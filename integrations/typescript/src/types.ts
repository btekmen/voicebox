/** Typed views over Voicebox API payloads (see backend/models.py). */

/** Terminal generation states — see backend/routes/generations.py. */
export const TERMINAL_STATES = new Set(["completed", "failed", "not_found"]);

/** Valid TTS engines, from the Field pattern in backend/models.py. */
export const ENGINES = [
  "qwen",
  "qwen_custom_voice",
  "luxtts",
  "chatterbox",
  "chatterbox_turbo",
  "tada",
  "kokoro",
] as const;
export type Engine = (typeof ENGINES)[number];

/** Language codes accepted by /generate. */
export const GENERATE_LANGUAGES = [
  "zh", "en", "ja", "ko", "de", "fr", "ru", "pt", "es", "it", "he", "ar",
  "da", "el", "fi", "hi", "ms", "nl", "no", "pl", "sv", "sw", "tr",
] as const;
export type GenerateLanguage = (typeof GENERATE_LANGUAGES)[number];

/** Whisper model sizes accepted by /transcribe. */
export const WHISPER_MODELS = ["base", "small", "medium", "large", "turbo"] as const;
export type WhisperModel = (typeof WHISPER_MODELS)[number];

export interface Profile {
  id: string;
  name: string;
  voiceType?: string;
  language?: string;
  raw: Record<string, unknown>;
}

export interface Generation {
  id: string;
  status: string;
  profileId?: string;
  text?: string;
  language?: string;
  audioPath?: string;
  duration?: number;
  engine?: string;
  error?: string;
  source?: string;
  raw: Record<string, unknown>;
}

export interface Transcription {
  text: string;
  duration: number;
}

export function isTerminal(status: string): boolean {
  return TERMINAL_STATES.has(status);
}

export function profileFromDict(d: Record<string, any>): Profile {
  return {
    id: d.id,
    name: d.name,
    voiceType: d.voice_type ?? undefined,
    language: d.language ?? undefined,
    raw: d,
  };
}

export function generationFromDict(d: Record<string, any>): Generation {
  return {
    id: d.id,
    status: d.status ?? "completed",
    profileId: d.profile_id ?? undefined,
    text: d.text ?? undefined,
    language: d.language ?? undefined,
    audioPath: d.audio_path ?? undefined,
    duration: d.duration ?? undefined,
    engine: d.engine ?? undefined,
    error: d.error ?? undefined,
    source: d.source ?? undefined,
    raw: d,
  };
}

export function transcriptionFromDict(d: Record<string, any>): Transcription {
  return { text: d.text, duration: d.duration ?? 0 };
}
