#!/usr/bin/env python3

import argparse
import json
import math
import re
import subprocess
from pathlib import Path

import yaml


def run(cmd):
    print(" ".join(str(c) for c in cmd))
    subprocess.run(cmd, check=True)


def ffprobe_duration(file: Path) -> float:
    result = subprocess.check_output([
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(file)
    ])
    return float(result.decode().strip())


def split_frontmatter(md: str):
    if md.startswith("---"):
        parts = md.split("---", 2)
        if len(parts) >= 3:
            return yaml.safe_load(parts[1]) or {}, parts[2].strip()
    return {}, md.strip()


def parse_scene_images(md_body: str):
    scenes = []
    current = None

    for raw in md_body.splitlines():
        line = raw.strip()

        if line.startswith("# Scene:"):
            current = {
                "title": line.replace("# Scene:", "").strip(),
                "image": None,
                "animation": "slow-zoom",
                "transition": "fade",
            }
            scenes.append(current)
            continue

        if current and line.startswith("!["):
            m = re.search(r"!\[.*?\]\((.*?)\)(?:\{(.*?)\})?", line)
            if m:
                current["image"] = m.group(1)

                attrs = m.group(2) or ""
                for key, value in re.findall(r"(\w+)=([\w-]+)", attrs):
                    current[key] = value

    return scenes


def image_filter(animation, width, height, fps, frames):
    frames = max(frames, 1)
    duration = frames / fps
    den = max(frames - 1, 1)

    work_scale = 4
    W = width * work_scale
    H = height * work_scale

    if animation == "slow-zoom":
        zoom_amount = 0.04

        return (
            f"scale={W}:{H}:force_original_aspect_ratio=increase,"
            f"crop={W}:{H},"
            f"zoompan="
            f"z='1+{zoom_amount}*on/{den}':"
            f"x='iw/2-(iw/zoom/2)':"
            f"y='ih/2-(ih/zoom/2)':"
            f"d={frames}:"
            f"s={W}x{H}:"
            f"fps={fps},"
            f"scale={width}:{height}:flags=lanczos,"
            f"trim=duration={duration},"
            f"setpts=PTS-STARTPTS,"
            f"format=yuv420p"
        )

    zoom = 1.02
    sw = int(W * zoom)
    sh = int(H * zoom)

    t = f"n/{den}"

    if animation == "slow-pan-right":
        x = f"floor(({sw}-{W})*{t})"
        y = f"floor(({sh}-{H})/2)"

    elif animation == "slow-pan-left":
        x = f"floor(({sw}-{W})*(1-{t}))"
        y = f"floor(({sh}-{H})/2)"

    elif animation == "slow-pan-up":
        x = f"floor(({sw}-{W})/2)"
        y = f"floor(({sh}-{H})*(1-{t}))"

    elif animation == "slow-pan-down":
        x = f"floor(({sw}-{W})/2)"
        y = f"floor(({sh}-{H})*{t})"

    else:
        x = f"floor(({sw}-{W})/2)"
        y = f"floor(({sh}-{H})/2)"

    return (
        f"fps={fps},"
        f"scale={sw}:{sh}:force_original_aspect_ratio=increase,"
        f"crop={W}:{H}:x='{x}':y='{y}',"
        f"scale={width}:{height}:flags=lanczos,"
        f"trim=duration={duration},"
        f"setpts=PTS-STARTPTS,"
        f"format=yuv420p"
    )


