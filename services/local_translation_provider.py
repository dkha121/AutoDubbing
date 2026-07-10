"""Local translation provider.

This is a working placeholder that fills vi_text so the whole pipeline runs
offline with zero heavy dependencies. The `_translate_batch` method is the
single seam to replace with a real model (NLLB / EnViT5 / SeamlessM4T):

    def _translate_batch(self, texts, source_lang, target_lang) -> list[str]:
        ...load a transformers model and return translations...

Everything else (chunking, progress, index preservation) stays the same.
"""
from __future__ import annotations

from core.logger import get_logger
from models.subtitle_segment import SubtitleSegment
from services.translation_service import ProgressCb, TranslationProvider, chunk_segments

logger = get_logger(__name__)


class LocalTranslationProvider(TranslationProvider):
    """Offline provider. Default impl echoes source with a [VI] marker."""

    def __init__(self, config=None) -> None:
        super().__init__(config)
        self._model = None  # reserved for a future transformers pipeline

    def _ensure_model(self) -> None:
        """Hook to lazily load a local MT model. No-op in the placeholder.

        To enable NLLB, install transformers+torch and implement here:
            from transformers import pipeline
            self._model = pipeline("translation", model="facebook/nllb-200-distilled-600M")
        """
        return

    def _translate_batch(self, texts: list[str], source_lang: str, target_lang: str) -> list[str]:
        """Translate a batch of strings. Replace with a real model call.

        Placeholder behaviour: returns the source text prefixed so the user can
        see the pipeline works end-to-end before wiring a model.
        """
        self._ensure_model()
        return [f"[VI] {t}" if t else t for t in texts]

    def translate_segments(
        self, segments: list[SubtitleSegment], source_lang: str, target_lang: str = "vi",
        style: str = "Natural Vietnamese", glossary: dict | None = None,
        progress_cb: ProgressCb = None, custom_context: str | None = None,
    ) -> list[SubtitleSegment]:
        chunk_size = int(self.config.get("translation.chunk_size", 40))
        total = max(1, len(segments))
        done = 0
        for chunk in chunk_segments(segments, chunk_size):
            texts = [s.source_text for s in chunk]
            translations = self._translate_batch(texts, source_lang, target_lang)
            for seg, vi in zip(chunk, translations):
                seg.vi_text = vi
                seg.status = "translated"
            done += len(chunk)
            if progress_cb:
                progress_cb(min(100.0, done / total * 100.0), f"Translated {done}/{total}")
        logger.info("Local translation done for %d segments", len(segments))
        return segments

    def estimate_cost(self, segments) -> str:
        return "Local / no API cost"
