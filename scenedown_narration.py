#!/usr/bin/env python3

import argparse
import os
import re
import subprocess
import tempfile
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


def split_into_sentences(text: str):
    text = re.sub(r"\s+", " ", text.strip())
    if not text:
        return []

    return re.split(r"(?<=[.!?])\s+", text)


def split_text(text: str, max_chars: int):
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

    chunks = []
    current = ""

    for paragraph in paragraphs:
        sentences = split_into_sentences(paragraph)

        for sentence in sentences:
            candidate = f"{current} {sentence}".strip() if current else sentence

            if len(candidate) > max_chars:
                if current:
                    chunks.append(current.strip())
                    current = sentence
                else:
                    for i in range(0, len(sentence), max_chars):
                        chunks.append(sentence[i:i + max_chars].strip())
                    current = ""
            else:
                current = candidate

    if current:
        chunks.append(current.strip())

    return chunks


def context_before(chunks, index: int, chars: int):
    if index <= 0:
        return None

    text = " ".join(chunks[:index])
    return text[-chars:] if text else None


def context_after(chunks, index: int, chars: int):
    if index >= len(chunks) - 1:
        return None

    text = " ".join(chunks[index + 1:])
    return text[:chars] if text else None


def run_ffmpeg(args):
    try:
        subprocess.run(
            ["ffmpeg", "-y", *args],
            check=True,
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"ffmpeg failed with exit code {e.returncode}") from e


def normalize_chunk_to_wav(
    input_file: Path,
    output_file: Path,
    target_lufs: float,
    true_peak: float,
    lra: float,
):
    run_ffmpeg([
        "-i", str(input_file),
        "-af", f"loudnorm=I={target_lufs}:TP={true_peak}:LRA={lra}",
        "-ar", "44100",
        "-ac", "2",
        str(output_file),
    ])


def concatenate_wav_files(wav_files, output_wav: Path):
    if not wav_files:
        raise RuntimeError("No WAV chunks to concatenate")

    with tempfile.TemporaryDirectory() as tmpdir:
        concat_file = Path(tmpdir) / "concat.txt"

        concat_file.write_text(
            "\n".join(f"file '{file.resolve()}'" for file in wav_files),
            encoding="utf-8",
        )

        run_ffmpeg([
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_file),
            "-c", "copy",
            str(output_wav),
        ])


def export_final_mp3(
    input_wav: Path,
    output_mp3: Path,
    target_lufs: float,
    true_peak: float,
    lra: float,
    bitrate: str,
):
    run_ffmpeg([
        "-i", str(input_wav),
        "-af", f"loudnorm=I={target_lufs}:TP={true_peak}:LRA={lra}",
        "-acodec", "libmp3lame",
        "-b:a", bitrate,
        "-ar", "44100",
        "-ac", "2",
        str(output_mp3),
    ])


def generate_audio_chunk_with_elevenlabs(
    text: str,
    meta: dict,
    output_file: Path,
    previous_text: str | None = None,
    next_text: str | None = None,
):
    api_key = os.getenv("ELEVENLABS_API_KEY")
    if not api_key:
        raise RuntimeError("Missing ELEVENLABS_API_KEY environment variable")

    tts = meta.get("tts", {})

    provider = tts.get("provider", "elevenlabs")
    if provider != "elevenlabs":
        raise RuntimeError(f"Unsupported TTS provider: {provider}")

    voice_id = tts.get("voice_id") or tts.get("voice")
    if not voice_id:
        raise RuntimeError("Missing tts.voice_id in storyboard.md")

    model_id = tts.get("model_id", "eleven_multilingual_v2")
    voice_settings = tts.get("voice_settings", {})
    seed = tts.get("seed")

    payload = {
        "text": text,
        "model_id": model_id,
        "voice_settings": voice_settings,
    }

    if seed is not None:
        payload["seed"] = seed

    if previous_text:
        payload["previous_text"] = previous_text

    if next_text:
        payload["next_text"] = next_text

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
        timeout=180,
    )

    if response.status_code >= 400:
        raise RuntimeError(
            f"ElevenLabs API error {response.status_code}:\n{response.text}"
        )

    if not response.content:
        raise RuntimeError("ElevenLabs returned empty audio content")

    output_file.write_bytes(response.content)


def clean_old_chunks(chunks_dir: Path):
    if not chunks_dir.exists():
        return

    for pattern in (
        "chunk_*.mp3",
        "chunk_*.txt",
    ):
        for file in chunks_dir.glob(pattern):
            file.unlink()


