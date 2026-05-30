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

        text = clean_text(line)
        if text:
            lines.append(text)

    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip() + "\n"


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

        if not line:
            continue

        if line.startswith("#"):
            continue

        if line.startswith("!["):
            continue

        text = clean_text(line)

        if text:
            current["lines"].append(text)

    if current:
        current["text"] = "\n".join(current["lines"]).strip()
        scenes.append(current)

    return scenes


def normalize_words(text: str):
    text = text.lower()
    text = re.sub(r"[^a-z0-9']+", " ", text)
    return [w for w in text.split() if w]


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


def build_character_timeline(alignment_data):
    chars = []

    for item in alignment_data.get("characters", []):
        if "start" not in item or "end" not in item:
            continue

        chars.append({
            "text": item.get("text", ""),
            "start": float(item["start"]),
            "end": float(item["end"]),
        })

    if not chars:
        raise RuntimeError(
            "No character alignment found. "
            "ElevenLabs response does not contain usable characters."
        )

    return chars


def char_time_at(chars, index: int, prefer_end: bool = False):
    if index < 0:
        index = 0

    if index >= len(chars):
        index = len(chars) - 1

    # Skip empty or weird chars defensively.
    step = -1 if prefer_end else 1
    i = index

    while 0 <= i < len(chars):
        ch = chars[i]
        if "start" in ch and "end" in ch:
            return ch["end"] if prefer_end else ch["start"]
        i += step

    ch = chars[max(0, min(index, len(chars) - 1))]
    return ch["end"] if prefer_end else ch["start"]


def normalize_with_index_map(text: str):
    """
    Normalize text for robust matching while keeping a map back to the
    original character positions.

    This intentionally ignores punctuation/case differences and works with
    Hungarian accented characters. The previous version required almost exact
    string equality, so a changed comma, dash, quote, or small edit in
    narration.txt could make the whole alignment fail at a scene boundary.
    """
    normalized = []
    index_map = []
    in_space = True

    for i, ch in enumerate(text):
        if ch.isalnum():
            normalized.append(ch.casefold())
            index_map.append(i)
            in_space = False
        else:
            if not in_space:
                normalized.append(" ")
                index_map.append(i)
                in_space = True

    # Drop leading/trailing normalized spaces together with their map entries.
    while normalized and normalized[0] == " ":
        normalized.pop(0)
        index_map.pop(0)

    while normalized and normalized[-1] == " ":
        normalized.pop()
        index_map.pop()

    return "".join(normalized), index_map


