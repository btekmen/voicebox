/** Exception hierarchy for the Voicebox client. */

export class VoiceboxError extends Error {
  constructor(message: string) {
    super(message);
    this.name = new.target.name;
  }
}

/**
 * Backend unreachable after all retries. Almost always means Voicebox isn't
 * running, or is bound to a different port than the client points at. The
 * desktop app uses 17493; `python -m backend.main` defaults to 8000 unless
 * started with `--port 17493`.
 */
export class VoiceboxConnectionError extends VoiceboxError {}

/** Backend returned a non-2xx response. `detail` is FastAPI's error body. */
export class VoiceboxAPIError extends VoiceboxError {
  constructor(
    readonly statusCode: number,
    readonly detail: unknown,
    readonly path = "",
  ) {
    super(`${statusCode} from ${path || "Voicebox"}: ${JSON.stringify(detail)}`);
  }
}

/** A requested voice profile couldn't be resolved (HTTP 404). */
export class ProfileNotFoundError extends VoiceboxAPIError {}

/**
 * The Whisper model is still downloading (HTTP 202). Wait and retry — the
 * model loads in the background.
 */
export class ModelDownloadingError extends VoiceboxAPIError {
  get modelName(): string | undefined {
    if (this.detail && typeof this.detail === "object") {
      return (this.detail as Record<string, unknown>).model_name as string | undefined;
    }
    return undefined;
  }
}

/** A generation finished with `status === "failed"`. */
export class GenerationFailedError extends VoiceboxError {
  constructor(readonly generationId: string, readonly error?: string) {
    super(`Generation ${generationId} failed: ${error ?? "unknown error"}`);
  }
}

/** A generation didn't reach a terminal state within the timeout. */
export class GenerationTimeoutError extends VoiceboxError {
  constructor(readonly generationId: string, readonly timeoutMs: number) {
    super(`Generation ${generationId} did not complete within ${timeoutMs}ms`);
  }
}
