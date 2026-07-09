/**
 * Tests for the Voicebox TS client, driven by an injected fetch mock — no
 * running backend required.
 *
 *   bun test
 */

import { describe, expect, test } from "bun:test";
import {
  ModelDownloadingError,
  ProfileNotFoundError,
  VoiceboxClient,
  VoiceboxConnectionError,
} from "../src/index.js";

type Handler = (url: string, init: RequestInit) => Response | Promise<Response>;

function makeClient(handler: Handler, extra = {}) {
  const fetchMock = ((input: any, init: any = {}) =>
    Promise.resolve(handler(String(input), init))) as unknown as typeof fetch;
  return new VoiceboxClient({ clientId: "test", maxRetries: 2, fetch: fetchMock, ...extra });
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

describe("VoiceboxClient", () => {
  test("listProfiles + findProfile", async () => {
    const vb = makeClient((url) => {
      expect(url).toEndWith("/profiles");
      return json([
        { id: "a1", name: "Morgan", voice_type: "cloned", language: "en" },
        { id: "b2", name: "Kokoro-Bella", voice_type: "preset", language: "en" },
      ]);
    });
    const profiles = await vb.listProfiles();
    expect(profiles.map((p) => p.name)).toEqual(["Morgan", "Kokoro-Bella"]);
    expect((await vb.findProfile("morgan"))?.id).toBe("a1"); // case-insensitive
    expect((await vb.findProfile("b2"))?.name).toBe("Kokoro-Bella"); // by id
    expect(await vb.findProfile("nope")).toBeNull();
  });

  test("speak sends client id header and body", async () => {
    let seenHeader: string | null = null;
    let seenBody: any = null;
    const vb = makeClient((url, init) => {
      expect(url).toEndWith("/speak");
      seenHeader = (init.headers as Record<string, string>)["X-Voicebox-Client-Id"];
      seenBody = JSON.parse(init.body as string);
      return json({ id: "gen1", status: "generating", profile_id: "a1" });
    });
    const gen = await vb.speak("hi", { profile: "Morgan", personality: true });
    expect(gen.id).toBe("gen1");
    expect(gen.status).toBe("generating");
    expect(seenHeader).toBe("test");
    expect(seenBody).toEqual({ text: "hi", profile: "Morgan", personality: true });
  });

  test("404 maps to ProfileNotFoundError", async () => {
    const vb = makeClient(() => json({ detail: "Voice profile 'X' not found." }, 404));
    await expect(vb.speak("hi", { profile: "X" })).rejects.toBeInstanceOf(ProfileNotFoundError);
  });

  test("waitForGeneration consumes SSE stream", async () => {
    const sse =
      'data: {"id": "gen1", "status": "generating"}\n\n' +
      'data: {"id": "gen1", "status": "completed", "duration": 2.5}\n\n';
    const vb = makeClient((url) => {
      expect(url).toEndWith("/generate/gen1/status");
      return new Response(sse, { headers: { "content-type": "text/event-stream" } });
    });
    const gen = await vb.waitForGeneration("gen1", { timeoutMs: 5000 });
    expect(gen.status).toBe("completed");
    expect(gen.duration).toBe(2.5);
  });

  test("waitForGeneration falls back to polling when SSE unavailable", async () => {
    let historyCalls = 0;
    const vb = makeClient((url) => {
      if (url.endsWith("/status")) return new Response("boom", { status: 500 });
      if (url.includes("/history/")) {
        historyCalls += 1;
        return json({ id: "gen1", status: historyCalls >= 2 ? "completed" : "generating" });
      }
      return new Response("", { status: 404 });
    });
    const gen = await vb.waitForGeneration("gen1", { timeoutMs: 10_000 });
    expect(gen.status).toBe("completed");
    expect(historyCalls).toBeGreaterThanOrEqual(2);
  });

  test("transcribe uses the `file` multipart field", async () => {
    let hasFile = false;
    let hasModel = false;
    const vb = makeClient((url, init) => {
      expect(url).toEndWith("/transcribe");
      const form = init.body as FormData;
      hasFile = form.get("file") !== null;
      hasModel = form.get("model") === "turbo";
      return json({ text: "hello world", duration: 1.2 });
    });
    const result = await vb.transcribe(new Uint8Array([1, 2, 3]), { model: "turbo" });
    expect(result.text).toBe("hello world");
    expect(hasFile).toBe(true);
    expect(hasModel).toBe(true);
  });

  test("202 raises ModelDownloadingError with model name", async () => {
    const vb = makeClient(() =>
      json({ message: "downloading", model_name: "whisper-turbo", downloading: true }, 202),
    );
    try {
      await vb.transcribe(new Uint8Array([1]), { model: "turbo" });
      throw new Error("should have thrown");
    } catch (err) {
      expect(err).toBeInstanceOf(ModelDownloadingError);
      expect((err as ModelDownloadingError).modelName).toBe("whisper-turbo");
    }
  });

  test("retries on 503 then succeeds", async () => {
    let n = 0;
    const vb = makeClient(() => {
      n += 1;
      return n === 1 ? new Response("warming up", { status: 503 }) : json([]);
    });
    expect(await vb.listProfiles()).toEqual([]);
    expect(n).toBe(2);
  });

  test("connection error is wrapped", async () => {
    const vb = makeClient(() => {
      throw new TypeError("fetch failed");
    });
    await expect(vb.health()).rejects.toBeInstanceOf(VoiceboxConnectionError);
  });
});
