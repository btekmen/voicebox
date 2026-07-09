# @voicebox/client — TypeScript client for the Voicebox API

A small, typed, **zero-dependency** TypeScript/JavaScript client for the local
[Voicebox](https://github.com/jamiepine/voicebox) REST API. Generate speech,
play text through a cloned voice, transcribe audio, and manage voice profiles
from any Node (18+), Bun, or Deno app or agent — built entirely on the
runtime's global `fetch`.

It's the TypeScript twin of `integrations/python` and wraps the same endpoints
the desktop app and MCP server use, mirroring the `voicebox.speak` MCP tool
(including per-client voice bindings).

## Install

No published package yet — vendor the `src/` directory, or point at it locally:

```jsonc
// package.json
"dependencies": { "@voicebox/client": "file:../voicebox/integrations/typescript" }
```

Requires a running Voicebox backend on `http://127.0.0.1:17493` (the desktop
app's port). To run it standalone: `python -m backend.main --port 17493` —
note the backend defaults to `8000`.

## Quickstart

```ts
import { VoiceboxClient } from "@voicebox/client";

const vb = new VoiceboxClient({ clientId: "my-script" });

// List voices
for (const p of await vb.listProfiles()) {
  console.log(p.name, p.voiceType, p.language);
}

// Speak out loud on the user's machine, wait for completion
const gen = await vb.speakAndWait("Deploy complete.", { profile: "Morgan" });

// Save the audio
await vb.downloadAudio(gen.id, "deploy.wav");

// Transcribe a file (Bun/Node)
import { readFile } from "node:fs/promises";
const result = await vb.transcribe(await readFile("recording.wav"), { model: "turbo" });
console.log(result.text);
```

## Why a `clientId`?

It's sent as `X-Voicebox-Client-Id` on every request. Voicebox uses it to look
up per-client **bindings** (Settings → MCP): a default voice, engine, and
personality flag. With a binding set you can call `vb.speak("...")` with **no
`profile`** and still get the right voice — resolution is
`explicit arg → per-client binding → global default`, exactly like the MCP tool.

## API

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `listProfiles()` / `findProfile(nameOrId)` | `GET /profiles` | Enumerate / resolve voices |
| `speak(text, opts)` | `POST /speak` | Play text aloud in a voice (async) |
| `generate(text, profileId, opts)` | `POST /generate` | Full generation with all knobs (async) |
| `waitForGeneration(id, opts)` | `GET /generate/{id}/status` (SSE) | Block until terminal |
| `speakAndWait(...)` / `generateAndWait(...)` | — | Start + wait, one call |
| `getGeneration(id)` | `GET /history/{id}` | Current state of a generation |
| `downloadAudio(id, dest)` / `audioBytes(id)` | `GET /audio/{id}` | Fetch the WAV |
| `transcribe(audio, opts)` | `POST /transcribe` | Whisper STT |
| `health()` / `isUp()` | `GET /health` | Liveness |

`speak`/`generate` resolve immediately with `status: "generating"`. Use the
`*AndWait` helpers (or `waitForGeneration`) when you need the finished audio.

Valid values are exported as `ENGINES`, `GENERATE_LANGUAGES`, and
`WHISPER_MODELS`, with matching `Engine` / `GenerateLanguage` / `WhisperModel`
string-literal types.

## Errors

All errors extend `VoiceboxError`:

- `VoiceboxConnectionError` — backend unreachable after retries
- `ProfileNotFoundError` — profile couldn't be resolved (HTTP 404)
- `ModelDownloadingError` — Whisper model still downloading (HTTP 202); wait and
  retry (`.modelName` tells you which)
- `GenerationFailedError` — generation reached `status: "failed"`
- `GenerationTimeoutError` — didn't finish within the timeout
- `VoiceboxAPIError` — any other non-2xx (`.statusCode`, `.detail`)

Connection errors and `502/503/504` are retried automatically with exponential
backoff (configurable via `maxRetries`).

## Gotchas this client handles for you

- **`/generate/{id}/status` is Server-Sent Events**, not a JSON poll. The client
  streams it and falls back to polling `/history/{id}` if it drops.
- **`/transcribe`'s multipart field is `file`**, not `audio` (the main README's
  curl example is wrong). The client sends the correct field.
- **Port mismatch:** desktop app `17493` vs. raw backend `8000`. The client
  defaults to `17493` — override with `{ baseUrl }`.

## Tests

Run against an injected `fetch` mock — no live backend needed:

```bash
bun test          # 9 tests
bun run typecheck # tsc --noEmit (needs @types/node)
```
