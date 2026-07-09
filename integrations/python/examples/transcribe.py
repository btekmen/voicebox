"""Transcribe an audio file via Voicebox's local Whisper.

    python examples/transcribe.py recording.wav --model turbo
"""

import argparse
import time

from voicebox_client import ModelDownloadingError, VoiceboxClient


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("audio", help="path to a .wav/.mp3/etc file")
    ap.add_argument("--model", default="turbo",
                    help="base|small|medium|large|turbo")
    ap.add_argument("--language", default=None)
    args = ap.parse_args()

    with VoiceboxClient(client_id="transcribe-example") as vb:
        for attempt in range(30):
            try:
                result = vb.transcribe(args.audio, model=args.model,
                                       language=args.language)
                break
            except ModelDownloadingError as exc:
                print(f"Downloading {exc.model_name}... waiting", flush=True)
                time.sleep(5)
        else:
            print("Model never finished downloading.")
            return 1

    print(f"[{result.duration:.1f}s] {result.text}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
