# Live demo — run the clients without the full TTS stack

This directory lets you see the Python and TypeScript clients work
**end-to-end right now**, without downloading models or a GPU.

`mock_voicebox.py` is a tiny, dependency-free stand-in for the Voicebox
backend. It implements just enough of the real API contract
(`backend/routes/*.py`) — profiles, `speak`/`generate`, the Server-Sent-Events
status stream, audio download, and transcribe — to exercise the clients over
real HTTP. Every generation returns a short beep WAV; it is **not** a real TTS
engine, only a demo harness.

## Run it

**1. Start the mock backend** (defaults to the app's port, 17493):

```bash
python integrations/demo/mock_voicebox.py --port 17493
```

**2. In another terminal, run a client against it:**

```bash
# Python
pip install httpx
PYTHONPATH=integrations/python python integrations/python/examples/quickstart.py "This is a live demo."

# TypeScript (Bun)
cd integrations/typescript && bun run examples/quickstart.ts "This is a live demo."
```

Expected output (either client):

```
2 voice profiles:
  - Morgan  (cloned, en)
  - Kokoro-Bella  (preset, en)

Generating with 'Morgan' ...
Done: quickstart.wav  (0.4s)
```

The mock server logs every request it receives, so you can watch the full
flow — `GET /profiles`, `POST /speak`, the SSE `GET /generate/{id}/status`
stream, and `GET /audio/{id}` — happen live.

## Going to the real thing

Point the exact same client code at a running Voicebox desktop app (or
`python -m backend.main --port 17493`) and it works unchanged — the mock and
the real backend speak the same contract. The only difference is you'll hear
an actual cloned voice instead of a beep.
