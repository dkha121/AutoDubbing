"""9router (OpenAI-compatible) translation provider.

Talks to a self-hosted / proxy endpoint that exposes the OpenAI chat API but
*always streams* responses as Server-Sent Events (text/event-stream). The
standard OpenAI provider assumes a JSON body, so this provider has its own SSE
reader. base_url, token and model are all configurable — nothing hard-coded.

Defaults target the 9router endpoint with a Gemini model verified to translate
Chinese/English -> Vietnamese well.
"""
from __future__ import annotations

import json
import time

from core.logger import get_logger
from models.subtitle_segment import SubtitleSegment
from services.translation_service import (
    ProgressCb, TranslationProvider, build_prompt, chunk_segments, merge_translations,
)
from utils.json_utils import extract_json_block

logger = get_logger(__name__)


class RouterTranslationProvider(TranslationProvider):
    """LLM translation via an OpenAI-compatible streaming endpoint."""

    def _base_url(self) -> str:
        return (self.config.get("router.base_url", "") or "").rstrip("/")

    def _token(self) -> str:
        tok = self.config.get("router.token", "")
        if not tok:
            raise RuntimeError("Router token is not set (Settings → Router).")
        return tok

    def _model(self) -> str:
        return self.config.get("router.model", "ag/gemini-3-flash")

    def test_connection(self) -> tuple[bool, str]:
        try:
            out = self._chat("Reply with the single word ok.", "ok")
            return bool(out), f"Router OK (model={self._model()}): {out[:60]}"
        except Exception as exc:  # noqa: BLE001
            return False, f"Router error: {exc}"

    def _chat(self, system_prompt: str, user_content: str, max_retries: int = 3) -> str:
        last_err: Exception | None = None
        for attempt in range(1, max_retries + 1):
            try:
                return self._chat_once(system_prompt, user_content)
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                wait = min(20, 2 ** attempt)
                logger.warning("Router attempt %d failed: %s (retry in %ss)", attempt, exc, wait)
                time.sleep(wait)
        raise RuntimeError(f"Router request failed after {max_retries} retries: {last_err}")

    def _chat_once(self, system_prompt: str, user_content: str) -> str:
        import requests  # noqa: WPS433

        base = self._base_url()
        if not base:
            raise RuntimeError("Router base_url is not set (Settings → Router).")
        resp = requests.post(
            f"{base}/chat/completions",
            headers={"Authorization": f"Bearer {self._token()}",
                     "Content-Type": "application/json"},
            json={
                "model": self._model(),
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                "temperature": 0.3,
                "stream": True,
            },
            timeout=180,
            stream=True,
        )
        if resp.status_code == 429:
            raise RuntimeError("Rate limited (429)")
        if resp.status_code != 200:
            raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        # Server streams UTF-8 but omits charset; force it so Vietnamese
        # characters aren't mangled into latin-1 mojibake.
        resp.encoding = "utf-8"
        return self._read_sse(resp)

    @staticmethod
    def _read_sse(resp) -> str:
        """Accumulate `delta.content` chunks from an OpenAI-style SSE stream.

        Falls back to a plain JSON body if the server didn't actually stream.
        """
        # If not a stream, parse as a normal chat completion.
        ctype = resp.headers.get("content-type", "")
        if "text/event-stream" not in ctype:
            data = resp.json()
            return data["choices"][0]["message"]["content"]

        parts: list[str] = []
        for raw in resp.iter_lines(decode_unicode=True):
            if not raw or not raw.startswith("data:"):
                continue
            payload = raw[len("data:"):].strip()
            if payload == "[DONE]":
                break
            try:
                chunk = json.loads(payload)
            except json.JSONDecodeError:
                continue
            for choice in chunk.get("choices", []):
                piece = choice.get("delta", {}).get("content")
                if piece:
                    parts.append(piece)
        return "".join(parts)

    def _build_glossary(self, segments: list[SubtitleSegment], source_lang: str,
                        target_lang: str, max_retries: int) -> str:
        """Pass 1: scan the WHOLE script once and ask the model for a consistent
        glossary of proper nouns / recurring terms (source -> target). Returns a
        text block to embed in every chunk's prompt so names stay consistent.

        Only the source text is sent (lightweight). On any failure we return ""
        and translation proceeds normally without a glossary.
        """
        joined = "\n".join(s.source_text for s in segments if s.source_text.strip())
        if not joined.strip():
            return ""
        # Cap input so a very long script doesn't blow the context window; the
        # first ~12k chars are more than enough to surface the recurring names.
        if len(joined) > 12000:
            joined = joined[:12000]
        sys_prompt = (
            "You are a translation consistency assistant. Read the whole script "
            f"and list every PROPER NOUN and RECURRING TERM (character names, "
            f"places, brands, special terms) with ONE consistent {target_lang} "
            "translation each. Return ONLY a JSON object mapping source term -> "
            f"{target_lang} term, e.g. {{\"大博\":\"Đại Bác\"}}. No explanations."
        )
        try:
            raw = self._chat(sys_prompt, joined, max_retries)
            data = extract_json_block(raw)
            if isinstance(data, dict) and data:
                terms = "; ".join(f"{k} -> {v}" for k, v in data.items()
                                  if k and v)
                logger.info("Glossary built: %d terms", len(data))
                return terms
        except Exception as exc:  # noqa: BLE001 - glossary is best-effort
            logger.warning("Glossary build failed (%s); continuing without it", exc)
        return ""

    def translate_segments(
        self, segments: list[SubtitleSegment], source_lang: str, target_lang: str = "vi",
        style: str = "Natural Vietnamese", glossary: dict | None = None,
        progress_cb: ProgressCb = None, custom_context: str | None = None,
    ) -> list[SubtitleSegment]:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        chunk_size = int(self.config.get("translation.chunk_size", 40))
        max_retries = int(self.config.get("translation.max_retries", 3))
        workers = max(1, int(self.config.get("translation.parallel_workers", 5)))
        use_glossary = bool(self.config.get("translation.use_glossary", True))

        # Pass 1: consistent glossary across the whole script (optional).
        ctx = custom_context or ""
        if use_glossary and len(segments) > chunk_size:
            if progress_cb:
                progress_cb(0.0, "Đang phân tích thuật ngữ chung…")
            terms = self._build_glossary(segments, source_lang, target_lang, max_retries)
            if terms:
                ctx = (ctx + "\n" if ctx else "") + (
                    "Use these EXACT translations for recurring terms/names "
                    f"consistently everywhere: {terms}"
                )

        system_prompt = build_prompt(style, glossary, ctx)
        chunks = list(chunk_segments(segments, chunk_size))
        total = max(1, len(segments))
        done = 0

        def _translate_chunk(chunk):
            payload = [
                {"index": s.index, "start": s.start, "end": s.end, "source_text": s.source_text}
                for s in chunk
            ]
            raw = self._chat(system_prompt, json.dumps(payload, ensure_ascii=False), max_retries)
            try:
                parsed = extract_json_block(raw)
            except Exception as exc:  # noqa: BLE001
                logger.error("Router JSON parse failed: %s | raw head: %s", exc, raw[:200])
                parsed = []
            merge_translations(chunk, parsed if isinstance(parsed, list) else [])
            return len(chunk)

        if workers == 1 or len(chunks) <= 1:
            for chunk in chunks:
                n = _translate_chunk(chunk)
                done += n
                if progress_cb:
                    progress_cb(min(100.0, done / total * 100.0), f"Translated {done}/{total}")
        else:
            with ThreadPoolExecutor(max_workers=workers) as ex:
                futures = [ex.submit(_translate_chunk, c) for c in chunks]
                for fut in as_completed(futures):
                    done += fut.result()
                    if progress_cb:
                        progress_cb(min(100.0, done / total * 100.0), f"Translated {done}/{total}")
        return segments

    def estimate_cost(self, segments) -> str:
        chars = sum(len(s.source_text) for s in segments)
        return f"~{chars:,} chars via {self._model()} (your router / key)"
