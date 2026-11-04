import json, time, urllib.request, uuid
from pathlib import Path

BASE = "http://100.72.208.31:8791"
env = dict(l.split("=", 1) for l in Path("/Users/kan/transcribe-endpoint/.env").read_text().splitlines() if "=" in l)
TOKEN = env["TRANSCRIBE_TOKEN"].strip()

def post_file(file_path: Path, fields: dict):
    boundary = "----verify" + uuid.uuid4().hex
    body = b""
    for k, v in fields.items():
        body += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode()
    data = file_path.read_bytes()
    body += f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{file_path.name}\"\r\nContent-Type: application/octet-stream\r\n\r\n".encode()
    body += data + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(BASE + "/transcribe", data=body, method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    req.add_header("Authorization", f"Bearer {TOKEN}")
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=1800) as r:
        return json.loads(r.read().decode("utf-8")), time.time() - t0

sample = Path("/Users/kan/asr-bench/sample.wav")

# A) correct=false -> raw segments, ASR-only timing
raw, wall = post_file(sample, {"correct": "false"})
print("A correct=false: corrected:", raw["corrected"], "| elapsed_s:", raw["elapsed_s"], "| wall:", round(wall, 1))

# B) segment-level diff vs corrected run
corr = json.load(open("/Users/kan/transcribe-endpoint/logs/verify-sample.json"))
print("B diffs (raw -> corrected):")
for rs, cs in zip(raw["segments"], corr["segments"]):
    if rs["text"] != cs["text"]:
        print(f"  [{rs['start']:.0f}s] RAW : {rs['text']}")
        print(f"  [{rs['start']:.0f}s] FIX : {cs['text']}")

# C) m4a decode path (60s clip made beforehand) + extra terms/context params
clip = Path("/Users/kan/transcribe-endpoint/logs/clip60.m4a")
d2, wall2 = post_file(clip, {"terms": "追加テスト語", "context": "これは検証用の短いクリップです"})
print("C m4a: engine:", d2["engine"], "| duration:", d2["audio_duration_s"], "| elapsed_s:", d2["elapsed_s"], "| corrected:", d2["corrected"], "| text_head:", d2["text"][:60])
