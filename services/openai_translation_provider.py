"""OpenAI translation provider.

Uses the OpenAI Python SDK if installed; otherwise falls back to a raw HTTPS
call via `requests`. API key comes from config/env, never hard-coded.
Implements chunking, retry with backoff, and basic cost estimation.
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


class OpenAITranslationProvider(TranslationProvider):
    def __init__(self, config=None) -> None:
        super().__init__(config)
        self.model = self.config.get("openai.model", "gpt-4o-mini")
        self.base_url = self.config.get("openai.base_url") or None

    def _api_key(self) -> str:
        key = self.config.get("api_keys.openai_api_key", "")
        if not key:
            raise RuntimeError("OpenAI API key is not set (Settings or OPENAI_API_KEY env).")
        return key

    def test_connection(self) -> tuple[bool, str]:
        try:
            self._call_chat("Reply with the single word: ok", "Return ok")
            return True, "OpenAI connection OK"
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)

    def _call_chat(self, system_prompt: str, user_content: str,
                   max_retries: int = 3) -> str:
        """Call chat completions with retry/backoff. Returns assistant text."""
        last_err: Exception | None = None
        for attempt in range(1, max_retries + 1):
            try:
                return self._call_chat_once(system_prompt, user_content)
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                wait = min(30, 2 ** attempt)
                logger.warning("OpenAI attempt %d failed: %s (retry in %ss)", attempt, exc, wait)
                time.sleep(wait)
        raise RuntimeError(f"OpenAI request failed after {max_retries} retries: {last_err}")

    def _call_chat_once(self, system_prompt: str, user_content: str) -> str:
        try:
            from openai import OpenAI  # noqa: WPS433
            client = OpenAI(api_key=self._api_key(), base_url=self.base_url)
            resp = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.3,
            )
            return resp.choices[0].message.content or ""
        except ImportError:
            return self._call_chat_requests(system_prompt, user_content)

    def _call_chat_requests(self, system_prompt: str, user_content: str) -> str:
        import requests  # noqa: WPS433
        base = self.base_url or "https://api.openai.com/v1"
        resp = requests.post(
            f"{base}/chat/completions",
            headers={"Authorization": f"Bearer {self._api_key()}",
                     "Content-Type": "application/json"},
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                "temperature": 0.3,
            },
            timeout=120,
        )
        if resp.status_code == 429:
            raise RuntimeError("Rate limited (429)")
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    def translate_segments(
        self, segments: list[SubtitleSegment], source_lang: str, target_lang: str = "vi",
        style: str = "Natural Vietnamese", glossary: dict | None = None,
        progress_cb: ProgressCb = None, custom_context: str | None = None,
    ) -> list[SubtitleSegment]:
        system_prompt = build_prompt(style, glossary, custom_context)
        chunk_size = int(self.config.get("translation.chunk_size", 40))
        max_retries = int(self.config.get("translation.max_retries", 3))
        total = max(1, len(segments))
        done = 0
        for chunk in chunk_segments(segments, chunk_size):
            payload = [
                {"index": s.index, "start": s.start, "end": s.end, "source_text": s.source_text}
                for s in chunk
            ]
            user_content = json.dumps(payload, ensure_ascii=False)
            raw = self._call_chat(system_prompt, user_content, max_retries)
            try:
                parsed = extract_json_block(raw)
            except Exception as exc:  # noqa: BLE001
                logger.error("Failed to parse OpenAI JSON: %s", exc)
                parsed = []
            merge_translations(chunk, parsed if isinstance(parsed, list) else [])
            done += len(chunk)
            if progress_cb:
                progress_cb(min(100.0, done / total * 100.0), f"Translated {done}/{total}")
        return segments

    def estimate_cost(self, segments) -> str:
        chars = sum(len(s.source_text) for s in segments)
        approx_tokens = chars / 4  # rough heuristic
        return f"~{approx_tokens:,.0f} input tokens ({self.model}); check current pricing"
