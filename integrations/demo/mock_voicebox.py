#!/usr/bin/env python3
"""A tiny, dependency-free stand-in for the Voicebox backend.

It implements just enough of the real API contract
(``backend/routes/*.py``) to exercise the client libraries end-to-end
without the full TTS/Whisper stack: profiles, speak/generate, the
Server-Sent-Events status stream, audio download, and transcribe.

    python integrations/demo/mock_voicebox.py --port 17493

This is for demos and local testing only — it returns a short beep for
every generation and echoes a canned transcript. Not a real TTS engine.
"""

from __future__ import annotations

import argparse
import json
import math
import struct
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

# In-memory generation store: id -> {status, created, profile_id, text}
_GENERATIONS: dict[str, dict] = {}
_LOCK = threading.Lock()
_SEQ = 0

PROFILES = [
    {"id": "p_morgan", "name": "Morgan", "voice_type": "cloned", "language": "en"},
    {"id": "p_bella", "name": "Kokoro-Bella", "voice_type": "preset", "language": "en"},
]

# How long a generation stays "generating" before flipping to "completed".
GEN_SECONDS = 1.5


def _beep_wav(seconds: float = 0.4, freq: int = 440, rate: int = 16000) -> bytes:
    """Build a minimal valid mono 16-bit PCM WAV of a sine beep."""
    n = int(seconds * rate)
    frames = b"".join(
        struct.pack("<h", int(12000 * math.sin(2 * math.pi * freq * i / rate)))
        for i in range(n)
    )
    data_len = len(frames)
    header = b"RIFF" + struct.pack("<I", 36 + data_len) + b"WAVE"
    header += b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16)
    header += b"data" + struct.pack("<I", data_len)
    return header + frames


_AUDIO = _beep_wav()


def _new_generation(profile_id: str, text: str) -> dict:
    global _SEQ
    with _LOCK:
        _SEQ += 1
        gen_id = f"gen_{_SEQ:04d}"
        rec = {
            "id": gen_id,
            "status": "generating",
            "profile_id": profile_id,
            "text": text,
            "language": "en",
            "engine": "qwen",
            "duration": None,
            "error": None,
            "source": "rest",
            "created": time.monotonic(),
        }
        _GENERATIONS[gen_id] = rec
        return rec


def _current_status(gen_id: str) -> dict | None:
    rec = _GENERATIONS.get(gen_id)
    if rec is None:
        return None
    if rec["status"] == "generating" and time.monotonic() - rec["created"] >= GEN_SECONDS:
        rec["status"] = "completed"
        rec["duration"] = 0.4
    return rec


def _resolve_profile(name_or_id: str | None) -> dict | None:
    if not name_or_id:
        return PROFILES[0]  # stand-in for "default voice" resolution
    wanted = name_or_id.lower()
    for p in PROFILES:
        if p["id"] == name_or_id or p["name"].lower() == wanted:
            return p
    return None


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # quieter logs
        print(f"  [mock] {self.command} {self.path} -> {args[1]}", flush=True)

    # -- helpers ---------------------------------------------------------
    def _json(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if not length:
            return {}
        return json.loads(self.rfile.read(length) or b"{}")

    # -- routes ----------------------------------------------------------
    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/health":
            return self._json({"status": "ok", "mock": True})
        if path == "/profiles":
            return self._json(PROFILES)
        if path.startswith("/generate/") and path.endswith("/status"):
            return self._sse_status(path.split("/")[2])
        if path.startswith("/history/"):
            rec = _current_status(path.split("/")[2])
            if rec is None:
                return self._json({"detail": "Generation not found"}, 404)
            return self._json(self._public(rec))
        if path.startswith("/audio/"):
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(_AUDIO)))
            self.end_headers()
            self.wfile.write(_AUDIO)
            return
        return self._json({"detail": f"Not found: {path}"}, 404)

    def do_POST(self):
        path = urlparse(self.path).path
        if path in ("/speak", "/generate"):
            data = self._read_json()
            key = "profile" if path == "/speak" else "profile_id"
            profile = _resolve_profile(data.get(key))
            if profile is None:
                return self._json(
                    {"detail": f"Voice profile '{data.get(key)}' not found."}, 404
                )
            rec = _new_generation(profile["id"], data.get("text", ""))
            client_id = self.headers.get("X-Voicebox-Client-Id", "-")
            print(f"  [mock] {path}: '{data.get('text','')[:40]}' as "
                  f"{profile['name']} (client={client_id}) -> {rec['id']}", flush=True)
            return self._json(self._public(rec))
        if path == "/transcribe":
            # We don't parse multipart here; just confirm we got a body and echo.
            length = int(self.headers.get("Content-Length", 0))
            self.rfile.read(length)
            return self._json(
                {"text": "This is a mock transcription of your audio.", "duration": 2.0}
            )
        return self._json({"detail": f"Not found: {path}"}, 404)

    # -- SSE -------------------------------------------------------------
    def _sse_status(self, gen_id: str):
        rec = _GENERATIONS.get(gen_id)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        if rec is None:
            self._sse_send({"id": gen_id, "status": "not_found"})
            return
        # Emit until terminal, then close (mirrors the real endpoint).
        while True:
            cur = _current_status(gen_id)
            self._sse_send(self._public(cur))
            if cur["status"] in ("completed", "failed"):
                return
            time.sleep(0.4)

    def _sse_send(self, payload: dict):
        try:
            self.wfile.write(f"data: {json.dumps(payload)}\n\n".encode())
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass

    @staticmethod
    def _public(rec: dict) -> dict:
        return {
            "id": rec["id"],
            "status": rec["status"],
            "profile_id": rec["profile_id"],
            "text": rec["text"],
            "language": rec["language"],
            "engine": rec["engine"],
            "duration": rec["duration"],
            "error": rec["error"],
            "source": rec["source"],
            "created_at": "2026-07-09T00:00:00Z",
        }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=17493)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Mock Voicebox listening on http://{args.host}:{args.port}  "
          f"(Ctrl-C to stop)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
