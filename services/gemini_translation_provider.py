"""Gemini translation provider.

Uses google-generativeai if installed; otherwise falls back to the REST API via
`requests`. API key comes from config/env. Chunking + retry + cost estimate.
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


class GeminiTranslationProvider(TranslationProvider):
    def __init__(self, config=None) -> None:
        super().__init__(config)
        self.model = self.config.get("gemini.model", "gemini-1.5-flash")

    def _api_key(self) -> str:
        key = self.config.get("api_keys.gemini_api_key", "")
        if not key:
            raise RuntimeError("Gemini API key is not set (Settings or GEMINI_API_KEY env).")
        return key

    def test_connection(self) -> tuple[bool, str]:
        try:
            self._call("Return ok", "ok")
            return True, "Gemini connection OK"
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)

    def _call(self, system_prompt: str, user_content: str, max_retries: int = 3) -> str:
        last_err: Exception | None = None
        for attempt in range(1, max_retries + 1):
            try:
                return self._call_once(system_prompt, user_content)
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                wait = min(30, 2 ** attempt)
                logger.warning("Gemini attempt %d failed: %s (retry in %ss)", attempt, exc, wait)
                time.sleep(wait)
        raise RuntimeError(f"Gemini request failed after {max_retries} retries: {last_err}")

    def _call_once(self, system_prompt: str, user_content: str) -> str:
        try:
            import google.generativeai as genai  # noqa: WPS433
            genai.configure(api_key=self._api_key())
            model = genai.GenerativeModel(self.model, system_instruction=system_prompt)
            resp = model.generate_content(user_content)
            return resp.text or ""
        except ImportError:
            return self._call_rest(system_prompt, user_content)

    def _call_rest(self, system_prompt: str, user_content: str) -> str:
        import requests  # noqa: WPS433
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent?key={self._api_key()}"
        )
        resp = requests.post(
            url,
            json={
                "system_instruction": {"parts": [{"text": system_prompt}]},
                "contents": [{"parts": [{"text": user_content}]}],
            },
            timeout=120,
        )
        if resp.status_code == 429:
            raise RuntimeError("Rate limited (429)")
        resp.raise_for_status()
        data = resp.json()
        return data["candidates"][0]["content"]["parts"][0]["text"]

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
            raw = self._call(system_prompt, json.dumps(payload, ensure_ascii=False), max_retries)
            try:
                parsed = extract_json_block(raw)
            except Exception as exc:  # noqa: BLE001
                logger.error("Failed to parse Gemini JSON: %s", exc)
                parsed = []
            merge_translations(chunk, parsed if isinstance(parsed, list) else [])
            done += len(chunk)
            if progress_cb:
                progress_cb(min(100.0, done / total * 100.0), f"Translated {done}/{total}")
        return segments

    def estimate_cost(self, segments) -> str:
        chars = sum(len(s.source_text) for s in segments)
        return f"~{chars:,} source chars ({self.model}); check current pricing"
