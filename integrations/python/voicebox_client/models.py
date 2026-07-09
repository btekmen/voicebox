"""Typed views over Voicebox API payloads.

These mirror the Pydantic response models in ``backend/models.py`` but only
carry the fields an integration typically cares about. Unknown fields are
ignored, so the client keeps working when the backend adds new ones.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

# Terminal generation states — see backend/routes/generations.py.
TERMINAL_STATES = frozenset({"completed", "failed", "not_found"})

# Valid values, pulled from the Field patterns in backend/models.py. Exposed
# so callers can validate before hitting the network.
ENGINES = (
    "qwen",
    "qwen_custom_voice",
    "luxtts",
    "chatterbox",
    "chatterbox_turbo",
    "tada",
    "kokoro",
)
GENERATE_LANGUAGES = (
    "zh", "en", "ja", "ko", "de", "fr", "ru", "pt", "es", "it", "he", "ar",
    "da", "el", "fi", "hi", "ms", "nl", "no", "pl", "sv", "sw", "tr",
)
WHISPER_MODELS = ("base", "small", "medium", "large", "turbo")


@dataclass(frozen=True)
class Profile:
    """A voice profile (cloned voice or preset)."""

    id: str
    name: str
    voice_type: Optional[str] = None
    language: Optional[str] = None
    raw: Dict[str, Any] = None  # type: ignore[assignment]

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Profile":
        return cls(
            id=d["id"],
            name=d["name"],
            voice_type=d.get("voice_type"),
            language=d.get("language"),
            raw=d,
        )


@dataclass(frozen=True)
class Generation:
    """A generation record returned by /generate, /speak, and /history/{id}."""

    id: str
    status: str
    profile_id: Optional[str] = None
    text: Optional[str] = None
    language: Optional[str] = None
    audio_path: Optional[str] = None
    duration: Optional[float] = None
    engine: Optional[str] = None
    error: Optional[str] = None
    source: Optional[str] = None
    raw: Dict[str, Any] = None  # type: ignore[assignment]

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATES

    @property
    def succeeded(self) -> bool:
        return self.status == "completed"

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Generation":
        return cls(
            id=d["id"],
            status=d.get("status", "completed"),
            profile_id=d.get("profile_id"),
            text=d.get("text"),
            language=d.get("language"),
            audio_path=d.get("audio_path"),
            duration=d.get("duration"),
            engine=d.get("engine"),
            error=d.get("error"),
            source=d.get("source"),
            raw=d,
        )


@dataclass(frozen=True)
class Transcription:
    """Result of POST /transcribe."""

    text: str
    duration: float

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Transcription":
        return cls(text=d["text"], duration=d.get("duration", 0.0))


def list_profiles_from(payload: List[Dict[str, Any]]) -> List[Profile]:
    return [Profile.from_dict(p) for p in payload]
