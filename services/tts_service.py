"""Text-to-speech service: provider interface + Piper/XTTS/Custom + timeline mux.

Piper is the default local engine (invoked as an external binary). XTTS and
Custom are placeholders with the same interface so engines are swappable.
synthesize_segments() renders one clip per subtitle and the FFmpeg-based
assembler places each clip on the timeline at its start time.
"""
from __future__ import annotations

import abc
import subprocess
import wave
from pathlib import Path
from typing import Callable

from core.app_config import AppConfig
from core.logger import get_logger
from models.subtitle_segment import SubtitleSegment
from utils.validation_utils import binary_available

logger = get_logger(__name__)

ProgressCb = Callable[[float, str], None] | None


class TTSProvider(abc.ABC):
    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config or AppConfig.instance()

    @abc.abstractmethod
    def synthesize(self, text: str, voice: str, output_path: str,
                   speed: float = 1.0, pitch: float = 0.0) -> str:
        """Render `text` to a WAV file at output_path. Returns the path."""
        raise NotImplementedError

    # How many clips to synthesize concurrently. Network engines (edge) benefit
    # a lot from parallelism; local GPU engines (VoxCPM) override this to 1.
    parallel_workers = 6

    def synthesize_segments(
        self, segments: list[SubtitleSegment], voice_map: dict[str, str],
        output_folder: str, speed: float = 1.0, progress_cb: ProgressCb = None,
    ) -> list[str]:
        """Render each segment to its own clip (parallel where safe).

        Returns clip paths in the SAME order as `segments`.
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        out = Path(output_folder)
        out.mkdir(parents=True, exist_ok=True)
        total = max(1, len(segments))
        default_voice = next(iter(voice_map.values()), "") if voice_map else ""

        jobs = []  # (index_in_list, clip_path, text, voice)
        clips: list[str] = [""] * len(segments)
        for i, seg in enumerate(segments):
            text = seg.display_text()
            voice = (seg.voice or voice_map.get(seg.speaker or "", default_voice))
            clip_path = str(out / f"seg_{seg.index:05d}.wav")
            clips[i] = clip_path
            if text.strip():
                jobs.append((i, clip_path, text, voice))

        workers = max(1, int(self.parallel_workers))
        if self.parallel_workers > 1:  # allow config to tune network engines
            workers = max(1, int(self.config.get("tts.parallel_workers", workers)))
        done = 0

        def _one(job):
            _i, _path, _text, _voice = job
            self.synthesize(_text, _voice, _path, speed)
            return _i

        if workers == 1:
            for job in jobs:
                _one(job)
                done += 1
                if progress_cb:
                    progress_cb(min(100.0, done / total * 100.0), f"TTS {done}/{total}")
        else:
            with ThreadPoolExecutor(max_workers=workers) as ex:
                futures = [ex.submit(_one, job) for job in jobs]
                for fut in as_completed(futures):
                    fut.result()  # re-raise any error
                    done += 1
                    if progress_cb:
                        progress_cb(min(100.0, done / total * 100.0), f"TTS {done}/{total}")
        return clips

    def is_available(self) -> tuple[bool, str]:
        return True, "OK"





class XTTSProvider(TTSProvider):
    """Placeholder for Coqui XTTS-v2 (voice cloning). Interface-compatible."""

    def is_available(self) -> tuple[bool, str]:
        return False, "XTTS engine not yet wired. Install TTS and implement synthesize()."

    def synthesize(self, text: str, voice: str, output_path: str,
                   speed: float = 1.0, pitch: float = 0.0) -> str:
        raise NotImplementedError("XTTS provider is a placeholder. See tts_service.py.")


class EdgeTTSProvider(TTSProvider):
    """Microsoft Edge neural TTS (free, online, no API key).

    Produces high-quality Vietnamese voices. edge-tts outputs MP3, which we
    convert to 44.1kHz WAV via FFmpeg so the timeline assembler can mix it.
    `voice` is an Edge voice id, e.g. 'vi-VN-HoaiMyNeural' (female) or
    'vi-VN-NamMinhNeural' (male).
    """

    DEFAULT_FEMALE = "vi-VN-HoaiMyNeural"
    DEFAULT_MALE = "vi-VN-NamMinhNeural"

    def is_available(self) -> tuple[bool, str]:
        try:
            import edge_tts  # noqa: WPS433,F401
            return True, "edge-tts available (needs internet)"
        except ImportError:
            return False, "edge-tts not installed. Run: pip install edge-tts"

    def synthesize(self, text: str, voice: str, output_path: str,
                   speed: float = 1.0, pitch: float = 0.0) -> str:
        import asyncio
        import re

        import edge_tts  # noqa: WPS433
        from services.ffmpeg_service import FFmpegService

        voice = voice or self.DEFAULT_FEMALE
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        # edge-tts raises NoAudioReceived if the text has no speakable content
        # (only punctuation, dashes, lone digits/symbols). Treat such lines as
        # silence so a single bad subtitle line never crashes the whole job.
        if not re.search(r"[^\W_]", text or "", flags=re.UNICODE):
            return self._write_silence(out, 0.4)

        rate_pct = int(round((speed - 1.0) * 100))
        rate = f"{rate_pct:+d}%"
        pitch_hz = f"{int(round(pitch)):+d}Hz" if pitch else "+0Hz"
        mp3_path = str(out.with_suffix(".mp3"))

        async def _run() -> None:
            comm = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch_hz)
            await comm.save(mp3_path)

        import time
        last_err: Exception | None = None
        for attempt in range(1, 6):
            try:
                asyncio.run(_run())
                FFmpegService(self.config).convert_audio_to_wav(mp3_path, output_path)
                try:
                    Path(mp3_path).unlink(missing_ok=True)
                except OSError:
                    pass
                return output_path
            except Exception as exc:  # noqa: BLE001 - edge-tts / network hiccups
                last_err = exc
                logger.warning("edge-tts attempt %d failed (%s): %s", attempt, voice, exc)
                if attempt < 5:
                    time.sleep(1.0)

        # All retries failed (e.g. transient server issue): emit silence so the
        # timeline assembly still succeeds rather than aborting the job.
        logger.error("edge-tts gave up on a line, inserting silence: %s", last_err)
        return self._write_silence(out, 0.6)

    def _write_silence(self, out: Path, seconds: float) -> str:
        """Write a short silent 16kHz mono WAV at `out`."""
        import wave

        out.parent.mkdir(parents=True, exist_ok=True)
        frames = int(16000 * max(0.1, seconds))
        with wave.open(str(out), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(b"\x00\x00" * frames)
        return str(out)


class CustomTTSProvider(TTSProvider):
    """Placeholder for any custom/HTTP TTS engine."""

    def is_available(self) -> tuple[bool, str]:
        return False, "Custom TTS engine not configured."

    def synthesize(self, text: str, voice: str, output_path: str,
                   speed: float = 1.0, pitch: float = 0.0) -> str:
        raise NotImplementedError("Custom provider is a placeholder.")


class VoxCPMProvider(TTSProvider):
    """VoxCPM2 (OpenBMB) — tokenizer-free local TTS, 30 languages incl. Vietnamese.

    Voice consistency: VoxCPM is a diffusion model, so plain synthesis produces a
    DIFFERENT random voice on every call. To keep ONE voice across all subtitle
    lines, this provider builds a single "anchor" clip once and then clones every
    line from that anchor via `reference_wav_path`. The anchor is created from:
      - clone  : the user's reference WAV (that voice is the anchor)
      - design : a short clip synthesised from a natural-language description,
                 using VoxCPM's "(description)text" control format
      - default: a short clip with the model's own voice (then locked in)

    The `voice` argument encodes the choice:
      - "clone:/path/to.wav"
      - "design:<description>"   (e.g. "design:warm young female voice")
      - "" / "default"
    The 2B model is loaded once and cached on the class. Output is 48kHz.
    """

    _model = None  # class-level cache shared across instances
    parallel_workers = 1  # local GPU: keep sequential to avoid VRAM contention

    # Natural-language voice descriptions for quick gender presets (English
    # control text works well; the spoken text stays Vietnamese).
    GENDER_PRESETS = {
        "nu": "a warm, natural young female voice, clear and friendly",
        "nam": "a warm, natural adult male voice, clear and steady",
        "female": "a warm, natural young female voice, clear and friendly",
        "male": "a warm, natural adult male voice, clear and steady",
    }

    def _settings(self) -> dict:
        return self.config.get("tts.voxcpm", {}) or {}

    def is_available(self) -> tuple[bool, str]:
        try:
            import voxcpm  # noqa: WPS433,F401
            return True, "VoxCPM available (loads ~2B model on first use)"
        except ImportError:
            return False, "VoxCPM not installed. Run: pip install voxcpm"

    def _ensure_model(self):
        if VoxCPMProvider._model is not None:
            return VoxCPMProvider._model
        from voxcpm import VoxCPM  # noqa: WPS433
        model_name = self._settings().get("model", "openbmb/VoxCPM2")
        logger.info("Loading VoxCPM model %s (first run downloads weights)…", model_name)
        VoxCPMProvider._model = VoxCPM.from_pretrained(model_name, load_denoiser=False)
        return VoxCPMProvider._model

    @staticmethod
    def _design_text(description: str, text: str) -> str:
        """VoxCPM voice-design format: '(description)the text to speak'."""
        description = (description or "").strip()
        return f"({description}){text}" if description else text

    def _parse_voice(self, voice: str) -> tuple[str, str]:
        """Return (mode, param) from the encoded voice string / config."""
        s = self._settings()
        if voice:
            if voice.startswith("clone:"):
                return "clone", voice[len("clone:"):]
            if voice.startswith("design:"):
                return "design", voice[len("design:"):]
            if voice in ("", "default"):
                return "default", ""
            # bare word like "nam"/"nu" -> treat as a design preset
            return "design", self.GENDER_PRESETS.get(voice.lower(), voice)
        mode = s.get("mode", "default")
        if mode == "clone":
            return "clone", (s.get("reference_wav", "") or "")
        if mode == "design":
            return "design", (s.get("design_prompt", "") or "")
        return "default", ""

    def _prepare_reference(self, ref_path: str, out_dir: "Path | None" = None) -> str:
        """Transcode a user-supplied clone reference into a clean PCM WAV.

        VoxCPM loads the reference via librosa/soundfile, which only reads real
        PCM/float WAV. Files saved with a .wav extension are often a different
        container/codec (e.g. snaptik/TikTok downloads), so soundfile raises
        "Format not recognised" and the whole job dies. Re-encoding through
        FFmpeg guarantees a valid mono WAV; we also trim to a short clip since a
        long reference is slow to clone and can exhaust VRAM.
        """
        from services.ffmpeg_service import FFmpegService

        src = Path(ref_path)
        target_dir = Path(out_dir) if out_dir else Path(self.config.temp_folder())
        target_dir.mkdir(parents=True, exist_ok=True)
        clean = target_dir / f"_ref_{src.stem}.wav"

        max_sec = float(self._settings().get("reference_max_sec", 20) or 0)
        ff = FFmpegService(self.config)
        cmd = [ff.ffmpeg, "-y", "-i", str(src)]
        if max_sec > 0:
            cmd += ["-t", f"{max_sec:.2f}"]
        cmd += ["-vn", "-acodec", "pcm_s16le", "-ar", "24000", "-ac", "1", str(clean)]
        ff._run(cmd)
        if not clean.exists() or clean.stat().st_size <= 44:  # 44 = empty WAV header
            raise RuntimeError(
                f"Reference audio has no usable audio stream: {src.name}"
            )
        logger.info("Prepared VoxCPM reference: %s -> %s", src.name, clean.name)
        return str(clean)

    def _raw_generate(self, model, text: str, reference_wav: str | None = None,
                      prompt_text: str | None = None) -> "object":
        kwargs: dict = {"text": text, "cfg_value": 2.0, "inference_timesteps": 10}
        if reference_wav:
            kwargs["reference_wav_path"] = reference_wav
            if prompt_text:
                kwargs["prompt_wav_path"] = reference_wav
                kwargs["prompt_text"] = prompt_text
        return model.generate(**kwargs)

    def synthesize(self, text: str, voice: str, output_path: str,
                   speed: float = 1.0, pitch: float = 0.0) -> str:
        """Single-clip synthesis (used for previews / non-batch callers)."""
        import soundfile as sf  # noqa: WPS433
        model = self._ensure_model()
        mode, param = self._parse_voice(voice)
        if mode == "clone" and param:
            ref = self._prepare_reference(param)
            wav = self._raw_generate(model, text, reference_wav=ref,
                                     prompt_text=self._settings().get("prompt_text") or None)
        elif mode == "design" and param:
            wav = self._raw_generate(model, self._design_text(param, text))
        else:
            wav = self._raw_generate(model, text)
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        sf.write(output_path, wav, model.tts_model.sample_rate)
        return output_path

    def synthesize_segments(
        self, segments, voice_map, output_folder, speed: float = 1.0,
        progress_cb=None,
    ) -> list[str]:
        """Render every line with ONE consistent voice via an anchor clip.

        Step 1: build/locate the anchor WAV (the fixed voice).
        Step 2: clone every subtitle line from that anchor so the timbre never
        changes between lines.
        """
        import soundfile as sf  # noqa: WPS433
        model = self._ensure_model()
        out = Path(output_folder)
        out.mkdir(parents=True, exist_ok=True)

        voice = next(iter(voice_map.values()), "") if voice_map else ""
        mode, param = self._parse_voice(voice)

        # ---- Step 1: anchor ----
        anchor_path: str
        if mode == "clone" and param and Path(param).exists():
            anchor_path = self._prepare_reference(param, out_dir=out)
        else:
            anchor_path = str(out / "_anchor.wav")
            seed_text = "Xin chào, đây là giọng đọc lồng tiếng tiếng Việt."
            if mode == "design" and param:
                seed_text = self._design_text(param, seed_text)
            if progress_cb:
                progress_cb(1.0, "Tạo giọng neo (cố định)…")
            anchor_wav = self._raw_generate(model, seed_text)
            sf.write(anchor_path, anchor_wav, model.tts_model.sample_rate)

        # ---- Step 2: clone every line from the anchor ----
        clips: list[str] = []
        total = max(1, len(segments))
        for i, seg in enumerate(segments, start=1):
            text = seg.display_text()
            clip_path = str(out / f"seg_{seg.index:05d}.wav")
            if text.strip():
                wav = self._raw_generate(model, text, reference_wav=anchor_path)
                sf.write(clip_path, wav, model.tts_model.sample_rate)
            clips.append(clip_path)
            if progress_cb:
                progress_cb(min(100.0, i / total * 100.0), f"VoxCPM {i}/{total}")
        return clips


def get_tts_provider(engine: str, config: AppConfig | None = None) -> TTSProvider:
    engine = (engine or "edge").lower()
    if engine in ("edge", "edge-tts", "edge_tts"):
        return EdgeTTSProvider(config)
    if engine in ("voxcpm", "voxcpm2"):
        return VoxCPMProvider(config)
    if engine == "xtts":
        return XTTSProvider(config)
    if engine == "custom":
        return CustomTTSProvider(config)
    return EdgeTTSProvider(config)


# ---- timeline assembly ----------------------------------------------
def _wav_duration(path: str) -> float:
    try:
        with wave.open(path, "rb") as w:
            return w.getnframes() / float(w.getframerate())
    except (wave.Error, OSError, EOFError):
        return 0.0


def _atempo_chain(tempo: float) -> str:
    """FFmpeg atempo only accepts 0.5–2.0 per filter. To speed up beyond 2.0x
    we chain multiple atempo filters whose factors multiply to `tempo`."""
    if tempo <= 2.0:
        return f"atempo={tempo:.3f}"
    parts = []
    remaining = tempo
    while remaining > 2.0:
        parts.append("atempo=2.0")
        remaining /= 2.0
    parts.append(f"atempo={remaining:.3f}")
    return ",".join(parts)


class TTSAssembler:
    """Places per-segment clips onto a single timeline track using FFmpeg.

    Optional time-fitting compresses any clip that would overrun its slot (the
    gap until the next segment starts) by speeding it up with `atempo`, capped
    at `max_speed` so speech stays intelligible. This eliminates the cumulative
    drift you get when Vietnamese lines are longer than the source lines.
    """

    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config or AppConfig.instance()

    def _slot_seconds(self, valid, i: int, total_duration: float) -> float:
        """Available time for clip i = until next segment's start (or end)."""
        seg = valid[i][0]
        if i + 1 < len(valid):
            nxt_start = valid[i + 1][0].start
        else:
            nxt_start = total_duration if total_duration > 0 else seg.end
        return max(0.0, nxt_start - seg.start)

    def assemble(self, segments: list[SubtitleSegment], clips: list[str],
                 output_wav: str, total_duration: float,
                 fit_timeline: bool = True, max_speed: float = 1.6,
                 min_gap: float = 0.05) -> str:
        """Mix each clip at its segment start time using (atempo)+adelay+amix.

        Args:
            fit_timeline: speed up overrunning clips so they fit their slot.
            max_speed: hard cap on the atempo factor (>1 = faster).
            min_gap: leave this many seconds before the next line as breathing room.
        """
        from services.ffmpeg_service import FFmpegService
        ff = FFmpegService(self.config)

        valid = [(seg, clip) for seg, clip in zip(segments, clips)
                 if clip and Path(clip).exists() and _wav_duration(clip) > 0]
        if not valid:
            raise RuntimeError("No TTS clips were produced.")

        # Windows caps a command line at ~32KB. With many subtitle lines the
        # adelay/amix graph + the per-clip -i inputs blow past that limit
        # (WinError 206). So we mix in BATCHES: each batch is a self-contained
        # ffmpeg call writing a partial WAV, then the partials are amix'ed.
        out_dir = Path(output_wav).parent
        batch_size = 50
        partials: list[str] = []
        fitted = 0
        for b0 in range(0, len(valid), batch_size):
            batch = valid[b0:b0 + batch_size]
            inputs: list[str] = []
            filters: list[str] = []
            for j, (seg, clip) in enumerate(batch):
                inputs += ["-i", clip]
                dur = _wav_duration(clip)
                tempo = 1.0
                if fit_timeline:
                    gi = b0 + j  # global index for slot calc
                    slot = self._slot_seconds(valid, gi, total_duration) - min_gap
                    if slot > 0.1 and dur > slot:
                        tempo = min(max_speed, dur / slot)
                        if tempo > 1.01:
                            fitted += 1
                delay_ms = int(seg.start * 1000)
                # Force every clip to 44.1kHz FIRST. edge-tts clips are 16kHz;
                # if fed straight into amix (which outputs 44.1kHz) the 16kHz
                # audio gets played back stretched ~2.75x -> "slow motion" voice.
                chain = f"[{j}:a]aresample=44100,"
                if tempo > 1.01:
                    chain += _atempo_chain(tempo) + ","
                chain += f"adelay={delay_ms}|{delay_ms}[a{j}]"
                filters.append(chain)
            mix_inputs = "".join(f"[a{j}]" for j in range(len(batch)))
            filters.append(
                f"{mix_inputs}amix=inputs={len(batch)}:duration=longest:normalize=0[out]"
            )
            partial = str(out_dir / f"_dub_part_{b0:05d}.wav")
            self._run_filter(ff, inputs, ";".join(filters), partial)
            partials.append(partial)

        # Mix the batch partials together (few inputs -> safe on the command line).
        if len(partials) == 1:
            Path(partials[0]).replace(output_wav)
        else:
            inputs = []
            for p in partials:
                inputs += ["-i", p]
            mix = "".join(f"[{k}:a]" for k in range(len(partials)))
            graph = f"{mix}amix=inputs={len(partials)}:duration=longest:normalize=0[out]"
            self._run_filter(ff, inputs, graph, output_wav)
            for p in partials:
                try:
                    Path(p).unlink(missing_ok=True)
                except OSError:
                    pass

        logger.info("Assembled %d clips in %d batch(es), %d time-fitted (max_speed=%.2f)",
                    len(valid), len(partials), fitted, max_speed)
        return output_wav

    def _run_filter(self, ff, inputs: list[str], graph: str, output_wav: str) -> None:
        """Run one ffmpeg amix call, passing the filter graph via a script file
        so it never bloats the command line (avoids Windows WinError 206)."""
        import tempfile
        script = None
        try:
            with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False,
                                             encoding="utf-8") as f:
                f.write(graph)
                script = f.name
            cmd = [ff.ffmpeg, "-y", *inputs,
                   "-filter_complex_script", script,
                   "-map", "[out]",
                   "-acodec", "pcm_s16le", "-ar", "44100", output_wav]
            ff._run(cmd)
        finally:
            if script:
                try:
                    Path(script).unlink(missing_ok=True)
                except OSError:
                    pass