def _find_best_anchor(normalized_transcript: str, normalized_scene: str, cursor: int):
    """
    Fallback for scenes that are not an exact match.

    It searches for a reasonably long prefix and suffix from the scene text.
    This handles the common case where narration.txt was generated from a
    slightly older/newer storyboard: the scene may contain a sentence-level edit,
    but its beginning and end are still present.
    """
    words = normalized_scene.split()
    if len(words) < 8:
        return None

    # Try increasingly shorter anchors. Keep these word-based so Hungarian
    # punctuation and line breaks do not matter.
    max_anchor = min(18, max(8, len(words) // 3))
    min_anchor = 5

    for anchor_len in range(max_anchor, min_anchor - 1, -1):
        prefix = " ".join(words[:anchor_len])
        suffix = " ".join(words[-anchor_len:])

        start = normalized_transcript.find(prefix, cursor)
        if start == -1:
            continue

        suffix_start_min = start + len(prefix)
        suffix_pos = normalized_transcript.find(suffix, suffix_start_min)
        if suffix_pos == -1:
            continue

        end = suffix_pos + len(suffix) - 1
        return start, end, anchor_len

    return None


def find_scene_positions_in_transcript(scenes, transcript: str):
    positions = []

    normalized_transcript, transcript_map = normalize_with_index_map(transcript)
    cursor = 0

    for scene in scenes:
        scene_text = scene["text"].strip()

        if not scene_text:
            continue

        normalized_scene, _ = normalize_with_index_map(scene_text)

        start_norm = normalized_transcript.find(normalized_scene, cursor)

        if start_norm != -1:
            end_norm = start_norm + len(normalized_scene) - 1
            match_mode = "exact"
        else:
            fallback = _find_best_anchor(
                normalized_transcript,
                normalized_scene,
                cursor,
            )

            if not fallback:
                context_start = max(0, cursor - 300)
                context_end = min(len(normalized_transcript), cursor + 900)
                context = normalized_transcript[context_start:context_end]
                raise RuntimeError(
                    f"Could not find scene text in narration transcript: "
                    f"{scene['title']}\n"
                    f"This usually means generated/audio/narration.txt was "
                    f"created from a different storyboard.md. Regenerate "
                    f"narration.txt/audio, or inspect this normalized transcript "
                    f"area near the failure:\n{context}"
                )

            start_norm, end_norm, anchor_len = fallback
            match_mode = f"anchor:{anchor_len}w"
            print(
                f"Warning: scene '{scene['title']}' was matched by anchors "
                f"instead of exact text. Check whether narration.txt and "
                f"storyboard.md differ."
            )

        start_char = transcript_map[start_norm]
        end_char = transcript_map[end_norm] + 1

        positions.append({
            "scene": scene,
            "start_char": start_char,
            "end_char": end_char,
            "match_mode": match_mode,
        })

        cursor = end_norm + 1

    return positions


def align_scenes_to_characters(scenes, transcript: str, alignment_data):
    chars = build_character_timeline(alignment_data)

    if len(chars) < len(transcript.strip()) * 0.8:
        print(
            "Warning: character alignment is much shorter than transcript. "
            "The audio or transcript may be incomplete."
        )

    positions = find_scene_positions_in_transcript(scenes, transcript)

    result = []

    for item in positions:
        scene = item["scene"]
        start_char = item["start_char"]
        end_char = item["end_char"]

        start_time = char_time_at(chars, start_char, prefer_end=False)
        end_time = char_time_at(chars, end_char - 1, prefer_end=True)

        result.append({
            "title": scene["title"],
            "start": start_time,
            "end": end_time,
            "duration": end_time - start_time,
            "text": scene["text"],
            "start_char": start_char,
            "end_char": end_char,
            "match_mode": item.get("match_mode", "exact"),
        })

    return result


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

        if current and (
            len(proposed_text) > max_chars or duration > max_duration
        ):
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


def main():
    parser = argparse.ArgumentParser(
        description="Generate ElevenLabs forced alignment and YouTube subtitles"
    )

    parser.add_argument(
        "directory",
        help="Directory containing storyboard.md"
    )

    parser.add_argument(
        "--reuse-alignment",
        action="store_true",
        help="Reuse generated/alignment/elevenlabs_alignment.json instead of calling ElevenLabs again"
    )

    args = parser.parse_args()

    base_dir = Path(args.directory).expanduser().resolve()

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

    raw_alignment_file = alignment_dir / "elevenlabs_alignment.json"
    words_file = alignment_dir / "words.json"
    scenes_file = alignment_dir / "scenes.json"
    srt_file = subtitles_dir / "subtitles.srt"

    if args.reuse_alignment:
        if not raw_alignment_file.exists():
            raise FileNotFoundError(
                f"Missing existing alignment file: {raw_alignment_file}"
            )

        print(f"Reusing alignment: {raw_alignment_file}")
        alignment_data = json.loads(raw_alignment_file.read_text(encoding="utf-8"))
    else:
        alignment_data = generate_elevenlabs_alignment(audio_file, transcript)

        raw_alignment_file.write_text(
            json.dumps(alignment_data, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )

    words = convert_elevenlabs_words(alignment_data)

    print(f"Extracted scenes: {len(scenes)}")
    print(f"Aligned words:    {len(words)}")
    print(f"Aligned chars:    {len(alignment_data.get('characters', []))}")

    scene_alignment = align_scenes_to_characters(
        scenes,
        transcript,
        alignment_data,
    )

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