def build_fade_video(clip_files, scene_durations, scenes, output_file, fps):
    if not clip_files:
        return

    if len(clip_files) == 1:
        run([
            "ffmpeg", "-y",
            "-i", str(clip_files[0]),
            "-c", "copy",
            str(output_file)
        ])
        return

    filter_parts = []
    inputs = []

    for f in clip_files:
        inputs.extend(["-i", str(f)])

    previous_stream = "[0:v]"
    current_timeline_end = scene_durations[0]

    for i in range(1, len(clip_files)):
        prev_scene = scenes[i - 1]
        transition = prev_scene.get("transition", "fade")

        if transition == "cut":
            filter_parts.append(
                f"{previous_stream}[{i}:v]concat=n=2:v=1:a=0[v{i}]"
            )
            current_timeline_end += scene_durations[i]
        else:
            offset = current_timeline_end
            filter_parts.append(
                f"{previous_stream}[{i}:v]"
                f"xfade=transition=fade:"
                f"duration=1.0:"
                f"offset={offset}"
                f"[v{i}]"
            )
            current_timeline_end += scene_durations[i]

        previous_stream = f"[v{i}]"

    filter_script = ";".join(filter_parts)

    cmd = ["ffmpeg", "-y"] + inputs + [
        "-filter_complex", filter_script,
        "-map", f"[v{len(clip_files) - 1}]",
        "-r", str(fps),
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        str(output_file)
    ]

    run(cmd)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directory")
    parser.add_argument(
        "--scene",
        type=int,
        help="Render only a single scene number, 1-based. Useful for debugging."
    )

    args = parser.parse_args()

    base_dir = Path(args.directory).resolve()

    storyboard_file = base_dir / "storyboard.md"
    audio_file = base_dir / "generated" / "audio" / "narration.mp3"
    scenes_file = base_dir / "generated" / "alignment" / "scenes.json"

    md = storyboard_file.read_text(encoding="utf-8")
    meta, body = split_frontmatter(md)

    storyboard_scenes = parse_scene_images(body)
    aligned_scenes = json.loads(scenes_file.read_text(encoding="utf-8"))

    if len(storyboard_scenes) != len(aligned_scenes):
        raise RuntimeError(
            f"Scene count mismatch: storyboard has {len(storyboard_scenes)}, "
            f"alignment has {len(aligned_scenes)}"
        )

    if args.scene is not None:
        if args.scene < 1 or args.scene > len(storyboard_scenes):
            raise RuntimeError(
                f"Invalid scene number: {args.scene}. "
                f"Valid range: 1..{len(storyboard_scenes)}"
            )

    video_meta = meta.get("video", {})
    width = int(video_meta.get("width", 1920))
    height = int(video_meta.get("height", 1080))
    fps = int(video_meta.get("fps", 30))

    audio_duration = ffprobe_duration(audio_file)

    output_dir = base_dir / "generated" / "video"
    clips_dir = output_dir / "clips"
    output_dir.mkdir(parents=True, exist_ok=True)
    clips_dir.mkdir(parents=True, exist_ok=True)

    clip_files = []
    scene_durations = []
    selected_scenes = []

    for i, scene in enumerate(storyboard_scenes):
        scene_number = i + 1

        if args.scene is not None and scene_number != args.scene:
            continue

        if not scene.get("image"):
            raise RuntimeError(f"Scene {scene_number} has no image")

        image_file = base_dir / scene["image"]

        if not image_file.exists():
            raise FileNotFoundError(image_file)

        start = float(aligned_scenes[i]["start"])

        if i + 1 < len(aligned_scenes):
            end = float(aligned_scenes[i + 1]["start"])
        else:
            end = audio_duration

        duration = max(0.1, end - start)
        scene_durations.append(duration)
        selected_scenes.append(scene)

        frames = math.ceil(duration * fps)

        if args.scene is not None:
            clip_file = clips_dir / f"scene_debug_{scene_number:03}.mp4"
        else:
            clip_file = clips_dir / f"scene_{scene_number:03}.mp4"

        clip_files.append(clip_file)

        vf = image_filter(
            scene.get("animation", "slow-zoom"),
            width,
            height,
            fps,
            frames,
        )

        run([
            "ffmpeg", "-y",
            "-loop", "1",
            "-i", str(image_file),
            "-vf", vf,
            "-t", str(duration),
            "-r", str(fps),
            "-an",
            "-c:v", "libx264",
            "-preset", "slow",
            "-crf", "18",
            "-pix_fmt", "yuv420p",
            str(clip_file),
        ])

    if not clip_files:
        raise RuntimeError("No clips were generated")

    if args.scene is not None:
        final_video = output_dir / f"scene_debug_{args.scene:03}.mp4"

        run([
            "ffmpeg", "-y",
            "-i", str(clip_files[0]),
            "-c", "copy",
            str(final_video),
        ])

        print(f"Generated debug scene video: {final_video}")
        print(f"Scene number: {args.scene}")
        print(f"Scene duration: {scene_durations[0]:.2f}s")
        return

    silent_video = output_dir / "video_silent.mp4"
    final_video = output_dir / "video.mp4"

    build_fade_video(
        clip_files=clip_files,
        scene_durations=scene_durations,
        scenes=selected_scenes,
        output_file=silent_video,
        fps=fps,
    )

    run([
        "ffmpeg", "-y",
        "-i", str(silent_video),
        "-i", str(audio_file),
        "-c:v", "copy",
        "-c:a", "aac",
        "-shortest",
        str(final_video),
    ])

    print(f"Generated video: {final_video}")
    print(f"Audio duration:  {audio_duration:.2f}s")


if __name__ == "__main__":
    main()