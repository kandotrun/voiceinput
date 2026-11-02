#!/usr/bin/env python3
"""Standalone deterministic tests; never read real credentials or contact the ASR server."""
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import subprocess
import tempfile
import threading

root = Path(__file__).resolve().parents[1]
requests = []
errors = []

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers['Content-Length']))
        requests.append(self.path)
        try:
            assert self.headers['Authorization'] == 'Bearer test-only-token'
            boundary = self.headers['Content-Type'].split('boundary=')[1].encode()
            assert body.startswith(b'--' + boundary + b'\r\n')
            assert body.endswith(b'--' + boundary + b'--\r\n')
            assert b'name="file"; filename="audio.wav"' in body
            assert b'Content-Type: audio/wav\r\n\r\nfixture-audio' in body
            assert b'name="language"\r\n\r\nja\r\n' in body
            correct = b'true' if self.path.startswith('/correct/') else b'false'
            assert b'name="correct"\r\n\r\n' + correct + b'\r\n' in body
        except Exception as exc:
            errors.append(str(exc) or 'multipart assertion failed')
        if self.path.startswith('/redirect/'):
            self.send_response(307)
            self.send_header('Location', '/unexpected-token-leak')
            self.end_headers()
            return
        self.send_response(401 if self.path.startswith('/unauthorized/') else 200)
        self.end_headers()
        if self.path.startswith('/malformed/'):
            self.wfile.write(b'not json')
        elif self.path.startswith('/empty/'):
            self.wfile.write(b'{"text":" "}')
        else:
            self.wfile.write('{"text":"テストの音声です"}'.encode())

with tempfile.TemporaryDirectory(prefix='voiceinput-tests-') as tmp:
    state = str(Path(tmp) / 'state')
    network = str(Path(tmp) / 'network')
    subprocess.run(['swiftc', 'VoiceInput/KeyState.swift', 'Tests/main.swift', '-o', state], cwd=root, check=True)
    subprocess.run([state], check=True)
    subprocess.run(['swiftc', '-parse-as-library', 'VoiceInput/Services.swift', 'Tests/NetworkTests.swift', '-o', network], cwd=root, check=True)
    server = HTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        subprocess.run([network, f'http://127.0.0.1:{server.server_port}'], check=True)
        assert len(requests) == 6, requests
        assert not errors, errors
    finally:
        server.shutdown()
        server.server_close()
print('PASS: all tests (no real credentials used)')
