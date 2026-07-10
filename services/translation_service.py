"""Translation provider interface, prompt presets, and factory.

All providers consume and return lists of SubtitleSegment, preserving
index/start/end exactly. Concrete providers live in sibling modules.
"""
from __future__ import annotations

import abc
from typing import Callable

from core.app_config import AppConfig
from core.logger import get_logger
from models.subtitle_segment import SubtitleSegment

logger = get_logger(__name__)

ProgressCb = Callable[[float, str], None] | None

BASE_PROMPT = """You are a professional Vietnamese subtitle translator and dubbing script editor.

Task:
Translate the following subtitle segments into natural Vietnamese.

Rules:
- Keep original index, start, and end exactly.
- Do not merge, remove, or reorder subtitle segments.
- Preserve names, brands, numbers, and technical terms.
- Translate using full context, not line by line only.
- Vietnamese should be natural, concise, and suitable for spoken dubbing.
- Avoid overly long sentences.
- If style is {style}, make the sentence catchy but do not change meaning.
- Return valid JSON only.

Output JSON format:
[
  {{"index": 1, "start": 1.23, "end": 3.45, "source_text": "...", "vi_text": "..."}}
]
"""

STYLE_HINTS = {
    "Accurate": "Prioritise faithful, precise meaning over fluency.",
    "Natural Vietnamese": "Use everyday natural spoken Vietnamese.",
    "TikTok/Reels": "Short, punchy, catchy phrasing suited to short-form video.",
    "Movie Review": "Engaging reviewer tone, conversational and descriptive.",
    "Storytelling": "Warm narrative voice, smooth flowing sentences.",
    "Formal": "Polished, formal register suitable for documentaries.",
    "Funny": "Light, humorous tone while keeping the meaning.",
    "Dubbing Script": "Optimised for voice-over timing; concise, speakable lines.",
}


def build_prompt(style: str, glossary: dict | None = None,
                 custom_context: str | None = None) -> str:
    prompt = BASE_PROMPT.format(style=style)
    hint = STYLE_HINTS.get(style)
    if hint:
        prompt += f"\nStyle guidance: {hint}\n"
    if custom_context and custom_context.strip():
        prompt += (
            "\nExtra context about this video (follow it closely when choosing "
            f"tone, slang and word choice):\n{custom_context.strip()}\n"
        )
    if glossary:
        terms = "; ".join(f"{k} -> {v}" for k, v in glossary.items())
        prompt += f"\nGlossary (use these translations): {terms}\n"
    return prompt


def chunk_segments(segments: list[SubtitleSegment], size: int):
    """Yield lists of up to `size` segments."""
    for i in range(0, len(segments), max(1, size)):
        yield segments[i:i + size]


class TranslationProvider(abc.ABC):
    """Abstract base for all translation engines."""

    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config or AppConfig.instance()

    @abc.abstractmethod
    def translate_segments(
        self, segments: list[SubtitleSegment], source_lang: str, target_lang: str = "vi",
        style: str = "Natural Vietnamese", glossary: dict | None = None,
        progress_cb: ProgressCb = None, custom_context: str | None = None,
    ) -> list[SubtitleSegment]:
        """Translate and return segments with vi_text filled in."""
        raise NotImplementedError

    def test_connection(self) -> tuple[bool, str]:
        """Return (ok, message). Local providers are always available."""
        return True, "OK"

    def estimate_cost(self, segments: list[SubtitleSegment]) -> str:
        """Rough cost estimate string for UI display."""
        return "Local / no API cost"


def get_provider(engine: str, config: AppConfig | None = None) -> TranslationProvider:
    """Factory: resolve an engine name to a provider instance."""
    config = config or AppConfig.instance()
    engine = (engine or "local").lower()
    if engine == "router":
        from services.router_translation_provider import RouterTranslationProvider
        return RouterTranslationProvider(config)
    if engine == "google":
        from services.google_translation_provider import GoogleTranslationProvider
        return GoogleTranslationProvider(config)
    if engine == "openai":
        from services.openai_translation_provider import OpenAITranslationProvider
        return OpenAITranslationProvider(config)
    if engine == "gemini":
        from services.gemini_translation_provider import GeminiTranslationProvider
        return GeminiTranslationProvider(config)
    if engine == "hybrid":
        from services.hybrid_translation_provider import HybridTranslationProvider
        return HybridTranslationProvider(config)
    from services.local_translation_provider import LocalTranslationProvider
    return LocalTranslationProvider(config)


def merge_translations(
    originals: list[SubtitleSegment], translated: list[dict]
) -> list[SubtitleSegment]:
    """Merge JSON translation results back into originals by index.

    index/start/end are taken from the originals, never from the model output,
    to guarantee timing integrity.
    """
    by_index = {item.get("index"): item for item in translated if isinstance(item, dict)}
    for seg in originals:
        item = by_index.get(seg.index)
        if item and item.get("vi_text"):
            seg.vi_text = str(item["vi_text"]).strip()
            seg.status = "translated"
    return originals
