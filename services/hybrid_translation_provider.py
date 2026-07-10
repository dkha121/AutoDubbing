"""Hybrid translation provider.

Strategy: run the fast local provider first to get a baseline, then (if an API
key is configured) refine with an API provider. If the API is unavailable, the
local result is returned, so the pipeline never hard-fails.
"""
from __future__ import annotations

from core.logger import get_logger
from models.subtitle_segment import SubtitleSegment
from services.local_translation_provider import LocalTranslationProvider
from services.translation_service import ProgressCb, TranslationProvider

logger = get_logger(__name__)


class HybridTranslationProvider(TranslationProvider):
    def __init__(self, config=None) -> None:
        super().__init__(config)
        self.local = LocalTranslationProvider(self.config)

    def _api_provider(self) -> TranslationProvider | None:
        if self.config.get("api_keys.openai_api_key"):
            from services.openai_translation_provider import OpenAITranslationProvider
            return OpenAITranslationProvider(self.config)
        if self.config.get("api_keys.gemini_api_key"):
            from services.gemini_translation_provider import GeminiTranslationProvider
            return GeminiTranslationProvider(self.config)
        return None

    def translate_segments(
        self, segments: list[SubtitleSegment], source_lang: str, target_lang: str = "vi",
        style: str = "Natural Vietnamese", glossary: dict | None = None,
        progress_cb: ProgressCb = None, custom_context: str | None = None,
    ) -> list[SubtitleSegment]:
        api = self._api_provider()
        if api is None:
            logger.info("Hybrid: no API key, using local provider only")
            return self.local.translate_segments(
                segments, source_lang, target_lang, style, glossary, progress_cb, custom_context
            )
        try:
            return api.translate_segments(
                segments, source_lang, target_lang, style, glossary, progress_cb, custom_context
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Hybrid: API failed (%s), falling back to local", exc)
            return self.local.translate_segments(
                segments, source_lang, target_lang, style, glossary, progress_cb, custom_context
            )

    def estimate_cost(self, segments) -> str:
        api = self._api_provider()
        return api.estimate_cost(segments) if api else "Local (no API key configured)"
