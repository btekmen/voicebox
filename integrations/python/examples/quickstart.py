"""Quickstart: list profiles, speak a line, and save the audio.

Run Voicebox (desktop app, or `python -m backend.main --port 17493`), then:

    pip install httpx
    python examples/quickstart.py "Hello from Voicebox"
"""

import sys

from voicebox_client import VoiceboxClient, VoiceboxConnectionError


def main() -> int:
    text = sys.argv[1] if len(sys.argv) > 1 else "Hello from the Voicebox Python client."

    with VoiceboxClient(client_id="quickstart") as vb:
        if not vb.is_up():
            print("Voicebox isn't reachable. Start the app (or the backend on "
                  "port 17493) and try again.")
            return 1

        profiles = vb.list_profiles()
        print(f"{len(profiles)} voice profiles:")
        for p in profiles[:10]:
            print(f"  - {p.name}  ({p.voice_type or '?'}, {p.language or '?'})")

        if not profiles:
            print("No profiles yet — create one in the app first.")
            return 1

        voice = profiles[0].name
        print(f"\nGenerating with '{voice}' ...")
        gen = vb.speak_and_wait(text, profile=voice)
        out = vb.download_audio(gen.id, "quickstart.wav")
        print(f"Done: {out}  ({gen.duration:.1f}s)" if gen.duration else f"Done: {out}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except VoiceboxConnectionError as exc:
        print(exc)
        raise SystemExit(1)
