#!/usr/bin/env python3

import argparse
import os
import re
from pathlib import Path

import requests
import yaml


def split_frontmatter(md: str):
    if md.startswith("---"):
        parts = md.split("---", 2)
        if len(parts) >= 3:
            meta = yaml.safe_load(parts[1]) or {}
            body = parts[2].strip()
            return meta, body
    return {}, md.strip()


def extract_narration(md_body: str) -> str:
    lines = []

    for line in md_body.splitlines():
        line = line.strip()

        if not line:
            lines.append("")
            continue

        if line.startswith("# Scene:"):
            continue

        if line.startswith("#"):
            continue

        if line.startswith("!["):
            continue

        lines.append(line)

    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip() + "\n"


def generate_audio_with_elevenlabs(text: str, meta: dict, output_file: Path):
    api_key = os.getenv("ELEVENLABS_API_KEY")
    if not api_key:
        raise RuntimeError("Missing ELEVENLABS_API_KEY environment variable")

    tts = meta.get("tts", {})

    voice_id = tts.get("voice_id") or tts.get("voice")
    if not voice_id:
        raise RuntimeError("Missing tts.voice or tts.voice_id in storyboard.md")

    model_id = tts.get("model_id", "eleven_multilingual_v2")
    voice_settings = tts.get("voice_settings", {})

    payload = {
        "text": text,
        "model_id": model_id,
        "voice_settings": voice_settings,
    }

    # Optional: add style_prompt as context before the text.
    # ElevenLabs does not have a generic "style_prompt" field in the basic TTS API,
    # so we don't send it directly.
    url = (
        f"https://api.elevenlabs.io/v1/text-to-speech/"
        f"{voice_id}?output_format=mp3_44100_128"
    )

    response = requests.post(
        url,
        headers={
            "xi-api-key": api_key,
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=120,
    )

    if response.status_code >= 400:
        raise RuntimeError(
            f"ElevenLabs API error {response.status_code}:\n{response.text}"
        )

    output_file.write_bytes(response.content)


def main():
    parser = argparse.ArgumentParser(
        description="Generate narration text and ElevenLabs audio from storyboard.md"
    )
    parser.add_argument("directory", help="Directory containing storyboard.md")

    args = parser.parse_args()

    base_dir = Path(args.directory).resolve()
    storyboard_path = base_dir / "storyboard.md"

    if not storyboard_path.exists():
        raise FileNotFoundError(f"Missing file: {storyboard_path}")

    md = storyboard_path.read_text(encoding="utf-8")
    meta, body = split_frontmatter(md)

    narration = extract_narration(body)

    output_dir = base_dir / "generated" / "audio"
    output_dir.mkdir(parents=True, exist_ok=True)

    txt_file = output_dir / "narration.txt"
    mp3_file = output_dir / "narration.mp3"

    txt_file.write_text(narration, encoding="utf-8")

    generate_audio_with_elevenlabs(narration, meta, mp3_file)

    print(f"Generated text:  {txt_file}")
    print(f"Generated audio: {mp3_file}")
    print(f"Characters:      {len(narration)}")


if __name__ == "__main__":
    main()