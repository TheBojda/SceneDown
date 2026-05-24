# SceneDown

SceneDown is a lightweight Markdown-based pipeline for generating educational videos, documentary narrations, subtitles, and AI-powered explainer content from a single storyboard file.

Write your entire video in Markdown, define narration and rendering settings in YAML frontmatter, and generate fully narrated cinematic videos using AI voice synthesis and automatic alignment.

Perfect for:
- Educational videos
- Science documentaries
- YouTube explainer channels
- AI-generated courses
- Philosophy and technology content
- Automated video pipelines
- AI-assisted storytelling

---

# Features

- Markdown-based storyboard format
- Scene-oriented video scripting
- AI narration generation with ElevenLabs
- Automatic subtitle generation
- Scene-to-audio alignment using ElevenLabs Forced Alignment
- Cinematic image animations
- Smooth Ken Burns style zooms and pans
- Automatic video rendering with FFmpeg
- YAML metadata configuration
- Clean CLI workflow
- Scene-based architecture
- YouTube-ready video export
- Easy future extension for:
  - AI image generation
  - background music
  - multi-voice narration
  - automatic B-roll
  - animation pipelines

---

# Example Storyboard

```md
---
title: How Einstein’s Theory of Relativity Redefined Space and Time
author: Laszlo Fazekas (thebojda@gmail.com)
rights: Copyright © 2026 Laszlo Fazekas, All rights reserved

language: en

video:
  preset: youtube
  width: 1920
  height: 1080
  fps: 30
  subtitles: false

tts:
  provider: elevenlabs
  model_id: eleven_multilingual_v2
  voice_id: "CwhRBWXzGAHq8TQ4Fs17"

  style_prompt: >
    Calm, intelligent, documentary-style narration.
    Speak clearly and slightly dramatically,
    like a science documentary narrator.

  voice_settings:
    stability: 0.55
    similarity_boost: 0.8
    style: 0.25
    use_speaker_boost: true
    speed: 1.0
---

# Scene: Introduction

![timeline](assets/timeline.png){animation=slow-zoom}

To understand Special Relativity, we need to travel back to the 1800s.

At that time, science had two incredibly successful models describing the world.

The first was Newtonian mechanics, which explained how objects move.

The second was Maxwell’s set of equations, which described electromagnetic forces, including how light behaves.
```

---

# Supported Scene Animations

SceneDown supports cinematic image animations directly from Markdown:

```md
![image](assets/example.png){animation=slow-zoom}
![image](assets/example.png){animation=slow-pan-right}
![image](assets/example.png){animation=slow-pan-left}
![image](assets/example.png){animation=slow-pan-up}
![image](assets/example.png){animation=slow-pan-down}
```

---

# Installation

## Clone the repository

```bash
git clone https://github.com/yourusername/scenedown.git
cd scenedown
```

---

## Install Python dependencies

```bash
pip install requests pyyaml
```

---

## Install FFmpeg

Linux:

```bash
sudo apt install ffmpeg
```

macOS:

```bash
brew install ffmpeg
```

---

# Configuration

Create a `.env` file in the project root:

```env
ELEVENLABS_API_KEY=sk_your_api_key_here
```

Example `.gitignore`:

```gitignore
.env
generated/
```

---

# Usage

## Generate narration audio

```bash
./scenedown.sh narration examples/relativity
```

This generates:

```text
generated/audio/narration.txt
generated/audio/narration.mp3
```

---

## Generate subtitle and scene alignment

```bash
./scenedown.sh alignment examples/relativity
```

This generates:

```text
generated/alignment/elevenlabs_alignment.json
generated/alignment/words.json
generated/alignment/scenes.json
generated/subtitles/subtitles.srt
```

SceneDown uses ElevenLabs Forced Alignment to synchronize narration with scenes and subtitles.

---

## Render the final video

```bash
./scenedown.sh video examples/relativity
```

This generates:

```text
generated/video/video.mp4
```

The renderer automatically:
- synchronizes scenes to narration timing
- creates smooth cinematic image motion
- renders scene clips
- concatenates clips
- merges final narration audio

---

## Run the complete pipeline

```bash
./scenedown.sh all examples/relativity
```

This executes:
1. narration generation
2. subtitle/alignment generation
3. final video rendering

---

# Project Structure

```text
scenedown/
├── scenedown.sh
├── scenedown_narration.py
├── scenedown_alignment.py
├── scenedown_video.py
├── .env
├── examples/
│   └── relativity/
│       ├── storyboard.md
│       ├── assets/
│       └── generated/
│           ├── audio/
│           ├── alignment/
│           ├── subtitles/
│           └── video/
```

---

# Supported Metadata

```yaml
language: en

video:
  width: 1920
  height: 1080
  fps: 30
  subtitles: false

tts:
  provider: elevenlabs
  model_id: eleven_multilingual_v2
  voice_id: "CwhRBWXzGAHq8TQ4Fs17"

  style_prompt: >
    Calm documentary narration

  voice_settings:
    stability: 0.55
    similarity_boost: 0.8
    style: 0.25
    use_speaker_boost: true
    speed: 1.0
```

---

# Recommended ElevenLabs Voices

Good voices for educational and documentary-style narration:

- Adam
- Antoni
- Josh
- Rachel

Recommended cinematic documentary voice:

```yaml
voice_id: "CwhRBWXzGAHq8TQ4Fs17"
```

---

# Rendering Pipeline

SceneDown internally performs:

1. Markdown parsing
2. Narration extraction
3. AI voice generation
4. Forced alignment
5. Subtitle generation
6. Scene timing synchronization
7. Cinematic image animation rendering
8. Video concatenation
9. Audio/video muxing

---

# Why SceneDown?

Most AI video workflows are fragmented:
- one tool for scripting
- another for voice generation
- another for subtitles
- another for rendering
- another for animations

SceneDown unifies the entire educational video generation workflow around a single human-readable Markdown format.

Write once. Generate everything.

---

# Roadmap

Planned features:

- AI image generation
- Background music support
- Multi-voice conversations
- Automatic B-roll generation
- GPU rendering acceleration
- LLM-assisted storyboard generation
- Scene transitions
- YouTube metadata export
- Automatic thumbnail generation

---

# License

MIT License

---

# Keywords

AI video generation, markdown video generator, educational video pipeline, ElevenLabs narration, cinematic slideshow generator, documentary AI workflow, YouTube automation, AI explainer videos, markdown storyboard system, AI narration generator, text to speech video pipeline, automatic subtitle generation, FFmpeg video automation, cinematic AI video renderer

