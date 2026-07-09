/**
 * A small, typed client for the Voicebox local API.
 *
 * Voicebox exposes a REST API (and an MCP server) on `127.0.0.1:17493` when
 * the desktop app is running. This client wraps the REST surface so any
 * Node/Bun app or agent can generate speech, play text through a cloned
 * voice, transcribe audio, and manage voice profiles — with no dependencies
 * beyond the runtime's built-in `fetch` (Node 18+, Bun, Deno).
 *
 * @example
 * const vb = new VoiceboxClient({ clientId: "my-script" });
 * const gen = await vb.speakAndWait("Deploy complete.", { profile: "Morgan" });
 * await vb.downloadAudio(gen.id, "deploy.wav");
 *
 * Notes:
 * - `/generate/{id}/status` is a Server-Sent Events stream, not a JSON poll —
 *   `waitForGeneration` consumes it and falls back to polling `/history/{id}`.
 * - `/transcribe` takes a multipart field named `file` (the README's `audio`
 *   is wrong) and a Whisper `model` of base/small/medium/large/turbo.
 */

import { writeFile } from "node:fs/promises";
import {
  GenerationFailedError,
  GenerationTimeoutError,
  ModelDownloadingError,
  ProfileNotFoundError,
  VoiceboxAPIError,
  VoiceboxConnectionError,
} from "./errors.js";
import {
  type Engine,
  type GenerateLanguage,
  type Generation,
  type Profile,
  type Transcription,
  type WhisperModel,
  generationFromDict,
  isTerminal,
  profileFromDict,
  transcriptionFromDict,
} from "./types.js";

export const DEFAULT_BASE_URL = "http://127.0.0.1:17493";

// Retry network errors and transient upstream failures; never retry a 4xx.
const RETRY_STATUS = new Set([502, 503, 504]);

export interface VoiceboxClientOptions {
  /** Where the backend listens. Defaults to the desktop app's port (17493). */
  baseUrl?: string;
  /**
   * Sent as `X-Voicebox-Client-Id` on every request. Voicebox uses it to
   * resolve per-client voice/personality bindings (Settings → MCP), so
   * `speak` can omit `profile` and still pick the right voice.
   */
  clientId?: string;
  /** Per-request timeout (ms) for ordinary calls. Default 30000. */
  timeoutMs?: number;
  /** Retries on connection error / 502-504, with exponential backoff. Default 3. */
  maxRetries?: number;
  /** Override the global fetch (used by tests). */
  fetch?: typeof fetch;
}

export interface SpeakOptions {
  profile?: string;
  engine?: Engine;
  personality?: boolean;
  language?: GenerateLanguage;
}

export interface GenerateOptions {
  language?: GenerateLanguage;
  engine?: Engine;
  personality?: boolean;
  seed?: number;
  instruct?: string;
  [key: string]: unknown;
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

async function extractDetail(resp: Response): Promise<unknown> {
  const body = await resp.text();
  try {
    const parsed = JSON.parse(body);
    if (parsed && typeof parsed === "object" && "detail" in parsed) {
      return (parsed as Record<string, unknown>).detail;
    }
    return parsed;
  } catch {
    return body;
  }
}

export class VoiceboxClient {
  readonly baseUrl: string;
  readonly clientId?: string;
  private readonly timeoutMs: number;
  private readonly maxRetries: number;
  private readonly fetchImpl: typeof fetch;

  constructor(opts: VoiceboxClientOptions = {}) {
    this.baseUrl = (opts.baseUrl ?? DEFAULT_BASE_URL).replace(/\/+$/, "");
    this.clientId = opts.clientId;
    this.timeoutMs = opts.timeoutMs ?? 30_000;
    this.maxRetries = opts.maxRetries ?? 3;
    this.fetchImpl = opts.fetch ?? fetch;
  }

  private headers(extra?: Record<string, string>): Record<string, string> {
    const h: Record<string, string> = { ...extra };
    if (this.clientId) h["X-Voicebox-Client-Id"] = this.clientId;
    return h;
  }