def collect_existing_chunks(chunks_dir: Path):
    chunk_files = sorted(chunks_dir.glob("chunk_*.mp3"))

    if not chunk_files:
        raise RuntimeError(f"No existing chunk files found in: {chunks_dir}")

    for chunk in chunk_files:
        if chunk.stat().st_size == 0:
            raise RuntimeError(f"Chunk file is empty: {chunk}")

    return chunk_files


def build_final_audio_from_chunks(
    chunk_files,
    output_file: Path,
    target_lufs: float,
    true_peak: float,
    lra: float,
    bitrate: str,
):
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        normalized_wavs = []

        for index, chunk_file in enumerate(chunk_files, start=1):
            wav_file = tmpdir / f"chunk_{index:03d}.normalized.wav"

            print(f"Normalizing chunk {index}/{len(chunk_files)}")

            normalize_chunk_to_wav(
                input_file=chunk_file,
                output_file=wav_file,
                target_lufs=target_lufs,
                true_peak=true_peak,
                lra=lra,
            )

            normalized_wavs.append(wav_file)

        full_wav = tmpdir / "narration.full.wav"

        concatenate_wav_files(normalized_wavs, full_wav)

        export_final_mp3(
            input_wav=full_wav,
            output_mp3=output_file,
            target_lufs=target_lufs,
            true_peak=true_peak,
            lra=lra,
            bitrate=bitrate,
        )


def get_tts_config(meta: dict):
    tts = meta.get("tts", {})
    chunking = tts.get("chunking", {})
    post = tts.get("post_processing", {})

    return {
        "max_chars": int(chunking.get("max_chars", 9000)),
        "context_chars": int(chunking.get("context_chars", 1200)),
        "target_lufs": float(post.get("target_lufs", -16)),
        "true_peak": float(post.get("true_peak", -1.5)),
        "lra": float(post.get("lra", 11)),
        "bitrate": str(post.get("bitrate", "192k")),
    }


def generate_audio_with_elevenlabs(
    text: str,
    meta: dict,
    output_file: Path,
    chunks_dir: Path,
    reuse_chunks: bool = False,
):
    config = get_tts_config(meta)

    chunks = split_text(
        text,
        max_chars=config["max_chars"],
    )

    print(f"Characters: {len(text)}")
    print(f"Chunks:     {len(chunks)}")
    print(f"Max chars:  {config['max_chars']}")
    print(f"Context:    {config['context_chars']} chars")

    chunks_dir.mkdir(parents=True, exist_ok=True)

    if reuse_chunks:
        print("Reusing existing chunks...")
        chunk_files = collect_existing_chunks(chunks_dir)
        print(f"Found {len(chunk_files)} existing chunks")
    else:
        clean_old_chunks(chunks_dir)

        chunk_files = []

        for index, chunk in enumerate(chunks):
            chunk_number = index + 1

            chunk_file = chunks_dir / f"chunk_{chunk_number:03d}.mp3"
            chunk_text_file = chunks_dir / f"chunk_{chunk_number:03d}.txt"

            print(
                f"Generating chunk {chunk_number}/{len(chunks)} "
                f"({len(chunk)} characters)"
            )

            chunk_text_file.write_text(chunk, encoding="utf-8")

            generate_audio_chunk_with_elevenlabs(
                text=chunk,
                meta=meta,
                output_file=chunk_file,
                previous_text=context_before(
                    chunks,
                    index,
                    chars=config["context_chars"],
                ),
                next_text=context_after(
                    chunks,
                    index,
                    chars=config["context_chars"],
                ),
            )

            if not chunk_file.exists() or chunk_file.stat().st_size == 0:
                raise RuntimeError(f"Generated chunk is missing or empty: {chunk_file}")

            chunk_files.append(chunk_file)

    build_final_audio_from_chunks(
        chunk_files=chunk_files,
        output_file=output_file,
        target_lufs=config["target_lufs"],
        true_peak=config["true_peak"],
        lra=config["lra"],
        bitrate=config["bitrate"],
    )

    if not output_file.exists() or output_file.stat().st_size == 0:
        raise RuntimeError(f"Final narration file is missing or empty: {output_file}")


def main():
    parser = argparse.ArgumentParser(
        description="Generate narration text and ElevenLabs audio from storyboard.md"
    )

    parser.add_argument(
        "directory",
        help="Directory containing storyboard.md",
    )

    parser.add_argument(
        "--reuse-chunks",
        action="store_true",
        help="Reuse existing chunk mp3 files instead of regenerating them",
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
        text=narration,
        meta=meta,
        output_file=mp3_file,
        chunks_dir=chunks_dir,
        reuse_chunks=args.reuse_chunks,
    )

    print(f"Generated text:   {txt_file}")
    print(f"Generated audio:  {mp3_file}")
    print(f"Generated chunks: {chunks_dir}")


if __name__ == "__main__":
    main()