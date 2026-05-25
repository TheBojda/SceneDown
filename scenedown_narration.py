#!/usr/bin/env python3

import argparse
import os
import re
import subprocess
import tempfile
from pathlib import Path

import requests
import yaml


MAX_CHARS = 9000


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


def split_text(text: str, max_chars: int = MAX_CHARS):
    paragraphs = text.split("\n\n")

    chunks = []
    current = ""

    for paragraph in paragraphs:
        paragraph = paragraph.strip()

        if not paragraph:
            continue

        candidate = current + "\n\n" + paragraph if current else paragraph

        if len(candidate) > max_chars:
            if current:
                chunks.append(current.strip())
                current = paragraph
            else:
                for i in range(0, len(paragraph), max_chars):
                    chunks.append(paragraph[i:i + max_chars])
                current = ""
        else:
            current = candidate

    if current:
        chunks.append(current.strip())

    return chunks


def generate_audio_chunk_with_elevenlabs(text: str, meta: dict, output_file: Path):
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

    if not response.content:
        raise RuntimeError("ElevenLabs returned empty audio content")

    output_file.write_bytes(response.content)


def concatenate_mp3_files(chunk_files, output_file: Path):
    """
    Safe MP3 concatenation using re-encoding.
    """

    if not chunk_files:
        raise RuntimeError("No audio chunks to concatenate")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        concat_file = tmpdir / "concat.txt"

        concat_file.write_text(
            "\n".join(f"file '{file.resolve()}'" for file in chunk_files),
            encoding="utf-8",
        )

        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", str(concat_file),
                "-acodec", "libmp3lame",
                "-b:a", "128k",
                "-ar", "44100",
                "-ac", "2",
                str(output_file),
            ],
            check=True,
        )


def clean_old_chunks(chunks_dir: Path):
    if not chunks_dir.exists():
        return

    for file in chunks_dir.glob("chunk_*.mp3"):
        file.unlink()

    for file in chunks_dir.glob("chunk_*.txt"):
        file.unlink()


def collect_existing_chunks(chunks_dir: Path):
    chunk_files = sorted(chunks_dir.glob("chunk_*.mp3"))

    if not chunk_files:
        raise RuntimeError(
            f"No existing chunk files found in: {chunks_dir}"
        )

    for chunk in chunk_files:
        if chunk.stat().st_size == 0:
            raise RuntimeError(f"Chunk file is empty: {chunk}")

    return chunk_files


def generate_audio_with_elevenlabs(
    text: str,
    meta: dict,
    output_file: Path,
    chunks_dir: Path,
    reuse_chunks: bool = False,
):
    chunks = split_text(text)

    print(f"Characters: {len(text)}")
    print(f"Chunks:     {len(chunks)}")

    chunks_dir.mkdir(parents=True, exist_ok=True)

    if reuse_chunks:
        print("Reusing existing chunks...")
        chunk_files = collect_existing_chunks(chunks_dir)

        print(f"Found {len(chunk_files)} existing chunks")

        concatenate_mp3_files(chunk_files, output_file)
        return

    clean_old_chunks(chunks_dir)

    chunk_files = []

    for index, chunk in enumerate(chunks, start=1):
        chunk_file = chunks_dir / f"chunk_{index:03d}.mp3"
        chunk_text_file = chunks_dir / f"chunk_{index:03d}.txt"

        print(
            f"Generating chunk {index}/{len(chunks)} "
            f"({len(chunk)} characters)"
        )

        chunk_text_file.write_text(chunk, encoding="utf-8")

        generate_audio_chunk_with_elevenlabs(
            chunk,
            meta,
            chunk_file,
        )

        if not chunk_file.exists() or chunk_file.stat().st_size == 0:
            raise RuntimeError(f"Generated chunk is missing or empty: {chunk_file}")

        chunk_files.append(chunk_file)

    if len(chunk_files) == 1:
        output_file.write_bytes(chunk_files[0].read_bytes())
    else:
        concatenate_mp3_files(chunk_files, output_file)

    if not output_file.exists() or output_file.stat().st_size == 0:
        raise RuntimeError(f"Final narration file is missing or empty: {output_file}")


def main():
    parser = argparse.ArgumentParser(
        description="Generate narration text and ElevenLabs audio from storyboard.md"
    )

    parser.add_argument(
        "directory",
        help="Directory containing storyboard.md"
    )

    parser.add_argument(
        "--reuse-chunks",
        action="store_true",
        help="Reuse existing chunk mp3 files instead of regenerating them"
    )

    args = parser.parse_args()

    base_dir = Path(args.directory).expanduser().resolve()
    storyboard_path = base_dir / "storyboard.md"

    if not storyboard_path.exists():
        raise FileNotFoundError(f"Missing file: {storyboard_path}")

    md = storyboard_path.read_text(encoding="utf-8")
    meta, body = split_frontmatter(md)

    narration = extract_narration(body)

    output_dir = base_dir / "generated" / "audio"
    output_dir.mkdir(parents=True, exist_ok=True)

    chunks_dir = output_dir / "chunks"

    txt_file = output_dir / "narration.txt"
    mp3_file = output_dir / "narration.mp3"

    txt_file.write_text(narration, encoding="utf-8")

    generate_audio_with_elevenlabs(
        narration,
        meta,
        mp3_file,
        chunks_dir,
        reuse_chunks=args.reuse_chunks,
    )

    print(f"Generated text:   {txt_file}")
    print(f"Generated audio:  {mp3_file}")
    print(f"Generated chunks: {chunks_dir}")


if __name__ == "__main__":
    main()