"""Google translation provider via deep-translator (free, no API key).

Translates segment-by-segment using the public Google endpoint. Includes a
small retry and a graceful fallback (keeps source text) on failure so the
pipeline never hard-stops.
"""
from __future__ import annotations

import time

from core.logger import get_logger
from models.subtitle_segment import SubtitleSegment
from services.translation_service import ProgressCb, TranslationProvider, chunk_segments

logger = get_logger(__name__)

# Map our detected language codes (Whisper ISO-639-1) to what GoogleTranslator
# expects. Most codes match; the notable exceptions are Chinese variants.
_LANG_FIX = {
    "auto": "auto", "": "auto", "unknown": "auto",
    "zh": "zh-CN", "zh-cn": "zh-CN", "zh-tw": "zh-TW",
    "jw": "jv", "iw": "iw",
}


def _to_google_lang(code: str) -> str:
    if not code:
        return "auto"
    low = code.lower()
    return _LANG_FIX.get(low, low)


class GoogleTranslationProvider(TranslationProvider):
    """Free Google translation. No key required; needs internet access."""

    def _translator(self, source: str, target: str):
        from deep_translator import GoogleTranslator  # noqa: WPS433
        try:
            return GoogleTranslator(source=_to_google_lang(source), target=target)
        except Exception as exc:  # noqa: BLE001 - unsupported code -> auto-detect
            logger.warning("Source lang '%s' rejected (%s); falling back to auto", source, exc)
            return GoogleTranslator(source="auto", target=target)

    def test_connection(self) -> tuple[bool, str]:
        try:
            from deep_translator import GoogleTranslator
            out = GoogleTranslator(source="en", target="vi").translate("hello")
            return bool(out), f"Google OK ('hello' -> '{out}')"
        except Exception as exc:  # noqa: BLE001
            return False, f"Google translate unavailable: {exc}"

    def _translate_one(self, translator, text: str, retries: int = 3) -> str:
        if not text.strip():
            return ""
        for attempt in range(1, retries + 1):
            try:
                return translator.translate(text) or text
            except Exception as exc:  # noqa: BLE001
                logger.warning("Google translate attempt %d failed: %s", attempt, exc)
                time.sleep(min(8, 2 ** attempt))
        logger.error("Google translate gave up on a segment; keeping source text")
        return text

    def translate_segments(
        self, segments: list[SubtitleSegment], source_lang: str, target_lang: str = "vi",
        style: str = "Natural Vietnamese", glossary: dict | None = None,
        progress_cb: ProgressCb = None, custom_context: str | None = None,
    ) -> list[SubtitleSegment]:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        translator = self._translator(source_lang or "auto", target_lang)
        total = max(1, len(segments))
        workers = max(1, int(self.config.get("translation.parallel_workers", 8)))
        done = 0

        def _one(seg):
            seg.vi_text = self._translate_one(translator, seg.source_text)
            seg.status = "translated"

        if workers == 1 or total <= 1:
            for seg in segments:
                _one(seg)
                done += 1
                if progress_cb:
                    progress_cb(min(100.0, done / total * 100.0), f"Translated {done}/{total}")
        else:
            with ThreadPoolExecutor(max_workers=workers) as ex:
                futures = [ex.submit(_one, s) for s in segments]
                for fut in as_completed(futures):
                    fut.result()
                    done += 1
                    if progress_cb:
                        progress_cb(min(100.0, done / total * 100.0), f"Translated {done}/{total}")
        logger.info("Google translation done for %d segments", len(segments))
        return segments

    def estimate_cost(self, segments) -> str:
        return "Google (free, no API cost) — requires internet"
