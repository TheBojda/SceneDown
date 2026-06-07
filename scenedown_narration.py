#!/usr/bin/env python3

import argparse
import copy
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import requests
import yaml


@dataclass
class SceneNarration:
    number: int
    title: str
    text: str


def split_frontmatter(md: str):
    if md.startswith("---"):
        parts = md.split("---", 2)
        if len(parts) >= 3:
            meta = yaml.safe_load(parts[1]) or {}
            body = parts[2].strip()
            return meta, body
    return {}, md.strip()


def clean_narration_lines(lines) -> str:
    cleaned = []

    for line in lines:
        line = line.strip()

        if not line:
            cleaned.append("")
            continue

        if line.startswith("#"):
            continue

        if line.startswith("!["):
            continue

        cleaned.append(line)

    text = "\n".join(cleaned)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_scenes(md_body: str):
    scenes = []
    current_title = None
    current_lines = []

    scene_re = re.compile(r"^#\s*Scene:\s*(.*)\s*$", re.IGNORECASE)

    def flush_scene():
        nonlocal current_title, current_lines

        if current_title is None:
            return

        text = clean_narration_lines(current_lines)
        if text:
            scenes.append(
                SceneNarration(
                    number=len(scenes) + 1,
                    title=current_title.strip(),
                    text=text + "\n",
                )
            )

        current_title = None
        current_lines = []

    for line in md_body.splitlines():
        match = scene_re.match(line.strip())

        if match:
            flush_scene()
            current_title = match.group(1).strip() or f"Scene {len(scenes) + 1}"
            current_lines = []
            continue

        if current_title is not None:
            current_lines.append(line)

    flush_scene()

    if not scenes:
        text = clean_narration_lines(md_body.splitlines())
        if text:
            scenes.append(
                SceneNarration(
                    number=1,
                    title="Narration",
                    text=text + "\n",
                )
            )

    return scenes


def extract_narration(md_body: str) -> str:
    scenes = extract_scenes(md_body)
    return "\n\n".join(scene.text.strip() for scene in scenes).strip() + "\n"


def _join_scene_texts(scenes) -> str:
    return "\n\n".join(scene.text.strip() for scene in scenes if scene.text.strip())


def context_before(scenes, index: int, chars: int, scene_count: int | None = None):
    if index <= 0:
        return None

    previous_scenes = scenes[:index]
    if scene_count is not None and scene_count > 0:
        previous_scenes = previous_scenes[-scene_count:]

    text = _join_scene_texts(previous_scenes)
    return text[-chars:] if text else None


def context_after(scenes, index: int, chars: int, scene_count: int | None = None):
    if index >= len(scenes) - 1:
        return None

    next_scenes = scenes[index + 1:]
    if scene_count is not None and scene_count > 0:
        next_scenes = next_scenes[:scene_count]

    text = _join_scene_texts(next_scenes)
    return text[:chars] if text else None


def run_ffmpeg(args):
    try:
        subprocess.run(
            ["ffmpeg", "-y", *args],
            check=True,
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"ffmpeg failed with exit code {e.returncode}") from e


def normalize_audio_to_wav(input_file: Path, output_file: Path, target_lufs: float, true_peak: float, lra: float):
    run_ffmpeg([
        "-i", str(input_file),
        "-af", f"loudnorm=I={target_lufs}:TP={true_peak}:LRA={lra}",
        "-ar", "44100",
        "-ac", "2",
        str(output_file),
    ])


def concatenate_wav_files(wav_files, output_wav: Path):
    if not wav_files:
        raise RuntimeError("No WAV files to concatenate")

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


def export_final_mp3(input_wav: Path, output_mp3: Path, target_lufs: float, true_peak: float, lra: float, bitrate: str):
    run_ffmpeg([
        "-i", str(input_wav),
        "-af", f"loudnorm=I={target_lufs}:TP={true_peak}:LRA={lra}",
        "-acodec", "libmp3lame",
        "-b:a", bitrate,
        "-ar", "44100",
        "-ac", "2",
        str(output_mp3),
    ])


