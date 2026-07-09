"""Exception hierarchy for the Voicebox client."""

from __future__ import annotations

from typing import Any, Optional


class VoiceboxError(Exception):
    """Base class for every error raised by the client."""


class VoiceboxConnectionError(VoiceboxError):
    """Raised when the backend is unreachable after all retries.

    Almost always means Voicebox isn't running, or is bound to a different
    port than the client is pointed at. The desktop app launches its backend
    on 17493; ``python -m backend.main`` defaults to 8000 unless you pass
    ``--port 17493``.
    """


class VoiceboxAPIError(VoiceboxError):
    """Raised when the backend returns a non-2xx response.

    ``detail`` is FastAPI's error body (a string, or a dict for structured
    errors such as the 202 "model downloading" response).
    """

    def __init__(self, status_code: int, detail: Any, *, path: str = "") -> None:
        self.status_code = status_code
        self.detail = detail
        self.path = path
        super().__init__(f"{status_code} from {path or 'Voicebox'}: {detail}")


class ProfileNotFoundError(VoiceboxAPIError):
    """Raised when a requested voice profile can't be resolved (HTTP 404)."""


class ModelDownloadingError(VoiceboxAPIError):
    """Raised by transcribe when the Whisper model is still downloading (HTTP 202).

    Retry the call after a short wait — the model loads in the background.
    """

    @property
    def model_name(self) -> Optional[str]:
        if isinstance(self.detail, dict):
            return self.detail.get("model_name")
        return None


class GenerationFailedError(VoiceboxError):
    """Raised when a generation finishes with ``status == "failed"``."""

    def __init__(self, generation_id: str, error: Optional[str]) -> None:
        self.generation_id = generation_id
        self.error = error
        super().__init__(f"Generation {generation_id} failed: {error or 'unknown error'}")


class GenerationTimeoutError(VoiceboxError):
    """Raised when a generation doesn't reach a terminal state in time."""

    def __init__(self, generation_id: str, timeout: float) -> None:
        self.generation_id = generation_id
        self.timeout = timeout
        super().__init__(
            f"Generation {generation_id} did not complete within {timeout:g}s"
        )
