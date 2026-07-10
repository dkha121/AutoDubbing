"""Automatic Speech Recognition via faster-whisper.

The faster-whisper import is deferred to load_model() so the app can start and
run non-ASR features even if the (heavy) dependency or model is not installed.
"""
from __future__ import annotations

from typing import Callable

from core.app_config import AppConfig
from core.logger import get_logger
from models.subtitle_segment import SubtitleSegment

logger = get_logger(__name__)

ProgressCb = Callable[[float, str], None] | None


def resolve_device(device: str) -> str:
    """Resolve 'auto' to cuda if a CUDA-capable torch is present, else cpu."""
    if device != "auto":
        return device
    try:
        import torch  # noqa: WPS433 - optional dependency
        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def resolve_compute_type(compute_type: str, device: str) -> str:
    if compute_type != "auto":
        return compute_type
    return "float16" if device == "cuda" else "int8"


class ASRService:
    """Wraps a faster-whisper WhisperModel instance."""

    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config or AppConfig.instance()
        self._model = None
        self._loaded_key: tuple | None = None

    def load_model(self, model_name: str | None = None, device: str | None = None,
                   compute_type: str | None = None) -> None:
        model_name = model_name or self.config.get("asr.default_model", "small")
        device = resolve_device(device or self.config.get("asr.device", "auto"))
        compute_type = resolve_compute_type(
            compute_type or self.config.get("asr.compute_type", "auto"), device
        )
        key = (model_name, device, compute_type)
        if self._model is not None and self._loaded_key == key:
            return

        try:
            from faster_whisper import WhisperModel  # noqa: WPS433
        except ImportError as exc:
            raise RuntimeError(
                "faster-whisper is not installed. Run: pip install faster-whisper"
            ) from exc

        download_root = str(self.config.get("models_folder", "./data/models"))
        logger.info("Loading Whisper model=%s device=%s compute=%s", model_name, device, compute_type)
        try:
            self._model = WhisperModel(
                model_name, device=device, compute_type=compute_type,
                download_root=download_root,
            )
        except Exception as exc:
            # Common case: CUDA libs missing -> let caller offer CPU fallback.
            raise RuntimeError(f"Failed to load Whisper model on {device}: {exc}") from exc
        self._loaded_key = key

    def transcribe(self, audio_path: str, language: str | None = None,
                   progress_cb: ProgressCb = None) -> tuple[list[SubtitleSegment], str]:
        """Transcribe audio. Returns (segments, detected_language).

        Whisper's raw segments are huge (up to 30s, many sentences merged).
        For dubbing we want "one spoken phrase = one subtitle line" matching
        the video's rhythm, so we use word-level timestamps and re-split into
        short lines on pauses / clause punctuation / a max length. This only
        SPLITS (never merges) — fast Douyin narration becomes ~3s lines.
        """
        if self._model is None:
            self.load_model()
        assert self._model is not None

        lang = None if (language in (None, "auto", "")) else language
        segments_iter, info = self._model.transcribe(
            audio_path, language=lang, beam_size=5,
            word_timestamps=True,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 200},
        )
        detected = getattr(info, "language", lang or "unknown")
        total = getattr(info, "duration", 0.0) or 0.0

        words: list[tuple[float, float, str]] = []
        for seg in segments_iter:
            seg_words = getattr(seg, "words", None)
            if seg_words:
                for w in seg_words:
                    if w.word and w.word.strip():
                        words.append((float(w.start), float(w.end), w.word))
            else:
                words.append((float(seg.start), float(seg.end), seg.text))
            if progress_cb and total > 0:
                progress_cb(min(100.0, seg.end / total * 100.0), "Transcribing")

        results = self._split_into_lines(words, detected)
        logger.info("Transcribed %d lines from %d words (lang=%s)",
                    len(results), len(words), detected)
        return results, detected

    def _split_into_lines(self, words: list[tuple[float, float, str]],
                          lang: str) -> list[SubtitleSegment]:
        """Cut short subtitle lines: on a speaker pause, on a clause-ending
        punctuation once the line is long enough, or at a hard length cap.
        Always SPLITS, never merges — keeps lines synced to the speech."""
        if not words:
            return []
        pause = float(self.config.get("asr.pause_split_sec", 0.3))
        soft_sec = float(self.config.get("asr.soft_split_sec", 1.5))
        max_sec = float(self.config.get("asr.max_line_sec", 6.0))
        no_space = lang in ("zh", "ja", "th", "lo", "my", "km")
        joiner = "" if no_space else " "
        punct = "，,、。．.!?！？…;；:："

        segments: list[SubtitleSegment] = []
        buf: list[str] = []
        start_t = words[0][0]
        prev_end = words[0][0]
        idx = 0

        def flush(end_t: float):
            nonlocal buf, idx
            text = joiner.join(buf).strip().replace("  ", " ")
            if text:
                idx += 1
                segments.append(SubtitleSegment(
                    index=idx, start=round(start_t, 3), end=round(end_t, 3),
                    source_text=text,
                ))
            buf = []

        for w_start, w_end, w_text in words:
            wt = w_text.strip()
            if buf and (w_start - prev_end) > pause:
                flush(prev_end)
                start_t = w_start
            elif buf and (prev_end - start_t) >= soft_sec and buf[-1][-1:] in punct:
                flush(prev_end)
                start_t = w_start
            elif buf and (w_end - start_t) >= max_sec:
                flush(prev_end)
                start_t = w_start
            if not buf:
                start_t = w_start
            buf.append(wt)
            prev_end = w_end
        flush(prev_end)
        return segments