def get_effective_meta(meta: dict):
    """Return a copy of meta with optional consistency defaults applied.

    Frontmatter example:

    tts:
      consistency:
        enabled: true
        stability: 0.8
        similarity_boost: 0.9
        style: 0.1
        use_speaker_boost: true
    """
    effective_meta = copy.deepcopy(meta)
    tts = effective_meta.setdefault("tts", {})
    voice_settings = tts.setdefault("voice_settings", {})
    consistency = tts.get("consistency", {}) or {}

    if consistency.get("enabled", True):
        defaults = {
            "stability": 0.8,
            "similarity_boost": 0.9,
            "style": 0.1,
            "use_speaker_boost": True,
        }

        for key, value in defaults.items():
            voice_settings.setdefault(key, value)

        # Explicit consistency values override voice_settings.
        for key in defaults:
            if key in consistency:
                voice_settings[key] = consistency[key]

    return effective_meta


def generate_audio_with_elevenlabs(text: str, meta: dict, output_file: Path, previous_text: str | None = None, next_text: str | None = None):
    api_key = os.getenv("ELEVENLABS_API_KEY")
    if not api_key:
        raise RuntimeError("Missing ELEVENLABS_API_KEY environment variable")

    effective_meta = get_effective_meta(meta)
    tts = effective_meta.get("tts", {})

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

    supports_context = model_id not in {"eleven_v3"}

    if supports_context:
        if previous_text:
            payload["previous_text"] = previous_text
        if next_text:
            payload["next_text"] = next_text

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}?output_format=mp3_44100_128"

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
        raise RuntimeError(f"ElevenLabs API error {response.status_code}:\n{response.text}")

    if not response.content:
        raise RuntimeError("ElevenLabs returned empty audio content")

    output_file.write_bytes(response.content)


def clean_old_scenes(scenes_dir: Path):
    if not scenes_dir.exists():
        return

    for pattern in ("scene_*.mp3", "scene_*.txt"):
        for file in scenes_dir.glob(pattern):
            file.unlink()


def scene_mp3_path(scenes_dir: Path, scene_number: int):
    return scenes_dir / f"scene_{scene_number:03d}.mp3"


def scene_txt_path(scenes_dir: Path, scene_number: int):
    return scenes_dir / f"scene_{scene_number:03d}.txt"


def collect_scene_audio_files(scenes_dir: Path, scenes):
    scene_files = []

    for scene in scenes:
        scene_file = scene_mp3_path(scenes_dir, scene.number)

        if not scene_file.exists():
            raise RuntimeError(
                f"Missing scene audio: {scene_file}\n"
                "Generate all scenes first, or omit --regen-scene."
            )

        if scene_file.stat().st_size == 0:
            raise RuntimeError(f"Scene audio file is empty: {scene_file}")

        scene_files.append(scene_file)

    return scene_files


