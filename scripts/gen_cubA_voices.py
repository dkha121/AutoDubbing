"""Batch-generate the "Cụ Bá" character voice with VoxCPM (one-off job).

Reads a manifest (CSV with columns: filename, text, direction) and produces one
WAV per row, all in ONE consistent elderly-male Vietnamese voice. It reuses the
project's VoxCPMProvider anchor→clone trick so the timbre never drifts between
lines, then post-processes each clip with FFmpeg to match the delivery spec:

  - mono, PCM 16-bit, 48 kHz
  - loudness normalised to ~ -18 LUFS integrated, true peak <= -3 dBTP
  - dry: no music / reverb (whatever the model emits, we just normalise)
  - leading silence trimmed to <= 100 ms, trailing tail ~ 200 ms
  - slight slow-down (0.92x) to read older / steadier than a young voice

The `direction` column is guidance for a human; it is NOT spoken. Only `text`
is synthesised. Filenames are written EXACTLY as given in the manifest.

Usage:
    python scripts/gen_cubA_voices.py manifest.csv --out data/outputs/cu_ba
    # optional: clone from your own reference instead of a designed voice
    python scripts/gen_cubA_voices.py manifest.csv --ref my_grandpa.wav
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

# Make the project root importable when run as `python scripts/...`.
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from core.app_config import AppConfig  # noqa: E402
from core.logger import get_logger, setup_logging  # noqa: E402
from services.ffmpeg_service import FFmpegService  # noqa: E402

logger = get_logger("gen_cu_ba")

# English control text drives VoxCPM's voice "design"; the spoken text stays
# Vietnamese. This captures the Cụ Bá brief: elderly (70-75) Vietnamese man,
# warm, low, slightly hoarse, gentle and trustworthy, unhurried.
CU_BA_DESIGN = (
    "an elderly Vietnamese man, about seventy-five years old, with a warm, "
    "low, slightly hoarse and breathy voice, gentle, kind and wise, speaking "
    "calmly and a little slowly, like a beloved grandfather"
)

# Seed text used to build the fixed anchor voice (spoken in Vietnamese).
ANCHOR_SEED = "Cháu à, ngồi xuống đây, để ông kể cho cháu nghe chuyện ngày xưa."

TARGET_SPEED = 0.92          # read a touch slower than a young voice
TARGET_LUFS = -18.0
TARGET_TP = -3.0
TARGET_SR = 48000


def read_manifest(path: Path) -> list[dict]:
    """Read filename/text/direction rows from CSV (utf-8, header required)."""
    rows: list[dict] = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        cols = {c.lower().strip(): c for c in (reader.fieldnames or [])}
        if "filename" not in cols or "text" not in cols:
            raise SystemExit(
                "Manifest must have at least 'filename' and 'text' columns. "
                f"Found: {reader.fieldnames}"
            )
        for i, raw in enumerate(reader, start=2):  # line 2 = first data row
            fn = (raw.get(cols["filename"]) or "").strip()
            txt = (raw.get(cols["text"]) or "").strip()
            if not fn and not txt:
                continue
            if not fn or not txt:
                raise SystemExit(f"Row {i}: both filename and text are required.")
            rows.append({"filename": fn, "text": txt,
                         "direction": (raw.get(cols.get("direction", "")) or "").strip()})
    if not rows:
        raise SystemExit("Manifest has no usable rows.")
    # Guard against duplicate / missing filenames.
    names = [r["filename"] for r in rows]
    dupes = {n for n in names if names.count(n) > 1}
    if dupes:
        raise SystemExit(f"Duplicate filenames in manifest: {sorted(dupes)}")
    return rows


def post_process(ff: FFmpegService, raw_wav: Path, final_wav: Path) -> None:
    """Slow slightly, trim ONLY the leading/trailing silence, loudnorm, then
    pad to spec; downmix to mono 48k PCM16.

    Trimming uses the trim-head → reverse → trim-head → reverse trick so that
    silences INSIDE the line (after "...", commas, sentence breaks) are left
    untouched. A plain `silenceremove` with stop_periods would shred the line
    at every internal pause.
    """
    final_wav.parent.mkdir(parents=True, exist_ok=True)
    trim_head = ("silenceremove=start_periods=1:start_silence=0:"
                 "start_threshold=-45dB:detection=peak")
    af = (
        f"atempo={TARGET_SPEED:.3f},"
        f"{trim_head},areverse,{trim_head},areverse,"
        f"loudnorm=I={TARGET_LUFS}:TP={TARGET_TP}:LRA=11,"
        # leading silence ~50ms (<=100ms spec); trailing tail ~200ms
        "adelay=50|50,apad=pad_dur=0.2"
    )
    cmd = [
        ff.ffmpeg, "-y", "-i", str(raw_wav),
        "-af", af,
        "-ac", "1", "-ar", str(TARGET_SR), "-acodec", "pcm_s16le",
        str(final_wav),
    ]
    ff._run(cmd)


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate the Cụ Bá voice set with VoxCPM.")
    ap.add_argument("manifest", type=Path, help="CSV: filename,text,direction")
    ap.add_argument("--out", type=Path, default=Path("data/outputs/cu_ba"),
                    help="Output folder for the final WAVs")
    ap.add_argument("--ref", type=Path, default=None,
                    help="Optional reference WAV to clone instead of a designed voice")
    ap.add_argument("--keep-raw", action="store_true",
                    help="Keep the pre-FFmpeg model output for inspection")
    args = ap.parse_args()

    setup_logging()
    config = AppConfig.instance()

    from services.tts_service import VoxCPMProvider  # lazy: heavy import
    provider = VoxCPMProvider(config)
    ok, msg = provider.is_available()
    if not ok:
        raise SystemExit(f"VoxCPM not available: {msg}")
    ff = FFmpegService(config)
    if not ff.check_ffmpeg_available():
        raise SystemExit("FFmpeg not found. Set ffmpeg_path in config.json.")

    rows = read_manifest(args.manifest)
    logger.info("Manifest OK: %d lines", len(rows))

    import soundfile as sf  # noqa: WPS433
    model = provider._ensure_model()

    out = args.out
    raw_dir = out / "_raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    # ---- Build the fixed anchor voice ONCE (Cụ Bá) ----
    if args.ref and args.ref.exists():
        anchor = provider._prepare_reference(str(args.ref), out_dir=raw_dir)
        logger.info("Anchor = your reference: %s", args.ref.name)
    else:
        anchor = str(raw_dir / "_anchor_cu_ba.wav")
        seed = provider._design_text(CU_BA_DESIGN, ANCHOR_SEED)
        logger.info("Designing Cụ Bá anchor voice…")
        wav = provider._raw_generate(model, seed)
        sf.write(anchor, wav, model.tts_model.sample_rate)

    # ---- Clone every line from the anchor, then post-process ----
    failures: list[str] = []
    total = len(rows)
    for i, row in enumerate(rows, start=1):
        fn = row["filename"]
        if not fn.lower().endswith(".wav"):
            fn = fn + ".wav"
        raw_wav = raw_dir / fn
        final_wav = out / fn
        try:
            logger.info("[%d/%d] %s", i, total, fn)
            wav = provider._raw_generate(model, row["text"], reference_wav=anchor)
            sf.write(str(raw_wav), wav, model.tts_model.sample_rate)
            post_process(ff, raw_wav, final_wav)
            if not args.keep_raw:
                raw_wav.unlink(missing_ok=True)
        except Exception as exc:  # noqa: BLE001 - keep going, report at the end
            logger.error("FAILED %s: %s", fn, exc)
            failures.append(fn)

    logger.info("Done: %d/%d ok -> %s", total - len(failures), total, out)
    if not args.keep_raw:
        try:
            anchor_p = Path(anchor)
            if anchor_p.parent == raw_dir:
                anchor_p.unlink(missing_ok=True)
            raw_dir.rmdir()
        except OSError:
            pass
    if failures:
        logger.warning("These files failed: %s", failures)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
