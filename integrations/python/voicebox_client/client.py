"""A small, typed Python client for the Voicebox local API.

Voicebox exposes a REST API (and an MCP server) on ``127.0.0.1:17493`` when
the desktop app is running. This client wraps the REST surface so any Python
app, script, or agent can generate speech, play text through a cloned voice,
transcribe audio, and manage voice profiles without hand-rolling HTTP.

Example
-------
    from voicebox_client import VoiceboxClient

    with VoiceboxClient(client_id="my-script") as vb:
        gen = vb.speak_and_wait("Deploy complete.", profile="Morgan")
        vb.download_audio(gen.id, "deploy.wav")

Notes
-----
* ``/generate/{id}/status`` is a Server-Sent Events stream, not a JSON poll —
  :meth:`wait_for_generation` consumes it and falls back to polling
  ``/history/{id}`` if the stream drops.
* ``/transcribe`` takes a multipart field named ``file`` (the README's
  ``audio=`` is wrong) and a Whisper ``model`` of base/small/medium/large/turbo.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import httpx

from .errors import (
    GenerationFailedError,
    GenerationTimeoutError,
    ModelDownloadingError,
    ProfileNotFoundError,
    VoiceboxAPIError,
    VoiceboxConnectionError,
    VoiceboxError,
)
from .models import Generation, Profile, Transcription, list_profiles_from

DEFAULT_BASE_URL = "http://127.0.0.1:17493"

# Retry network errors and transient upstream failures; never retry a 4xx —
# those are the caller's fault and won't fix themselves.
_RETRY_STATUS = frozenset({502, 503, 504})

PathLike = Union[str, Path]


def _detail(resp: httpx.Response) -> Any:
    """Best-effort extraction of FastAPI's error detail from a response."""
    try:
        body = resp.json()
    except (json.JSONDecodeError, ValueError):
        return resp.text
    if isinstance(body, dict) and "detail" in body:
        return body["detail"]
    return body


