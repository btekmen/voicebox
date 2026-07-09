# Voicebox integrations

Client libraries for driving the local Voicebox API (`http://127.0.0.1:17493`)
from your own apps, scripts, and agents. Both wrap the same REST surface the
desktop app and MCP server use, and mirror the `voicebox.speak` MCP tool
(including per-client voice bindings via `X-Voicebox-Client-Id`).

| Directory | Language | Runtime dep | Tests |
| --- | --- | --- | --- |
| [`python/`](python) | Python 3.9+ | `httpx` | `pytest` (MockTransport) |
| [`typescript/`](typescript) | TS / JS | none (global `fetch`) | `bun test` |

Both cover: list/find profiles, `speak` / `generate` (+ `*_and_wait`),
SSE-aware wait-for-completion with a polling fallback, audio download, Whisper
transcription, a typed error hierarchy, and automatic retry/backoff.

They also paper over two spots where the main README diverges from the backend:
`/transcribe`'s multipart field is `file` (not `audio`), and
`/generate/{id}/status` is a Server-Sent Events stream (not a JSON poll).

See each directory's README for full usage.