  /** Low-level request with retry/backoff. Returns the raw Response on 2xx. */
  private async request(method: string, path: string, init: RequestInit = {}): Promise<Response> {
    let lastErr: unknown;
    for (let attempt = 0; attempt <= this.maxRetries; attempt++) {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), this.timeoutMs);
      try {
        const resp = await this.fetchImpl(this.baseUrl + path, {
          method,
          ...init,
          headers: this.headers(init.headers as Record<string, string>),
          signal: controller.signal,
        });
        clearTimeout(timer);
        if (RETRY_STATUS.has(resp.status) && attempt < this.maxRetries) {
          lastErr = new VoiceboxAPIError(resp.status, await extractDetail(resp), path);
        } else {
          return await this.raiseForStatus(resp, path);
        }
      } catch (err) {
        clearTimeout(timer);
        if (err instanceof VoiceboxAPIError) throw err;
        lastErr = err;
      }
      if (attempt < this.maxRetries) await sleep(500 * 2 ** attempt);
    }
    throw new VoiceboxConnectionError(
      `Could not reach Voicebox at ${this.baseUrl} after ${this.maxRetries + 1} ` +
        `attempts. Is the app running and bound to this port? (${lastErr})`,
    );
  }

  private async raiseForStatus(resp: Response, path: string): Promise<Response> {
    // 202 is technically 2xx, but Voicebox uses it for "Whisper model still
    // downloading" — surface it as a typed error, not success.
    if (resp.status === 202) {
      throw new ModelDownloadingError(202, await extractDetail(resp), path);
    }
    if (resp.ok) return resp;
    const detail = await extractDetail(resp);
    if (resp.status === 404) throw new ProfileNotFoundError(404, detail, path);
    throw new VoiceboxAPIError(resp.status, detail, path);
  }

  private jsonHeaders(): Record<string, string> {
    return { "Content-Type": "application/json" };
  }

  // -- health ----------------------------------------------------------
  async health(): Promise<Record<string, unknown>> {
    return (await this.request("GET", "/health")).json();
  }

  async isUp(): Promise<boolean> {
    try {
      await this.health();
      return true;
    } catch {
      return false;
    }
  }

  // -- profiles --------------------------------------------------------
  async listProfiles(): Promise<Profile[]> {
    const data = (await (await this.request("GET", "/profiles")).json()) as Record<string, any>[];
    return data.map(profileFromDict);
  }

  /** Resolve a profile by exact id or case-insensitive name, else null. */
  async findProfile(nameOrId: string): Promise<Profile | null> {
    const wanted = nameOrId.toLowerCase();
    for (const p of await this.listProfiles()) {
      if (p.id === nameOrId || p.name.toLowerCase() === wanted) return p;
    }
    return null;
  }

  // -- generation ------------------------------------------------------
  /**
   * Start a generation on `/generate`. Resolves immediately with a
   * Generation whose `status` is "generating"; use `waitForGeneration`.
   */
  async generate(text: string, profileId: string, opts: GenerateOptions = {}): Promise<Generation> {
    const { language = "en", engine, personality = false, seed, instruct, ...extra } = opts;
    const body: Record<string, unknown> = { text, profile_id: profileId, language, personality };
    if (engine !== undefined) body.engine = engine;
    if (seed !== undefined) body.seed = seed;
    if (instruct !== undefined) body.instruct = instruct;
    Object.assign(body, extra);
    const resp = await this.request("POST", "/generate", {
      headers: this.jsonHeaders(),
      body: JSON.stringify(body),
    });
    return generationFromDict(await resp.json());
  }

  /**
   * Play `text` through a voice on the user's speakers (`/speak`). `profile`
   * accepts a name or id; when omitted, Voicebox resolves the per-client
   * binding, then the global default. Mirrors the `voicebox.speak` MCP tool.
   */
  async speak(text: string, opts: SpeakOptions = {}): Promise<Generation> {
    const body: Record<string, unknown> = { text };
    if (opts.profile !== undefined) body.profile = opts.profile;
    if (opts.engine !== undefined) body.engine = opts.engine;
    if (opts.personality !== undefined) body.personality = opts.personality;
    if (opts.language !== undefined) body.language = opts.language;
    const resp = await this.request("POST", "/speak", {
      headers: this.jsonHeaders(),
      body: JSON.stringify(body),
    });
    return generationFromDict(await resp.json());
  }

  /** Fetch the current state of a generation via `/history/{id}`. */
  async getGeneration(generationId: string): Promise<Generation> {
    return generationFromDict(await (await this.request("GET", `/history/${generationId}`)).json());
  }

  /**
   * Block until a generation reaches a terminal state. Consumes the
   * `/generate/{id}/status` SSE stream, falling back to polling `/history/{id}`
   * if the stream ends or errors early.
   */
  async waitForGeneration(
    generationId: string,
    opts: { timeoutMs?: number; raiseOnFailure?: boolean } = {},
  ): Promise<Generation> {
    const timeoutMs = opts.timeoutMs ?? 300_000;
    const raiseOnFailure = opts.raiseOnFailure ?? true;
    const deadline = Date.now() + timeoutMs;

    let last = await this.awaitViaSse(generationId, deadline);
    if (!last || !isTerminal(last.status)) {
      last = await this.awaitViaPolling(generationId, deadline);
    }
    if (!last) throw new GenerationTimeoutError(generationId, timeoutMs);
    if (last.status === "failed" && raiseOnFailure) {
      throw new GenerationFailedError(generationId, last.error);
    }
    return last;
  }

  private async awaitViaSse(generationId: string, deadline: number): Promise<Generation | null> {
    const remaining = deadline - Date.now();
    if (remaining <= 0) return null;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), remaining);
    try {
      const resp = await this.fetchImpl(`${this.baseUrl}/generate/${generationId}/status`, {
        headers: this.headers(),
        signal: controller.signal,
      });
      if (!resp.ok || !resp.body) return null;
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      let last: Generation | null = null;
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        let nl: number;
        while ((nl = buf.indexOf("\n")) >= 0) {
          const line = buf.slice(0, nl).trim();
          buf = buf.slice(nl + 1);
          if (!line.startsWith("data:")) continue;
          try {
            last = generationFromDict(JSON.parse(line.slice(5).trim()));
          } catch {
            continue;
          }
          if (isTerminal(last.status)) {
            controller.abort();
            return last;
          }
        }
        if (Date.now() >= deadline) return last;
      }
      return last;
    } catch {
      return null;
    } finally {
      clearTimeout(timer);
    }
  }

  private async awaitViaPolling(generationId: string, deadline: number): Promise<Generation | null> {
    let last: Generation | null = null;
    while (Date.now() < deadline) {
      last = await this.getGeneration(generationId);
      if (isTerminal(last.status)) return last;
      await sleep(1000);
    }
    return last;
  }

  /** `speak` then `waitForGeneration` in one call. */
  async speakAndWait(text: string, opts: SpeakOptions & { timeoutMs?: number } = {}): Promise<Generation> {
    const { timeoutMs, ...speakOpts } = opts;
    const gen = await this.speak(text, speakOpts);
    return this.waitForGeneration(gen.id, { timeoutMs });
  }

  /** `generate` then `waitForGeneration` in one call. */
  async generateAndWait(
    text: string,
    profileId: string,
    opts: GenerateOptions & { timeoutMs?: number } = {},
  ): Promise<Generation> {
    const { timeoutMs, ...genOpts } = opts;
    const gen = await this.generate(text, profileId, genOpts);
    return this.waitForGeneration(gen.id, { timeoutMs });
  }

  // -- audio -----------------------------------------------------------
  /** Return a completed generation's audio as bytes. */
  async audioBytes(generationId: string): Promise<Uint8Array> {
    const resp = await this.request("GET", `/audio/${generationId}`);
    return new Uint8Array(await resp.arrayBuffer());
  }

  /** Download a completed generation's audio to `dest`. Returns `dest`. */
  async downloadAudio(generationId: string, dest: string): Promise<string> {
    await writeFile(dest, await this.audioBytes(generationId));
    return dest;
  }

  // -- transcription ---------------------------------------------------
  /**
   * Transcribe audio via `/transcribe` (Whisper). `model` is one of
   * base/small/medium/large/turbo. If the model isn't cached, Voicebox starts
   * downloading it and returns HTTP 202 — this throws ModelDownloadingError.
   */
  async transcribe(
    audio: Blob | Uint8Array | ArrayBuffer,
    opts: { filename?: string; language?: string; model?: WhisperModel } = {},
  ): Promise<Transcription> {
    const blob =
      audio instanceof Blob
        ? audio
        : new Blob([audio instanceof Uint8Array ? audio : new Uint8Array(audio)]);
    const form = new FormData();
    form.append("file", blob, opts.filename ?? "audio.wav");
    if (opts.language) form.append("language", opts.language);
    if (opts.model) form.append("model", opts.model);
    const resp = await this.request("POST", "/transcribe", { body: form });
    return transcriptionFromDict(await resp.json());
  }
}
