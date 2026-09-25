"""Phase -1.2 (G2) disposable experiment: Voxtral Realtime via transcribe.cpp on Windows.

Not product code. Nothing in src/ may import this. Run with Windows Python 3.12:

    python g2_stt_transcribe_cpp.py MODEL.gguf clip.wav=expected.txt [...] [--backend auto|cpu]

Measures model load, GPU memory, streaming latency at live-microphone pace, one-shot
speed, word error rate against the known script, and cancellation. Prints one JSON object.
Audio must be 16 kHz mono 16-bit WAV (synthetic test speech only).
"""

from __future__ import annotations

import argparse
import array
import json
import re
import subprocess
import sys
import threading
import time
import wave

t_import = time.perf_counter()
import transcribe_cpp  # noqa: E402

IMPORT_S = time.perf_counter() - t_import


def gpu_used_mib() -> int | None:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
        ).stdout
        return int(out.strip().splitlines()[0])
    except Exception:
        return None


def load_wav(path: str) -> array.array:
    with wave.open(path, "rb") as w:
        if (w.getsampwidth(), w.getframerate(), w.getnchannels()) != (2, 16000, 1):
            raise SystemExit(f"{path}: need 16 kHz 16-bit mono")
        pcm16 = array.array("h")
        pcm16.frombytes(w.readframes(w.getnframes()))
    return array.array("f", (s / 32768.0 for s in pcm16))


def words(text: str) -> list[str]:
    return re.sub(r"[^a-z0-9 ]+", " ", text.lower()).split()


def wer(ref: str, hyp: str) -> float:
    r, h = words(ref), words(hyp)
    d = list(range(len(h) + 1))
    for i, rw in enumerate(r, 1):
        prev, d[0] = d[0], i
        for j, hw in enumerate(h, 1):
            prev, d[j] = d[j], min(d[j] + 1, d[j - 1] + 1, prev + (rw != hw))
    return round(d[len(h)] / max(1, len(r)), 3)


def stream_clip(session, pcm: array.array, chunk_ms: int) -> dict:
    """Feed at live pace; latency is measured from the moment audio for a word exists."""
    chunk = 16000 * chunk_ms // 1000
    start = time.perf_counter()
    first_commit_s = None
    max_feed_s = 0.0
    with session.stream() as stream:
        for i in range(0, len(pcm), chunk):
            due = start + i / 16000
            now = time.perf_counter()
            if due > now:
                time.sleep(due - now)
            t0 = time.perf_counter()
            stream.feed(pcm[i:i + chunk])
            max_feed_s = max(max_feed_s, time.perf_counter() - t0)
            if first_commit_s is None and stream.text().committed.strip():
                first_commit_s = time.perf_counter() - start
        audio_end = start + len(pcm) / 16000
        t_fin = time.perf_counter()
        stream.finalize()
        done = time.perf_counter()
        text = stream.text().committed.strip()
    return {
        "chunk_ms": chunk_ms,
        "first_committed_text_s": round(first_commit_s, 3) if first_commit_s else None,
        "max_feed_call_s": round(max_feed_s, 3),
        "finalize_s": round(done - t_fin, 3),
        "final_text_after_audio_end_s": round(done - audio_end, 3),
        "fell_behind_live": (t_fin - audio_end) > 0.5,
        "text": text,
    }


def cancel_test(model, pcm: array.array) -> dict:
    with model.session() as session:
        result: dict = {}

        def run() -> None:
            t0 = time.perf_counter()
            try:
                session.run(pcm)
                result["outcome"] = "completed_before_cancel"
            except Exception as exc:  # expect Aborted
                result["outcome"] = type(exc).__name__
            result["run_returned_s"] = round(time.perf_counter() - t0, 3)

        th = threading.Thread(target=run)
        th.start()
        time.sleep(0.3)
        t_cancel = time.perf_counter()
        session.cancel()
        th.join(timeout=30)
        result["returned_after_cancel_s"] = round(time.perf_counter() - t_cancel, 3)
        result["thread_stuck"] = th.is_alive()
        return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("model")
    ap.add_argument("clips", nargs="+", help="clip.wav=expected.txt")
    ap.add_argument("--backend", default="auto")
    ap.add_argument("--device", default=None, help="exact device name, e.g. CUDA0, Vulkan1, CPU")
    ap.add_argument("--chunk-ms", type=int, nargs="+", default=[80, 240])
    args = ap.parse_args()

    report: dict = {
        "python": sys.version.split()[0],
        "transcribe_cpp": getattr(transcribe_cpp, "__version__", "?"),
        "import_s": round(IMPORT_S, 3),
        "devices": [f"{d.device_type}:{getattr(d, 'name', '')}" for d in transcribe_cpp.backends()],
        "gpu_used_mib_before_load": gpu_used_mib(),
    }
    if args.device:
        device = next(d for d in transcribe_cpp.backends() if getattr(d, "name", "") == args.device)
        model_kwargs = {"device": device}
    else:
        model_kwargs = {"backend": args.backend}
    t0 = time.perf_counter()
    with transcribe_cpp.Model(args.model, **model_kwargs) as model:
        report["load_s"] = round(time.perf_counter() - t0, 3)
        report["gpu_used_mib_after_load"] = gpu_used_mib()
        # Warm-up: the first run pays one-time kernel/graph setup; measure warm behaviour.
        t_w = time.perf_counter()
        with model.session() as session:
            session.run(load_wav(args.clips[0].split("=", 1)[0]))
        report["warmup_s"] = round(time.perf_counter() - t_w, 3)
        report["model"] = f"{model.arch}/{model.variant} on {model.backend}"
        report["supports_streaming"] = model.capabilities.supports_streaming
        report["clips"] = []
        longest = None
        for spec in args.clips:
            wav, expected_path = spec.split("=", 1)
            expected = open(expected_path, encoding="utf-8-sig").read().strip()
            pcm = load_wav(wav)
            dur = len(pcm) / 16000
            if longest is None or len(pcm) > len(longest):
                longest = pcm
            clip = {"wav": wav.rsplit("\\", 1)[-1], "audio_s": round(dur, 2), "expected": expected}
            with model.session() as session:
                t1 = time.perf_counter()
                one = session.run(pcm).text.strip()
                el = time.perf_counter() - t1
            clip["one_shot"] = {"s": round(el, 3), "realtime_factor": round(el / dur, 3),
                                "wer": wer(expected, one), "text": one}
            clip["streams"] = []
            for ms in args.chunk_ms:
                with model.session() as session:
                    s = stream_clip(session, pcm, ms)
                s["wer"] = wer(expected, s["text"])
                clip["streams"].append(s)
            report["clips"].append(clip)
        report["gpu_used_mib_peak_after_runs"] = gpu_used_mib()
        report["cancel"] = cancel_test(model, longest)
    report["gpu_used_mib_after_unload"] = gpu_used_mib()
    print(json.dumps(report, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
