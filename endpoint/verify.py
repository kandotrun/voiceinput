import json, time, urllib.request, urllib.error, uuid, mimetypes
from pathlib import Path

BASE = "http://100.72.208.31:8791"
env = dict(l.split("=", 1) for l in Path("/Users/kan/transcribe-endpoint/.env").read_text().splitlines() if "=" in l)
TOKEN = env["TRANSCRIBE_TOKEN"].strip()

def post(path, data: bytes, ctype: str, token=None):
    req = urllib.request.Request(BASE + path, data=data, method="POST")
    req.add_header("Content-Type", ctype)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=1800) as r:
            return r.status, r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")

def multipart(file_path: Path, fields: dict):
    boundary = "----verify" + uuid.uuid4().hex
    body = b""
    for k, v in fields.items():
        body += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode()
    data = file_path.read_bytes()
    body += f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{file_path.name}\"\r\nContent-Type: audio/wav\r\n\r\n".encode()
    body += data + f"\r\n--{boundary}--\r\n".encode()
    return body, f"multipart/form-data; boundary={boundary}"

sample = Path("/Users/kan/asr-bench/sample.wav")

# 1) no-token -> expect 401
body, ctype = multipart(sample, {})
st, _ = post("/transcribe", body, ctype)
print("no_token_status_is_401:", st == 401, "(raw:", st, ")")

# 2) full run with token
t0 = time.time()
body, ctype = multipart(sample, {})
st, payload = post("/transcribe", body, ctype, token=TOKEN)
wall = time.time() - t0
print("auth_status_ok:", st == 200, "(raw:", st, ")")
d = json.loads(payload)
Path("/Users/kan/transcribe-endpoint/logs/verify-sample.json").write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
print("engine:", d["engine"], "| corrected:", d["corrected"], "| corrections:", d["corrections"])
print("audio_duration_s:", d["audio_duration_s"], "| server_elapsed_s:", d["elapsed_s"], "| wall_s:", round(wall, 1))
print("segments:", len(d["segments"]), "| text_chars:", len(d["text"]), "| raw_chars:", len(d["raw_text"]))
print("raw_has_FB16:", "FB16" in d["raw_text"], "| text_has_FP16:", "FP16" in d["text"], "| text_has_FB16:", "FB16" in d["text"])
print("correction_error:", d.get("correction_error"))

# 3) compare raw vs bench qwen3-asr.txt
import re, unicodedata
from difflib import SequenceMatcher
bench_lines = []
for line in Path("/Users/kan/asr-bench/qwen3-asr.txt").read_text(encoding="utf-8").splitlines():
    m = re.match(r"^\[\s*[\d.]+-\s*[\d.]+\]\s*(.*)$", line)
    if m:
        bench_lines.append(m.group(1))
def norm(s):
    s = unicodedata.normalize("NFKC", s)
    return re.sub(r"[\s。、・「」『』!?！？,.]", "", s)
bench_text = "".join(bench_lines)
ratio = SequenceMatcher(None, norm(bench_text), norm(d["raw_text"])).ratio()
print("bench_vs_endpoint_raw_similarity:", round(ratio, 3), "| bench_chars_norm:", len(norm(bench_text)), "| endpoint_chars_norm:", len(norm(d["raw_text"])))
# segments offset check: endpoint segments are 0-based, bench are +300s
first = d["segments"][0]; last = d["segments"][-1]
print("first_segment:", first["start"], "-", first["end"], "| last_segment_end:", last["end"])
