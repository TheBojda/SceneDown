# SceneDown

SceneDown is a scene-based Markdown video generation pipeline for educational videos, documentaries, explainer content, and AI-assisted storytelling.

Write your entire video in Markdown, define narration and rendering settings in YAML frontmatter, and generate fully narrated cinematic videos from a single storyboard file.

## Features

- Markdown-based storyboard format
- Scene-oriented architecture
- Scene-by-scene narration generation
- AI narration generation with ElevenLabs
- Selective scene regeneration
- Automatic subtitle generation
- Scene-to-audio alignment using ElevenLabs Forced Alignment
- Cinematic image animations
- Ken Burns style zooms and pans
- Scene-level video rendering
- Automatic full video rendering
- YAML metadata configuration
- Clean CLI workflow
- YouTube-ready video export

---

## Installation

```bash
git clone https://github.com/yourusername/scenedown.git
cd scenedown
pip install requests pyyaml
```

Install FFmpeg:

```bash
sudo apt install ffmpeg
```

Create `.env`:

```env
ELEVENLABS_API_KEY=sk_your_api_key_here
```

---

## Example Storyboard

```yaml
tts:
  provider: elevenlabs
  model_id: eleven_multilingual_v2
  voice_id: "YOUR_VOICE_ID"

  seed: 42

  consistency:
    enabled: true
    stability: 0.8
    similarity_boost: 0.9
    style: 0.1
    use_speaker_boost: true

    context_chars: 3000
    context_scenes_before: 2
    context_scenes_after: 2
```

---

## Narration

Generate all scenes:

```bash
./scenedown.sh narration <project>
```

Reuse existing scene audio:

```bash
./scenedown.sh narration <project> --reuse-scenes
```

Regenerate a single scene:

```bash
./scenedown.sh narration <project> --regen-scene 7
```

Generated structure:

```text
generated/audio/
├── narration.txt
├── narration.mp3
└── scenes/
    ├── scene_001.mp3
    ├── scene_002.mp3
    └── ...
```

---

## Alignment

```bash
./scenedown.sh alignment <project>
```

Generated files:

```text
generated/alignment/
├── elevenlabs_alignment.json
├── words.json
└── scenes.json

generated/subtitles/
└── subtitles.srt
```

---

## Video Rendering

Render full video:

```bash
./scenedown.sh video <project>
```

Output:

```text
generated/video/video.mp4
```

### Render a Single Scene Video

```bash
./scenedown.sh video <project> --scene-video 7
```

Output:

```text
generated/video/scenes/scene_007.mp4
```

Uses:

```text
generated/audio/scenes/scene_007.mp3
```

### Silent Debug Scene

```bash
./scenedown.sh video <project> --scene 7
```

### Scene Video With Audio

```bash
./scenedown.sh video <project> --scene 7 --with-scene-audio
```

Equivalent to:

```bash
./scenedown.sh video <project> --scene-video 7
```

---

## Complete Pipeline

```bash
./scenedown.sh all <project>
```

Runs:

1. Narration generation
2. Alignment generation
3. Subtitle generation
4. Final video rendering

---

## Recommended Model

For best narrator consistency:

```yaml
model_id: eleven_multilingual_v2
```

`eleven_v3` currently does not support scene context passing.

---

## License

MIT License
