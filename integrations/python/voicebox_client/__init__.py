"""voicebox_client — a typed Python client for the local Voicebox API.

    from voicebox_client import VoiceboxClient

    with VoiceboxClient(client_id="my-script") as vb:
        for p in vb.list_profiles():
            print(p.name)
        vb.speak_and_wait("Build finished.", profile="Morgan")
"""

from .client import DEFAULT_BASE_URL, VoiceboxClient
from .errors import (
    GenerationFailedError,
    GenerationTimeoutError,
    ModelDownloadingError,
    ProfileNotFoundError,
    VoiceboxAPIError,
    VoiceboxConnectionError,
    VoiceboxError,
)
from .models import (
    ENGINES,
    GENERATE_LANGUAGES,
    WHISPER_MODELS,
    Generation,
    Profile,
    Transcription,
)

__version__ = "0.1.0"

__all__ = [
    "VoiceboxClient",
    "DEFAULT_BASE_URL",
    "Generation",
    "Profile",
    "Transcription",
    "ENGINES",
    "GENERATE_LANGUAGES",
    "WHISPER_MODELS",
    "VoiceboxError",
    "VoiceboxConnectionError",
    "VoiceboxAPIError",
    "ProfileNotFoundError",
    "ModelDownloadingError",
    "GenerationFailedError",
    "GenerationTimeoutError",
    "__version__",
]
