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



def has_audio_stream(file: Path) -> bool:
    result = subprocess.run([
        "ffprobe", "-v", "error",
        "-select_streams", "a",
        "-show_entries", "stream=index",
        "-of", "csv=p=0",
        str(file),
    ], capture_output=True, text=True, check=True)
    return bool(result.stdout.strip())


def assert_audio_stream(file: Path):
    if not has_audio_stream(file):
        raise RuntimeError(f"Generated file has no audio stream: {file}")

def scene_audio_file(base_dir: Path, scene_number: int) -> Path:
    return base_dir / "generated" / "audio" / "scenes" / f"scene_{scene_number:03d}.mp3"


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


def build_fade_video(clip_files, clip_durations, scenes, output_file, fps):
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

    fade_duration = 1.0

    inputs = []
    for f in clip_files:
        inputs.extend(["-i", str(f)])

    filter_parts = []

    for i in range(len(clip_files)):
        filter_parts.append(f"[{i}:v]setpts=PTS-STARTPTS[v{i}]")

    previous_stream = "[v0]"
    current_duration = clip_durations[0]

    for i in range(1, len(clip_files)):
        previous_scene = scenes[i - 1]
        transition = previous_scene.get("transition", "fade")

        if transition == "cut":
            filter_parts.append(
                f"{previous_stream}[v{i}]concat=n=2:v=1:a=0[out{i}]"
            )
            current_duration += clip_durations[i]
        else:
            offset = max(0, current_duration - fade_duration)

            filter_parts.append(
                f"{previous_stream}[v{i}]"
                f"xfade=transition=fade:"
                f"duration={fade_duration}:"
                f"offset={offset}"
                f"[out{i}]"
            )

            current_duration += clip_durations[i] - fade_duration

        previous_stream = f"[out{i}]"

    filter_script = ";".join(filter_parts)

    cmd = ["ffmpeg", "-y"] + inputs + [
        "-filter_complex", filter_script,
        "-map", previous_stream,
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
        help="Render only a single scene number, 1-based. By default this creates a silent debug clip."
    )
    parser.add_argument(
        "--with-scene-audio",
        action="store_true",
        help="When used with --scene, attach generated/audio/scenes/scene_XXX.mp3 and output a standalone scene video."
    )
    parser.add_argument(
        "--scene-video",
        type=int,
        help="Render one scene as a standalone video with its scene audio. Equivalent to --scene N --with-scene-audio."
    )
    parser.add_argument(
        "--reuse-clips",
        action="store_true",
        help="Reuse already generated clips and skip clip rendering."
    )

    args = parser.parse_args()

    if args.scene_video is not None:
        if args.scene is not None and args.scene != args.scene_video:
            raise RuntimeError("Use either --scene or --scene-video, not both with different values")
        args.scene = args.scene_video
        args.with_scene_audio = True

    base_dir = Path(args.directory).resolve()

    storyboard_file = base_dir / "storyboard.md"
    audio_file = base_dir / "generated" / "audio" / "narration.mp3"
    scenes_file = base_dir / "generated" / "alignment" / "scenes.json"

    md = storyboard_file.read_text(encoding="utf-8")
    meta, body = split_frontmatter(md)

    storyboard_scenes = parse_scene_images(body)

    aligned_scenes = None
    full_audio_duration = None

    if not (args.scene is not None and args.with_scene_audio):
        aligned_scenes = json.loads(scenes_file.read_text(encoding="utf-8"))

        if len(storyboard_scenes) != len(aligned_scenes):
            raise RuntimeError(
                f"Scene count mismatch: storyboard has {len(storyboard_scenes)}, "
                f"alignment has {len(aligned_scenes)}"
            )

        full_audio_duration = ffprobe_duration(audio_file)

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

    output_dir = base_dir / "generated" / "video"
    clips_dir = output_dir / "clips"
    output_dir.mkdir(parents=True, exist_ok=True)
    clips_dir.mkdir(parents=True, exist_ok=True)

    clip_files = []
    clip_durations = []
    selected_scenes = []

    fade_duration = 1.0

    for i, scene in enumerate(storyboard_scenes):
        scene_number = i + 1

        if args.scene is not None and scene_number != args.scene:
            continue

        if not scene.get("image"):
            raise RuntimeError(f"Scene {scene_number} has no image")

        image_file = base_dir / scene["image"]

        if not image_file.exists():
            raise FileNotFoundError(image_file)

        if args.scene is not None and args.with_scene_audio:
            scene_audio = scene_audio_file(base_dir, scene_number)
            if not scene_audio.exists():
                raise FileNotFoundError(
                    f"Missing scene audio: {scene_audio}\n"
                    f"Generate it first with the narration script."
                )
            real_duration = max(0.1, ffprobe_duration(scene_audio))
        else:
            start = float(aligned_scenes[i]["start"])

            if i + 1 < len(aligned_scenes):
                end = float(aligned_scenes[i + 1]["start"])
            else:
                end = full_audio_duration

            real_duration = max(0.1, end - start)

        transition = scene.get("transition", "fade")
        is_last_scene = i == len(storyboard_scenes) - 1

        render_duration = real_duration

        if transition != "cut" and not is_last_scene and not (args.scene is not None and args.with_scene_audio):
            render_duration += fade_duration

        clip_durations.append(render_duration)
        selected_scenes.append(scene)

        frames = math.ceil(render_duration * fps)

        if args.scene is not None:
            clip_file = clips_dir / f"scene_debug_{scene_number:03}.mp4"
        else:
            clip_file = clips_dir / f"scene_{scene_number:03}.mp4"

        clip_files.append(clip_file)

        if args.reuse_clips and clip_file.exists():
            print(f"Reusing existing clip: {clip_file}")
        else:
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
                "-t", str(render_duration),
                "-r", str(fps),
                "-an",
                "-c:v", "libx264",
                "-preset", "slow",
                "-crf", "18",
                "-pix_fmt", "yuv420p",
                str(clip_file),
            ])

        print(
            f"Scene {scene_number:03}: "
            f"real={real_duration:.2f}s "
            f"render={render_duration:.2f}s "
            f"transition={transition}"
        )

    if not clip_files:
        raise RuntimeError("No clips were generated")

    if args.scene is not None:
        if args.with_scene_audio:
            scenes_output_dir = output_dir / "scenes"
            scenes_output_dir.mkdir(parents=True, exist_ok=True)

            scene_audio = scene_audio_file(base_dir, args.scene)
            final_video = scenes_output_dir / f"scene_{args.scene:03}.mp4"

            if not has_audio_stream(scene_audio):
                raise RuntimeError(f"Scene audio file has no audio stream: {scene_audio}")

            run([
                "ffmpeg", "-y",
                "-i", str(clip_files[0]),
                "-i", str(scene_audio),
                "-map", "0:v:0",
                "-map", "1:a:0",
                "-c:v", "copy",
                "-c:a", "aac",
                "-b:a", "192k",
                "-movflags", "+faststart",
                "-shortest",
                str(final_video),
            ])

            assert_audio_stream(final_video)
            final_duration = ffprobe_duration(final_video)

            print(f"Generated scene video: {final_video}")
            print(f"Scene number: {args.scene}")
            print(f"Scene audio:  {scene_audio}")
            print(f"Scene duration: {final_duration:.2f}s")
            return

        final_video = output_dir / f"scene_debug_{args.scene:03}.mp4"

        run([
            "ffmpeg", "-y",
            "-i", str(clip_files[0]),
            "-c", "copy",
            str(final_video),
        ])

        print(f"Generated debug scene video: {final_video}")
        print(f"Scene number: {args.scene}")
        print(f"Scene duration: {clip_durations[0]:.2f}s")
        return

    silent_video = output_dir / "video_silent.mp4"
    final_video = output_dir / "video.mp4"

    build_fade_video(
        clip_files=clip_files,
        clip_durations=clip_durations,
        scenes=selected_scenes,
        output_file=silent_video,
        fps=fps,
    )

    if not has_audio_stream(audio_file):
        raise RuntimeError(f"Narration audio file has no audio stream: {audio_file}")

    run([
        "ffmpeg", "-y",
        "-i", str(silent_video),
        "-i", str(audio_file),
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "+faststart",
        "-shortest",
        str(final_video),
    ])

    assert_audio_stream(final_video)
    silent_duration = ffprobe_duration(silent_video)
    final_duration = ffprobe_duration(final_video)

    print(f"Generated video: {final_video}")
    print(f"Audio duration:  {full_audio_duration:.2f}s")
    print(f"Silent duration: {silent_duration:.2f}s")
    print(f"Final duration:  {final_duration:.2f}s")


if __name__ == "__main__":
    main()