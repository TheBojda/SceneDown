# SceneDown

SceneDown is a lightweight markdown-based pipeline for generating educational videos, documentary narrations, and AI-powered explainer content from a single storyboard file.

Write your video in Markdown, define narration and rendering metadata in YAML frontmatter, and generate professional AI voice narration using ElevenLabs.

Perfect for:
- Educational videos
- Science documentaries
- YouTube explainer channels
- AI-generated courses
- Philosophy and technology content
- Automated video pipelines

---

# Features

- Markdown-based storyboard format
- Scene-oriented video scripting
- AI narration generation
- ElevenLabs TTS integration
- YAML metadata configuration
- Automatic narration text extraction
- Clean project structure
- CLI workflow
- Easy future extension for:
  - subtitles
  - image generation
  - video rendering
  - alignment
  - animation pipelines

---

# Example Storyboard

```md
---
title: How Einstein’s Theory of Relativity Redefined Space and Time

tts:
  provider: elevenlabs
  model_id: eleven_multilingual_v2

  voice_id: "TxGEqnHWrfWFTfGW9XjX"

  voice_settings:
    stability: 0.45
    similarity_boost: 0.8
    style: 0.25
    use_speaker_boost: true
    speed: 0.96
---

# Scene: Introduction

![timeline](assets/timeline.png)

To understand Special Relativity, we need to travel back to the 1800s.
```

---

# Installation

## Clone the repository

```bash
git clone https://github.com/yourusername/scenedown.git
cd scenedown
```

## Install Python dependencies

```bash
pip install requests pyyaml
```

---

# Configuration

Create a `.env` file in the project root:

```env
ELEVENLABS_API_KEY=sk_your_api_key_here
```

Add `.env` to `.gitignore`:

```gitignore
.env
```

---

# Usage

Generate narration and audio from a storyboard:

```bash
./scenedown.sh narration examples/relativity
```

This will:

1. Read:

```text
examples/relativity/storyboard.md
```

2. Extract narration text

3. Generate:

```text
examples/relativity/generated/audio/narration.txt
examples/relativity/generated/audio/narration.mp3
```

---

# Project Structure

```text
scenedown/
├── scenedown.sh
├── scenedown_narration.py
├── .env
├── examples/
│   └── relativity/
│       ├── storyboard.md
│       ├── assets/
│       └── generated/
│           └── audio/
```

---

# Supported Metadata

```yaml
tts:
  provider: elevenlabs
  model_id: eleven_multilingual_v2

  voice_id: "TxGEqnHWrfWFTfGW9XjX"

  voice_settings:
    stability: 0.45
    similarity_boost: 0.8
    style: 0.25
    use_speaker_boost: true
    speed: 0.96
```

---

# Recommended Voices

Good free voices for educational videos in ElevenLabs:

- Josh
- Adam
- Antoni
- Rachel

Recommended for documentary-style narration:

```yaml
voice_id: "TxGEqnHWrfWFTfGW9XjX"
```

---

# Roadmap

Planned features:

- Subtitle generation
- WhisperX alignment
- AI image generation
- Video rendering
- Scene animations
- Multi-voice conversations
- Background music
- YouTube export pipeline

---

# Why SceneDown?

Most AI video workflows are fragmented:
- one tool for scripting
- another for voice
- another for subtitles
- another for rendering

SceneDown aims to unify the entire educational video generation pipeline around a single human-readable markdown format.

---

# License

MIT License

---

# Keywords

AI video generation, markdown video generator, educational video pipeline, ElevenLabs narration, documentary AI workflow, YouTube automation, AI explainer videos, markdown storyboard system, AI narration generator, text to speech video pipeline

