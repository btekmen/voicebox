# voicebox-client — Python client for the Voicebox API

A small, typed, dependency-light Python client for the local
[Voicebox](https://github.com/jamiepine/voicebox) REST API. Generate speech,
play text through a cloned voice, transcribe audio, and manage voice profiles
from any Python app, script, or agent — without hand-rolling HTTP.

It wraps the same endpoints the desktop app and MCP server use, and mirrors the
`voicebox.speak` MCP tool's behavior (including per-client voice bindings).

## Install

```bash
pip install httpx          # the only runtime dependency
# then add integrations/python to your PYTHONPATH, or:
pip install -e integrations/python
```

Requires a running Voicebox backend. The desktop app serves it on
`http://127.0.0.1:17493`. To run it standalone:

```bash
python -m backend.main --port 17493   # NB: the backend defaults to 8000
```

## Quickstart

```python
from voicebox_client import VoiceboxClient

with VoiceboxClient(client_id="my-script") as vb:
    # 1. List voices
    for p in vb.list_profiles():
        print(p.name, p.voice_type, p.language)

    # 2. Speak out loud on the user's machine, wait for it to finish
    gen = vb.speak_and_wait("Deploy complete.", profile="Morgan")

    # 3. Save the audio
    vb.download_audio(gen.id, "deploy.wav")

    # 4. Transcribe a file
    result = vb.transcribe("recording.wav", model="turbo")
    print(result.text)
```

## Why a `client_id`?

The `client_id` is sent as the `X-Voicebox-Client-Id` header on every request.
Voicebox uses it to look up per-client **bindings** (Settings → MCP): a default
voice, engine, and personality flag for that client. With a binding configured
you can call `vb.speak("...")` with **no `profile`** and still get the right
voice — resolution follows `explicit arg → per-client binding → global default`,
exactly like the MCP tool.

## API

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `list_profiles()` / `find_profile(name_or_id)` | `GET /profiles` | Enumerate / resolve voices |
| `speak(text, profile=…)` | `POST /speak` | Play text aloud in a voice (async) |
| `generate(text, profile_id=…)` | `POST /generate` | Full generation with all knobs (async) |
| `wait_for_generation(id)` | `GET /generate/{id}/status` (SSE) | Block until terminal |
| `speak_and_wait(...)` / `generate_and_wait(...)` | — | Start + wait, one call |
| `get_generation(id)` | `GET /history/{id}` | Current state of a generation |
| `download_audio(id, dest)` / `audio_bytes(id)` | `GET /audio/{id}` | Fetch the WAV |
| `transcribe(audio, model=…)` | `POST /transcribe` | Whisper STT |
| `health()` / `is_up()` | `GET /health` | Liveness |

`speak`/`generate` return immediately with `status="generating"`. Use the
`*_and_wait` helpers (or `wait_for_generation`) when you need the finished audio.

### Valid values

- **Engines:** `qwen`, `qwen_custom_voice`, `luxtts`, `chatterbox`,
  `chatterbox_turbo`, `tada`, `kokoro` (exposed as `voicebox_client.ENGINES`)
- **Whisper models:** `base`, `small`, `medium`, `large`, `turbo`
- **Languages:** 23 codes for generation (`voicebox_client.GENERATE_LANGUAGES`)

## Errors

All errors derive from `VoiceboxError`:

- `VoiceboxConnectionError` — backend unreachable after retries (usually not
  running, or on the wrong port)
- `ProfileNotFoundError` — the named profile couldn't be resolved (HTTP 404)
- `ModelDownloadingError` — a Whisper model is still downloading (HTTP 202);
  wait and retry (see `examples/transcribe.py`)
- `GenerationFailedError` — generation reached `status="failed"`
- `GenerationTimeoutError` — didn't finish within the timeout
- `VoiceboxAPIError` — any other non-2xx (carries `.status_code`, `.detail`)

Connection errors and `502/503/504` are retried automatically with exponential
backoff (configurable via `max_retries`).

## Notes / gotchas this client handles for you

- **`/generate/{id}/status` is Server-Sent Events**, not a JSON poll. The client
  consumes the stream and falls back to polling `/history/{id}` if it drops.
- **`/transcribe`'s file field is `file`**, not `audio` (the main README's curl
  example is wrong). The client sends the correct field.
- **Port mismatch:** the desktop app uses `17493`; the raw backend defaults to
  `8000`. `VoiceboxClient` defaults to `17493` — override `base_url` if needed.

## Tests

The suite runs against an `httpx.MockTransport` — no live backend needed:

```bash
pip install httpx pytest
pytest integrations/python/tests
```