class VoiceboxClient:
    """Synchronous client for the Voicebox REST API.

    Parameters
    ----------
    base_url:
        Where the Voicebox backend is listening. Defaults to the desktop
        app's port (17493). If you run the backend standalone, remember it
        binds to 8000 unless started with ``--port 17493``.
    client_id:
        Sent as ``X-Voicebox-Client-Id`` on every request. Voicebox uses it
        to resolve per-client voice/personality bindings (Settings → MCP), so
        :meth:`speak` can omit ``profile`` and still pick the right voice.
    timeout:
        Per-request timeout in seconds for ordinary calls (not the long-lived
        status stream, which is governed by the ``timeout`` arg on
        :meth:`wait_for_generation`).
    max_retries:
        How many times to retry a request on a connection error or a
        502/503/504, with exponential backoff (0.5s, 1s, 2s, ...).
    """

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        *,
        client_id: Optional[str] = None,
        timeout: float = 30.0,
        max_retries: int = 3,
        transport: Optional[httpx.BaseTransport] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.client_id = client_id
        self.max_retries = max_retries
        headers = {"X-Voicebox-Client-Id": client_id} if client_id else {}
        self._http = httpx.Client(
            base_url=self.base_url,
            headers=headers,
            timeout=timeout,
            transport=transport,
        )

    # -- context manager -------------------------------------------------
    def __enter__(self) -> "VoiceboxClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    # -- low-level request with retry/backoff ----------------------------
    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        last_exc: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            try:
                resp = self._http.request(method, path, **kwargs)
            except (httpx.ConnectError, httpx.ReadError, httpx.WriteError,
                    httpx.PoolTimeout, httpx.ConnectTimeout) as exc:
                last_exc = exc
            else:
                if resp.status_code in _RETRY_STATUS and attempt < self.max_retries:
                    last_exc = VoiceboxAPIError(
                        resp.status_code, _detail(resp), path=path
                    )
                else:
                    return self._raise_for_status(resp, path)
            if attempt < self.max_retries:
                time.sleep(0.5 * (2 ** attempt))
        raise VoiceboxConnectionError(
            f"Could not reach Voicebox at {self.base_url} after "
            f"{self.max_retries + 1} attempts. Is the app running and bound "
            f"to this port? ({last_exc})"
        ) from last_exc

    @staticmethod
    def _raise_for_status(resp: httpx.Response, path: str) -> httpx.Response:
        # 202 is technically a 2xx, but Voicebox uses it to signal "Whisper
        # model still downloading" — surface it as a typed error, not success.
        if resp.status_code == 202:
            raise ModelDownloadingError(202, _detail(resp), path=path)
        if resp.is_success:
            return resp
        detail = _detail(resp)
        if resp.status_code == 404:
            raise ProfileNotFoundError(404, detail, path=path)
        raise VoiceboxAPIError(resp.status_code, detail, path=path)

    # -- health ----------------------------------------------------------
    def health(self) -> Dict[str, Any]:
        """Return the backend health payload, or raise if unreachable."""
        return self._request("GET", "/health").json()

    def is_up(self) -> bool:
        """True if the backend answers /health, False on any connection error."""
        try:
            self.health()
            return True
        except VoiceboxError:
            return False

    # -- profiles --------------------------------------------------------
    def list_profiles(self) -> List[Profile]:
        """List all voice profiles (cloned voices and presets)."""
        return list_profiles_from(self._request("GET", "/profiles").json())

    def find_profile(self, name_or_id: str) -> Optional[Profile]:
        """Resolve a profile by exact id or case-insensitive name, else None."""
        wanted = name_or_id.lower()
        for p in self.list_profiles():
            if p.id == name_or_id or p.name.lower() == wanted:
                return p
        return None

    # -- generation ------------------------------------------------------
    def generate(
        self,
        text: str,
        profile_id: str,
        *,
        language: str = "en",
        engine: Optional[str] = None,
        personality: bool = False,
        seed: Optional[int] = None,
        instruct: Optional[str] = None,
        **extra: Any,
    ) -> Generation:
        """Start a generation on ``/generate``. Returns immediately with a
        ``Generation`` whose ``status`` is ``"generating"``. Use
        :meth:`wait_for_generation` to block until it's done."""
        body: Dict[str, Any] = {
            "text": text,
            "profile_id": profile_id,
            "language": language,
            "personality": personality,
        }
        if engine is not None:
            body["engine"] = engine
        if seed is not None:
            body["seed"] = seed
        if instruct is not None:
            body["instruct"] = instruct
        body.update(extra)
        return Generation.from_dict(self._request("POST", "/generate", json=body).json())

    def speak(
        self,
        text: str,
        *,
        profile: Optional[str] = None,
        engine: Optional[str] = None,
        personality: Optional[bool] = None,
        language: Optional[str] = None,
    ) -> Generation:
        """Play ``text`` through a voice on the user's speakers (``/speak``).

        ``profile`` accepts a name or id. When omitted, Voicebox resolves the
        voice from this client's per-client binding, then the global default.
        Mirrors the ``voicebox.speak`` MCP tool exactly. Returns immediately;
        pair with :meth:`wait_for_generation` if you need the finished audio.
        """
        body: Dict[str, Any] = {"text": text}
        if profile is not None:
            body["profile"] = profile
        if engine is not None:
            body["engine"] = engine
        if personality is not None:
            body["personality"] = personality
        if language is not None:
            body["language"] = language
        return Generation.from_dict(self._request("POST", "/speak", json=body).json())

    def get_generation(self, generation_id: str) -> Generation:
        """Fetch the current state of a generation via ``/history/{id}``."""
        resp = self._request("GET", f"/history/{generation_id}")
        return Generation.from_dict(resp.json())

    def wait_for_generation(
        self,
        generation_id: str,
        *,
        timeout: float = 300.0,
        raise_on_failure: bool = True,
    ) -> Generation:
        """Block until a generation reaches a terminal state.

        Consumes the ``/generate/{id}/status`` SSE stream. If the stream ends
        or errors before a terminal status, falls back to polling
        ``/history/{id}`` until ``timeout`` elapses.
        """
        deadline = time.monotonic() + timeout
        last = self._await_via_sse(generation_id, deadline)
        if last is None or not last.is_terminal:
            last = self._await_via_polling(generation_id, deadline)
        if last is None:
            raise GenerationTimeoutError(generation_id, timeout)
        if last.status == "failed" and raise_on_failure:
            raise GenerationFailedError(generation_id, last.error)
        return last

    def _await_via_sse(self, generation_id: str, deadline: float) -> Optional[Generation]:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        try:
            with self._http.stream(
                "GET",
                f"/generate/{generation_id}/status",
                timeout=httpx.Timeout(remaining, read=remaining),
            ) as resp:
                if not resp.is_success:
                    return None
                last: Optional[Generation] = None
                for line in resp.iter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    try:
                        payload = json.loads(line[len("data:"):].strip())
                    except json.JSONDecodeError:
                        continue
                    last = Generation.from_dict(payload)
                    if last.is_terminal:
                        return last
                    if time.monotonic() >= deadline:
                        return last
                return last
        except httpx.HTTPError:
            return None

    def _await_via_polling(self, generation_id: str, deadline: float) -> Optional[Generation]:
        last: Optional[Generation] = None
        while time.monotonic() < deadline:
            last = self.get_generation(generation_id)
            if last.is_terminal:
                return last
            time.sleep(1.0)
        return last

    def speak_and_wait(
        self,
        text: str,
        *,
        profile: Optional[str] = None,
        engine: Optional[str] = None,
        personality: Optional[bool] = None,
        language: Optional[str] = None,
        timeout: float = 300.0,
    ) -> Generation:
        """:meth:`speak` then :meth:`wait_for_generation` in one call."""
        gen = self.speak(
            text, profile=profile, engine=engine,
            personality=personality, language=language,
        )
        return self.wait_for_generation(gen.id, timeout=timeout)

    def generate_and_wait(
        self, text: str, profile_id: str, *, timeout: float = 300.0, **kwargs: Any
    ) -> Generation:
        """:meth:`generate` then :meth:`wait_for_generation` in one call."""
        gen = self.generate(text, profile_id, **kwargs)
        return self.wait_for_generation(gen.id, timeout=timeout)

    # -- audio -----------------------------------------------------------
    def download_audio(self, generation_id: str, dest: PathLike) -> Path:
        """Download a completed generation's audio to ``dest``. Returns the path."""
        resp = self._request("GET", f"/audio/{generation_id}")
        out = Path(dest)
        out.write_bytes(resp.content)
        return out

    def audio_bytes(self, generation_id: str) -> bytes:
        """Return a completed generation's audio as raw bytes."""
        return self._request("GET", f"/audio/{generation_id}").content

    # -- transcription ---------------------------------------------------
    def transcribe(
        self,
        audio: PathLike,
        *,
        language: Optional[str] = None,
        model: Optional[str] = None,
    ) -> Transcription:
        """Transcribe an audio file via ``/transcribe`` (Whisper).

        ``model`` is one of base/small/medium/large/turbo. If the chosen model
        isn't cached yet, Voicebox starts downloading it and returns HTTP 202 —
        this raises :class:`ModelDownloadingError`; wait and retry.
        """
        path = Path(audio)
        data: Dict[str, str] = {}
        if language is not None:
            data["language"] = language
        if model is not None:
            data["model"] = model
        with path.open("rb") as fh:
            files = {"file": (path.name, fh, "application/octet-stream")}
            resp = self._request("POST", "/transcribe", data=data, files=files)
        return Transcription.from_dict(resp.json())