def build_final_audio_from_scenes(scene_files, output_file: Path, target_lufs: float, true_peak: float, lra: float, bitrate: str):
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        normalized_wavs = []

        for index, scene_file in enumerate(scene_files, start=1):
            wav_file = tmpdir / f"scene_{index:03d}.normalized.wav"
            print(f"Normalizing scene {index}/{len(scene_files)}")
            normalize_audio_to_wav(
                input_file=scene_file,
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
    post = tts.get("post_processing", {})
    consistency = tts.get("consistency", {}) or {}

    return {
        "context_chars": int(tts.get("context_chars", consistency.get("context_chars", 3000))),
        "context_scenes_before": int(tts.get("context_scenes_before", consistency.get("context_scenes_before", 2))),
        "context_scenes_after": int(tts.get("context_scenes_after", consistency.get("context_scenes_after", 2))),
        "target_lufs": float(post.get("target_lufs", -16)),
        "true_peak": float(post.get("true_peak", -1.5)),
        "lra": float(post.get("lra", 11)),
        "bitrate": str(post.get("bitrate", "192k")),
    }


def generate_scene_audio(scenes, meta: dict, output_file: Path, scenes_dir: Path, reuse_scenes: bool = False, regen_scene: int | None = None):
    config = get_tts_config(meta)
    effective_meta = get_effective_meta(meta)
    voice_settings = effective_meta.get("tts", {}).get("voice_settings", {})

    print(f"Scenes:      {len(scenes)}")
    print(f"Characters:  {sum(len(scene.text) for scene in scenes)}")
    print(f"Context:     {config['context_chars']} chars")
    print(f"Prev scenes: {config['context_scenes_before']}")
    print(f"Next scenes: {config['context_scenes_after']}")
    print(f"Voice settings: {voice_settings}")

    scenes_dir.mkdir(parents=True, exist_ok=True)

    if regen_scene is not None and (regen_scene < 1 or regen_scene > len(scenes)):
        raise RuntimeError(f"Invalid scene number: {regen_scene}. Valid range: 1-{len(scenes)}")

    if regen_scene is None and not reuse_scenes:
        clean_old_scenes(scenes_dir)

    if reuse_scenes and regen_scene is None:
        print("Reusing existing scene audio files...")
    else:
        for index, scene in enumerate(scenes):
            should_generate = True

            if regen_scene is not None:
                should_generate = scene.number == regen_scene

            if reuse_scenes and regen_scene is None:
                should_generate = False

            if not should_generate:
                continue

            scene_file = scene_mp3_path(scenes_dir, scene.number)
            scene_text_file = scene_txt_path(scenes_dir, scene.number)

            previous_text = context_before(
                scenes,
                index,
                chars=config["context_chars"],
                scene_count=config["context_scenes_before"],
            )
            next_text = context_after(
                scenes,
                index,
                chars=config["context_chars"],
                scene_count=config["context_scenes_after"],
            )

            print(
                f"Generating scene {scene.number}/{len(scenes)}: "
                f"{scene.title} ({len(scene.text)} characters, "
                f"prev_context={len(previous_text or '')}, next_context={len(next_text or '')})"
            )

            scene_text_file.write_text(scene.text, encoding="utf-8")

            generate_audio_with_elevenlabs(
                text=scene.text,
                meta=effective_meta,
                output_file=scene_file,
                previous_text=previous_text,
                next_text=next_text,
            )

            if not scene_file.exists() or scene_file.stat().st_size == 0:
                raise RuntimeError(f"Generated scene audio is missing or empty: {scene_file}")

    scene_files = collect_scene_audio_files(scenes_dir, scenes)

    build_final_audio_from_scenes(
        scene_files=scene_files,
        output_file=output_file,
        target_lufs=config["target_lufs"],
        true_peak=config["true_peak"],
        lra=config["lra"],
        bitrate=config["bitrate"],
    )

    if not output_file.exists() or output_file.stat().st_size == 0:
        raise RuntimeError(f"Final narration file is missing or empty: {output_file}")


def main():
    parser = argparse.ArgumentParser(description="Generate scene-based ElevenLabs narration audio from storyboard.md")

    parser.add_argument("directory", help="Directory containing storyboard.md")
    parser.add_argument("--reuse-scenes", action="store_true", help="Reuse existing scene mp3 files instead of regenerating them")
    parser.add_argument("--regen-scene", type=int, help="Regenerate only the selected 1-based scene number, then rebuild narration.mp3")

    args = parser.parse_args()

    if args.reuse_scenes and args.regen_scene is not None:
        raise RuntimeError("Use either --reuse-scenes or --regen-scene, not both")

    base_dir = Path(args.directory).expanduser().resolve()
    storyboard_path = base_dir / "storyboard.md"

    if not storyboard_path.exists():
        raise FileNotFoundError(f"Missing file: {storyboard_path}")

    md = storyboard_path.read_text(encoding="utf-8")
    meta, body = split_frontmatter(md)

    scenes = extract_scenes(body)
    narration = "\n\n".join(scene.text.strip() for scene in scenes).strip() + "\n"

    output_dir = base_dir / "generated" / "audio"
    output_dir.mkdir(parents=True, exist_ok=True)

    scenes_dir = output_dir / "scenes"
    txt_file = output_dir / "narration.txt"
    mp3_file = output_dir / "narration.mp3"

    txt_file.write_text(narration, encoding="utf-8")

    generate_scene_audio(
        scenes=scenes,
        meta=meta,
        output_file=mp3_file,
        scenes_dir=scenes_dir,
        reuse_scenes=args.reuse_scenes,
        regen_scene=args.regen_scene,
    )

    print(f"Generated text:    {txt_file}")
    print(f"Generated audio:   {mp3_file}")
    print(f"Generated scenes:  {scenes_dir}")


if __name__ == "__main__":
    main()
