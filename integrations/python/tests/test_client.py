"""Tests for voicebox_client, driven entirely by an httpx MockTransport —
no running Voicebox backend required.

    pip install httpx pytest
    pytest integrations/python/tests
"""

from __future__ import annotations

import json

import httpx
import pytest

from voicebox_client import (
    Generation,
    ModelDownloadingError,
    ProfileNotFoundError,
    VoiceboxClient,
    VoiceboxConnectionError,
)


def make_client(handler, **kwargs) -> VoiceboxClient:
    return VoiceboxClient(transport=httpx.MockTransport(handler),
                          client_id="test", max_retries=2, **kwargs)


def test_list_profiles():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/profiles"
        return httpx.Response(200, json=[
            {"id": "a1", "name": "Morgan", "voice_type": "cloned", "language": "en"},
            {"id": "b2", "name": "Kokoro-Bella", "voice_type": "preset", "language": "en"},
        ])

    with make_client(handler) as vb:
        profiles = vb.list_profiles()
        assert [p.name for p in profiles] == ["Morgan", "Kokoro-Bella"]
        assert vb.find_profile("morgan").id == "a1"      # case-insensitive name
        assert vb.find_profile("b2").name == "Kokoro-Bella"  # by id
        assert vb.find_profile("nope") is None


def test_speak_sends_client_id_and_body():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/speak"
        seen["client_id"] = request.headers.get("X-Voicebox-Client-Id")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "id": "gen1", "status": "generating", "profile_id": "a1",
            "text": "hi", "language": "en", "created_at": "2026-07-09T00:00:00Z",
        })

    with make_client(handler) as vb:
        gen = vb.speak("hi", profile="Morgan", personality=True)
        assert gen.id == "gen1" and gen.status == "generating"
        assert seen["client_id"] == "test"
        assert seen["body"] == {"text": "hi", "profile": "Morgan", "personality": True}


def test_profile_not_found_maps_to_typed_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "Voice profile 'X' not found."})

    with make_client(handler) as vb:
        with pytest.raises(ProfileNotFoundError) as ei:
            vb.speak("hi", profile="X")
        assert ei.value.status_code == 404


def test_wait_for_generation_consumes_sse():
    sse = (
        b'data: {"id": "gen1", "status": "generating"}\n\n'
        b'data: {"id": "gen1", "status": "completed", "duration": 2.5}\n\n'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/generate/gen1/status"
        return httpx.Response(200, content=sse,
                              headers={"content-type": "text/event-stream"})

    with make_client(handler) as vb:
        gen = vb.wait_for_generation("gen1", timeout=5)
        assert gen.succeeded and gen.duration == 2.5


def test_wait_falls_back_to_polling_when_sse_unavailable():
    calls = {"status": 0, "history": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/status"):
            calls["status"] += 1
            return httpx.Response(500, text="boom")  # SSE unavailable
        if request.url.path.startswith("/history/"):
            calls["history"] += 1
            status = "completed" if calls["history"] >= 2 else "generating"
            return httpx.Response(200, json={"id": "gen1", "status": status})
        return httpx.Response(404)

    with make_client(handler) as vb:
        gen = vb.wait_for_generation("gen1", timeout=10)
        assert gen.succeeded
        assert calls["history"] >= 2  # polled until terminal


def test_transcribe_uses_file_field(monkeypatch, tmp_path):
    audio = tmp_path / "clip.wav"
    audio.write_bytes(b"RIFFfake-wav-bytes")
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/transcribe"
        # multipart body must carry a part named "file" (README's "audio" is wrong)
        body = request.content
        seen["has_file_field"] = b'name="file"' in body
        seen["has_model_field"] = b'name="model"' in body
        return httpx.Response(200, json={"text": "hello world", "duration": 1.2})

    with make_client(handler) as vb:
        result = vb.transcribe(audio, model="turbo")
        assert result.text == "hello world"
        assert seen["has_file_field"] is True
        assert seen["has_model_field"] is True


def test_model_downloading_raises_202():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(202, json={
            "message": "downloading", "model_name": "whisper-turbo", "downloading": True,
        })

    with make_client(handler) as vb:
        # write a tiny file to transcribe
        import tempfile, os
        fd, path = tempfile.mkstemp(suffix=".wav")
        os.write(fd, b"x"); os.close(fd)
        try:
            with pytest.raises(ModelDownloadingError) as ei:
                vb.transcribe(path, model="turbo")
            assert ei.value.model_name == "whisper-turbo"
        finally:
            os.unlink(path)


def test_retries_on_503_then_succeeds(monkeypatch):
    monkeypatch.setattr("voicebox_client.client.time.sleep", lambda *_: None)
    state = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["n"] += 1
        if state["n"] == 1:
            return httpx.Response(503, text="warming up")
        return httpx.Response(200, json=[])

    with make_client(handler) as vb:
        assert vb.list_profiles() == []
        assert state["n"] == 2  # one retry


def test_connection_error_is_wrapped(monkeypatch):
    monkeypatch.setattr("voicebox_client.client.time.sleep", lambda *_: None)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with make_client(handler) as vb:
        with pytest.raises(VoiceboxConnectionError):
            vb.health()


def test_generation_dataclass_terminal_flags():
    g = Generation.from_dict({"id": "x", "status": "completed"})
    assert g.is_terminal and g.succeeded
    g2 = Generation.from_dict({"id": "x", "status": "generating"})
    assert not g2.is_terminal and not g2.succeeded
