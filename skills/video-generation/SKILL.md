---
name: video-generation
description: Use this skill when the user requests to generate, create, or imagine videos. Supports plain-text or structured prompts for guided generation.
---

# Video Generation Skill

## Overview

This skill submits async video generation jobs to ComfyUI through the Capybara Home generation API.
The execution path is:

1. Create prompt file (plain text or JSON) in `/mnt/user-data/workspace/`
2. Run `scripts/generate.py`
3. Script calls `/api/threads/{thread_id}/generation/jobs` with `kind=video`
4. Backend loads video workflow JSON and patches required fields before submitting to ComfyUI

Current workflow template location:
- `skills/public/video-generation/assets/text_to_video_wan.json`

## Core Capabilities

- Plain text or structured JSON prompt input
- Async job submission and completion tracking
- Stable WAN text-to-video workflow submission
- Optional reference image arguments (accepted but currently ignored by async pipeline)

## Execution Contract

### Step 1: Prepare Prompt File

Create prompt file under `/mnt/user-data/workspace/`.

- If the user gives a simple prompt, save it as plain text.
- If the user gives structured fields, JSON is allowed.
- Do not force JSON when plain text is enough.
- Always write prompt content in English.

### Step 2: Preflight Thread Context (Required)

`generate.py` must resolve `thread_id` before calling the API.
At least one of these must be true at runtime:

- `CAPYBARA_HOME_THREAD_ID` is set, or
- `THREAD_ID` is set, or
- `--output-file` path contains `/threads/<thread_id>/user-data/outputs/`

If none is true, submission fails with:
`Error: Could not detect thread_id from output path.`

In normal agent runs, tool runtime injects these env vars automatically.
Treat missing thread id as a hard error (do not use detached generation path).

### Step 3: Submit Job

Run:
```bash
python /mnt/skills/public/video-generation/scripts/generate.py \
  --prompt-file /mnt/user-data/workspace/prompt-file.txt \
  --reference-images /path/to/ref1.jpg \
  --output-file /mnt/user-data/outputs/generated-video.mp4 \
  --aspect-ratio 16:9
```

Parameters:

- `--prompt-file` (required): absolute path to prompt file
- `--reference-images` (optional): accepted for compatibility, currently ignored by async pipeline
- `--output-file` (required): absolute output hint path; basename becomes output name
- `--aspect-ratio` (optional): accepted by API but currently not used in video workflow patching

### Step 4: Report Result

- The script returns submission status including `job_id`, `prompt_id`, and expected output path.
- Final artifact is produced asynchronously by background poller.

## Exact Runtime Replacement Map (ComfyUI Workflow)

The backend patches these fields in `text_to_video_wan.json` before sending to ComfyUI:

- Nodes with `class_type == "CLIPTextEncode"` where `_meta.title` contains `positive`:
  - `inputs.text <- request.prompt`
- All nodes with `class_type == "SaveVideo"`:
  - `inputs.filename_prefix <- "capybara/{output_name}"`

Not patched by this async path:
- Negative prompt text node
- Video latent geometry/timing (`width`, `height`, `length`, `fps`)
- Sampler and model loader settings
- Reference image injections

Duration note:
- Current workflow template uses `length=33` and `fps=16` (about 2.1 seconds).
- A user request like "7 seconds" will not be enforced unless workflow timing nodes are changed.

[!IMPORTANT]
Truthfulness and traceability rules:
- Never claim specific tool calls, job IDs, file paths, or timings unless they were observed from tool output in the current turn.
- If asked "how it was created" and logs are unavailable, clearly label the explanation as "expected flow" rather than an execution trace.
- Avoid inventing backend internals.

## Video Generation Example

### Example A: Plain text prompt

Prompt file `/mnt/user-data/workspace/winter-fox.txt`:
```text
A fox moving quickly through a snowy forest valley, cinematic daylight, tracking camera, natural motion blur, realistic style.
```

Submit:
```bash
python /mnt/skills/public/video-generation/scripts/generate.py \
  --prompt-file /mnt/user-data/workspace/winter-fox.txt \
  --output-file /mnt/user-data/outputs/winter-fox-01.mp4 \
  --aspect-ratio 16:9
```

### Example B: Structured JSON prompt

Prompt file `/mnt/user-data/workspace/street-run.json`:

```json
{
  "subject": "A young cyclist weaving through neon-lit alleys at night",
  "camera": "Low-angle tracking shot, medium speed",
  "style": "Cinematic, realistic, soft volumetric fog",
  "motion": "Continuous forward movement with slight handheld feel",
  "lighting": "Neon signs reflecting on wet pavement"
}
```

Submit:
```bash
python /mnt/skills/public/video-generation/scripts/generate.py \
  --prompt-file /mnt/user-data/workspace/street-run.json \
  --reference-images /mnt/user-data/uploads/ref-frame.jpg \
  --output-file /mnt/user-data/outputs/street-run-01.mp4 \
  --aspect-ratio 16:9
```

## Output Handling

After submission:

- The script returns quickly with a `job_id`
- Background poller completes generation and copies the final file into `/mnt/user-data/outputs/capybara/`
- Completion appears in chat automatically with output path
- You can still iterate by submitting another job

Current behavior note:
- `--reference-images` is currently accepted by CLI for compatibility but not used by the async submission path.

## Notes

- Always use English for prompts regardless of user's language
- Plain text prompt files are supported; JSON is optional
- Reference-image arguments are currently not used by async submission path
- Iterative refinement is normal for optimal results
