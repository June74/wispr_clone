"""Phase -1.2 (G2) disposable experiment: live microphone -> Voxtral via transcribe.cpp.

Not product code. Run with Windows Python 3.12 in the experiment venv:

    python g2_live_mic.py MODEL.gguf [--device CUDA0] [--chunk-ms 80]

Read the passage aloud, then press Enter. Mirrors the planned design: the audio callback
only enqueues; a feeder thread calls feed(). Nothing is saved: no audio, no transcript file.
Prints live text, then a JSON summary.
"""

from __future__ import annotations

import argparse
import array
import json
import queue
import re
import threading
import time

import sounddevice as sd
import transcribe_cpp

PASSAGE = ("Please do not merge the pull request until Sarah reviews it. "
           "The meeting moved to Tuesday at four thirty, and the budget is twelve hundred dollars. "
           "Run pytest in the backend folder, then check the logs.")


def words(t: str) -> list[str]:
    return re.sub(r"[^a-z0-9 ]+", " ", t.lower()).split()


def wer(ref: str, hyp: str) -> float:
    r, h = words(ref), words(hyp)
    d = list(range(len(h) + 1))
    for i, rw in enumerate(r, 1):
        prev, d[0] = d[0], i
        for j, hw in enumerate(h, 1):
            prev, d[j] = d[j], min(d[j] + 1, d[j - 1] + 1, prev + (rw != hw))
    return round(d[len(h)] / max(1, len(r)), 3)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("model")
    ap.add_argument("--device", default="CUDA0")
    ap.add_argument("--chunk-ms", type=int, default=80)
    args = ap.parse_args()

    dev = next(d for d in transcribe_cpp.backends() if getattr(d, "name", "") == args.device)
    mic = sd.query_devices(kind="input")
    print(f"Loading model on {args.device}; microphone: {mic['name']}")
    frames = 16000 * args.chunk_ms // 1000
    q: "queue.Queue[bytes]" = queue.Queue(maxsize=500)  # bounded, like the planned audio queue
    overflow = {"n": 0, "max_depth": 0}
    level = {"peak": 0.0, "sumsq": 0.0, "n": 0, "status_flags": 0}

    def callback(indata, _frames, _time, status) -> None:  # only enqueue, never block
        if status:
            level["status_flags"] += 1
        try:
            q.put_nowait(bytes(indata))
        except queue.Full:
            overflow["n"] += 1

    with transcribe_cpp.Model(args.model, device=dev) as model:
        with model.session() as s:  # warm-up
            s.run(array.array("f", [0.0] * 16000))
        print("\nRead this aloud, then press Enter:\n\n  " + PASSAGE + "\n")
        stop = threading.Event()
        max_feed = [0.0]
        with model.session() as session, session.stream() as stream:
            def feeder() -> None:
                last = ""
                while not (stop.is_set() and q.empty()):
                    try:
                        chunk = q.get(timeout=0.05)
                    except queue.Empty:
                        continue
                    overflow["max_depth"] = max(overflow["max_depth"], q.qsize())
                    pcm = array.array("f", chunk)
                    if pcm:  # signal level only (no audio kept), on the feeder thread
                        level["peak"] = max(level["peak"], max(abs(x) for x in pcm))
                        level["sumsq"] += sum(x * x for x in pcm)
                        level["n"] += len(pcm)
                    t0 = time.perf_counter()
                    stream.feed(pcm)
                    max_feed[0] = max(max_feed[0], time.perf_counter() - t0)
                    t = stream.text()
                    line = f"{t.committed}\x1b[2m{t.tentative}\x1b[0m"
                    if line != last:
                        print(f"\r\x1b[K{line[-150:]}", end="", flush=True)
                        last = line

            ft = threading.Thread(target=feeder)
            with sd.RawInputStream(samplerate=16000, channels=1, dtype="float32",
                                   blocksize=frames, callback=callback):
                ft.start()
                t_start = time.perf_counter()
                input()
                t_enter = time.perf_counter()
            stop.set()
            ft.join()
            stream.finalize()
            t_final = time.perf_counter()
            final = stream.text().committed.strip()
            snap = stream.snapshot()
    import math
    rms = math.sqrt(level["sumsq"] / level["n"]) if level["n"] else 0.0
    dbfs = lambda v: round(20 * math.log10(v), 1) if v > 0 else None  # noqa: E731
    print("\n\nFinal:\n  " + final)
    print(json.dumps({
        "final_text": final,
        "final_chars": len(final),
        "language": getattr(snap, "language", None),
        "input_peak_dbfs": dbfs(level["peak"]),
        "input_rms_dbfs": dbfs(rms),
        "callback_status_flags": level["status_flags"],
        "mic": mic["name"], "device": args.device, "chunk_ms": args.chunk_ms,
        "spoken_s": round(t_enter - t_start, 1),
        "final_text_after_enter_s": round(t_final - t_enter, 3),
        "max_feed_call_s": round(max_feed[0], 3),
        "queue_max_depth_chunks": overflow["max_depth"], "queue_overflows": overflow["n"],
        "raw_wer_vs_passage": wer(PASSAGE, final),
        "note": "raw WER counts '4:30' vs 'four thirty' etc. as errors; judge the text too",
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
