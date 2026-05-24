#!/usr/bin/env python3

import argparse
import json
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


def clean_text(line: str) -> str:
    line = re.sub(r"!\[.*?\]\(.*?\).*", "", line)
    line = re.sub(r"\{.*?\}", "", line)
    return line.strip()


def normalize_words(text: str):
    text = text.lower()
    text = re.sub(r"[^a-z0-9']+", " ", text)
    return [w for w in text.split() if w]


def extract_scenes(md_body: str):
    scenes = []
    current = None

    for raw in md_body.splitlines():
        line = raw.strip()

        if line.startswith("# Scene:"):
            if current:
                current["text"] = "\n".join(current["lines"]).strip()
                scenes.append(current)

            current = {
                "title": line.replace("# Scene:", "").strip(),
                "lines": [],
            }
            continue

        if not current:
            continue

        if not line or line.startswith("#") or line.startswith("!["):
            continue

        text = clean_text(line)
        if text:
            current["lines"].append(text)

    if current:
        current["text"] = "\n".join(current["lines"]).strip()
        scenes.append(current)

    return scenes


def generate_elevenlabs_alignment(audio_file: Path, transcript: str):
    api_key = os.getenv("ELEVENLABS_API_KEY")
    if not api_key:
        raise RuntimeError("Missing ELEVENLABS_API_KEY environment variable")

    url = "https://api.elevenlabs.io/v1/forced-alignment"

    with audio_file.open("rb") as f:
        response = requests.post(
            url,
            headers={
                "xi-api-key": api_key,
            },
            files={
                "file": (audio_file.name, f, "audio/mpeg"),
            },
            data={
                "text": transcript,
            },
            timeout=300,
        )

    if response.status_code >= 400:
        raise RuntimeError(
            f"ElevenLabs Forced Alignment API error {response.status_code}:\n"
            f"{response.text}"
        )

    return response.json()


def seconds_to_srt_time(seconds: float):
    ms = int(round(seconds * 1000))
    h = ms // 3_600_000
    ms %= 3_600_000
    m = ms // 60_000
    ms %= 60_000
    s = ms // 1000
    ms %= 1000
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def split_words_into_subtitles(words, max_chars=72, max_duration=6.0):
    subtitles = []
    current = []

    for word in words:
        if "start" not in word or "end" not in word:
            continue

        text = word["text"].strip()
        if not text:
            continue

        proposed = current + [word]
        proposed_text = " ".join(w["text"] for w in proposed)
        duration = proposed[-1]["end"] - proposed[0]["start"]

        if current and (len(proposed_text) > max_chars or duration > max_duration):
            subtitles.append({
                "start": current[0]["start"],
                "end": current[-1]["end"],
                "text": " ".join(w["text"] for w in current),
            })
            current = [word]
        else:
            current = proposed

    if current:
        subtitles.append({
            "start": current[0]["start"],
            "end": current[-1]["end"],
            "text": " ".join(w["text"] for w in current),
        })

    return subtitles


def write_srt(subtitles, output_file: Path):
    blocks = []

    for i, sub in enumerate(subtitles, start=1):
        start = seconds_to_srt_time(sub["start"])
        end = seconds_to_srt_time(sub["end"])
        text = sub["text"].strip()
        blocks.append(f"{i}\n{start} --> {end}\n{text}")

    output_file.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")


def convert_elevenlabs_words(alignment_data):
    words = []

    for word in alignment_data.get("words", []):
        if "start" not in word or "end" not in word:
            continue

        text = word.get("text", "").strip()
        normalized = normalize_words(text)

        if not normalized:
            continue

        words.append({
            "word": normalized[0],
            "text": text,
            "start": float(word["start"]),
            "end": float(word["end"]),
            "loss": word.get("loss"),
        })

    return words


def align_scenes_to_words(scenes, words):
    result = []
    cursor = 0

    for scene in scenes:
        scene_words = normalize_words(scene["text"])

        if not scene_words:
            continue

        start_index = None
        end_index = None

        for i in range(cursor, len(words)):
            if words[i]["word"] == scene_words[0]:
                start_index = i
                break

        if start_index is None:
            start_index = cursor

        j = start_index
        matched = 0

        while j < len(words) and matched < len(scene_words):
            if words[j]["word"] == scene_words[matched]:
                matched += 1
                end_index = j
            j += 1

        if end_index is None:
            end_index = min(start_index + len(scene_words), len(words) - 1)

        result.append({
            "title": scene["title"],
            "start": words[start_index]["start"],
            "end": words[end_index]["end"],
            "duration": words[end_index]["end"] - words[start_index]["start"],
            "text": scene["text"],
        })

        cursor = end_index + 1

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Generate ElevenLabs forced alignment and YouTube subtitles"
    )
    parser.add_argument("directory", help="Directory containing storyboard.md")
    args = parser.parse_args()

    base_dir = Path(args.directory).resolve()

    storyboard_path = base_dir / "storyboard.md"
    audio_file = base_dir / "generated" / "audio" / "narration.mp3"
    transcript_file = base_dir / "generated" / "audio" / "narration.txt"

    if not storyboard_path.exists():
        raise FileNotFoundError(f"Missing file: {storyboard_path}")

    if not audio_file.exists():
        raise FileNotFoundError(f"Missing audio file: {audio_file}")

    if not transcript_file.exists():
        raise FileNotFoundError(f"Missing transcript file: {transcript_file}")

    md = storyboard_path.read_text(encoding="utf-8")
    _, body = split_frontmatter(md)

    scenes = extract_scenes(body)
    transcript = transcript_file.read_text(encoding="utf-8")

    alignment_dir = base_dir / "generated" / "alignment"
    subtitles_dir = base_dir / "generated" / "subtitles"

    alignment_dir.mkdir(parents=True, exist_ok=True)
    subtitles_dir.mkdir(parents=True, exist_ok=True)

    alignment_data = generate_elevenlabs_alignment(audio_file, transcript)

    raw_alignment_file = alignment_dir / "elevenlabs_alignment.json"
    words_file = alignment_dir / "words.json"
    scenes_file = alignment_dir / "scenes.json"
    srt_file = subtitles_dir / "subtitles.srt"

    raw_alignment_file.write_text(
        json.dumps(alignment_data, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    words = convert_elevenlabs_words(alignment_data)
    scene_alignment = align_scenes_to_words(scenes, words)
    subtitles = split_words_into_subtitles(words)

    words_file.write_text(
        json.dumps(words, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    scenes_file.write_text(
        json.dumps(scene_alignment, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    write_srt(subtitles, srt_file)

    print(f"Generated raw alignment:   {raw_alignment_file}")
    print(f"Generated word alignment:  {words_file}")
    print(f"Generated scene alignment: {scenes_file}")
    print(f"Generated subtitles:       {srt_file}")
    print(f"Words:                     {len(words)}")
    print(f"Scenes:                    {len(scene_alignment)}")


if __name__ == "__main__":
    main()