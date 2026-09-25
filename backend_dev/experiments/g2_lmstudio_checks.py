"""Phase -1.2 (G2) disposable experiment: LM Studio as the cleanup server.

Not product code. Stdlib only; run from WSL (mirrored networking) or Windows:

    python3 g2_lmstudio_checks.py --lmstudio-dir /mnt/c/Users/<you>/.lmstudio

Sends only synthetic text carrying a random marker. Never loads, unloads or reconfigures
models (Cognee shares this server). Log check: searches recently modified LM Studio files
for the marker and reports only file names and hit counts, never log contents.
Prints one JSON object.
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import secrets
import subprocess
import time
import urllib.request

HOST, PORT = "127.0.0.1", 1234
MODEL = "meta-llama-3.1-8b-instruct"
SKIP_DIRS = {"models", "transcriptions", "audio", "credentials", "hub", "extensions", "bin"}


def get_json(path: str) -> dict:
    with urllib.request.urlopen(f"http://{HOST}:{PORT}{path}", timeout=10) as r:
        return json.load(r)


def chat(messages: list[dict], max_tokens: int = 200) -> tuple[str, float]:
    body = json.dumps({"model": MODEL, "messages": messages, "temperature": 0,
                       "max_tokens": max_tokens, "stream": False}).encode()
    req = urllib.request.Request(f"http://{HOST}:{PORT}/v1/chat/completions", data=body,
                                 headers={"Content-Type": "application/json"})
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=120) as r:
        out = json.load(r)
    return out["choices"][0]["message"]["content"], time.perf_counter() - t0


def gpu_util() -> int | None:
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=5).stdout
        return int(out.strip().splitlines()[0])
    except Exception:
        return None


def ttft(prompt: str) -> float:
    """Time to first streamed token for a short request."""
    body = json.dumps({"model": MODEL, "messages": [{"role": "user", "content": prompt}],
                       "temperature": 0, "max_tokens": 5, "stream": True})
    conn = http.client.HTTPConnection(HOST, PORT, timeout=120)
    t0 = time.perf_counter()
    conn.request("POST", "/v1/chat/completions", body, {"Content-Type": "application/json"})
    resp = conn.getresponse()
    while True:
        line = resp.readline()
        if not line or line.startswith(b"data:"):
            break
    dt = time.perf_counter() - t0
    conn.close()
    return dt


def disconnect_test(marker: str) -> dict:
    body = json.dumps({"model": MODEL, "temperature": 0, "max_tokens": 1500, "stream": True,
                       "messages": [{"role": "user", "content":
                                     f"[{marker}] Count from 1 to 600, one number per line."}]})
    base = ttft("Say OK.")
    idle = [gpu_util() for _ in range(3)]
    conn = http.client.HTTPConnection(HOST, PORT, timeout=120)
    conn.request("POST", "/v1/chat/completions", body, {"Content-Type": "application/json"})
    resp = conn.getresponse()
    chunks = 0
    while chunks < 30:
        if resp.readline().startswith(b"data:"):
            chunks += 1
    busy = gpu_util()
    conn.sock.close()  # drop the client mid-generation
    conn.close()
    t_drop = time.perf_counter()
    after = []
    for _ in range(6):
        time.sleep(0.5)
        after.append(gpu_util())
    follow = ttft("Say OK.")
    return {
        "baseline_ttft_s": round(base, 3),
        "gpu_util_idle": idle,
        "gpu_util_while_generating": busy,
        "gpu_util_after_disconnect_0.5s_steps": after,
        "followup_ttft_s": round(follow, 3),
        "followup_waited_for_old_generation": follow > base + 2.0,
        "observed_s_since_drop": round(time.perf_counter() - t_drop, 2),
    }


def marker_hits(root: str, marker: str, since: float) -> list[dict]:
    hits = []
    needle = marker.encode()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            p = os.path.join(dirpath, name)
            try:
                if os.path.getmtime(p) < since or os.path.getsize(p) > 200_000_000:
                    continue
                with open(p, "rb") as f:
                    n = f.read().count(needle)
                if n:
                    hits.append({"file": os.path.relpath(p, root), "hits": n})
            except OSError:
                continue
    return hits


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lmstudio-dir", required=True)
    ap.add_argument("--appdata-dir", default=None, help="optional extra dir, e.g. AppData/Roaming/LM Studio")
    args = ap.parse_args()

    started = time.time() - 5
    marker = "WCMARK" + secrets.token_hex(6).upper()
    report: dict = {"marker_prefix": "WCMARK", "model": MODEL}

    m = get_json(f"/api/v0/models/{MODEL}")
    report["P-LMS-001_model"] = {k: m.get(k) for k in ("state", "quantization", "loaded_context_length")}

    system = ("You clean up dictated text. Remove filler words, fix punctuation. Keep every fact, "
              "number, name, negation and technical term exactly. Output only the cleaned text.")
    dictated = (f"um so [{marker}] do not delete the file config dot yaml uh and move the "
                "design review to Thursday at three PM and like send the notes to Priya")
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": dictated}]
    outs, lat = [], []
    for _ in range(3):
        text, dt = chat(msgs)
        outs.append(text)
        lat.append(round(dt, 3))
    report["P-LMS-002_temp0"] = {"identical_x3": len(set(outs)) == 1, "latency_s": lat,
                                 "output": outs[0].replace(marker, "<marker>")}

    report["P-LMS-003_disconnect"] = disconnect_test(marker)

    time.sleep(2)  # let log writers flush
    roots = [args.lmstudio_dir] + ([args.appdata_dir] if args.appdata_dir else [])
    report["log_check"] = {r: marker_hits(r, marker, started) for r in roots}
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
