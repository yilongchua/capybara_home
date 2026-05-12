import argparse
import json
import logging
import os
import shutil
import subprocess
import tempfile
from typing import Literal, Optional

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from assets.tts import TTSService


# Types
class ScriptLine:
    def __init__(self, speaker: Literal["male", "female"] = "male", paragraph: str = ""):
        self.speaker = speaker
        self.paragraph = paragraph


class Script:
    def __init__(self, locale: Literal["en", "zh"] = "en", lines: Optional[list[ScriptLine]] = None):
        self.locale = locale
        self.lines = lines or []

    @classmethod
    def from_dict(cls, data: dict) -> "Script":
        script = cls(locale=data.get("locale", "en"))
        for line in data.get("lines", []):
            script.lines.append(
                ScriptLine(
                    speaker=line.get("speaker", "male"),
                    paragraph=line.get("paragraph", ""),
                )
            )
        return script


def _have_cmd(name: str) -> bool:
    return shutil.which(name) is not None


def _run(cmd: list[str]) -> None:
    logger.debug("Running: %s", " ".join(cmd))
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def _get_voice(speaker: Literal["male", "female"]) -> str:
    # Defaults chosen for macOS; users can override via env.
    if speaker == "male":
        return os.getenv("PODCAST_TTS_VOICE_MALE", "Alex")
    return os.getenv("PODCAST_TTS_VOICE_FEMALE", "Samantha")


def _render_segments(script: Script, segments_dir: str) -> list[str]:
    segment_paths: list[str] = []
    total = len(script.lines)
    tts_by_speaker: dict[str, TTSService] = {
        "male": TTSService(say_voice=_get_voice("male")),
        "female": TTSService(say_voice=_get_voice("female")),
    }
    for i, line in enumerate(script.lines):
        voice = _get_voice(line.speaker)
        logger.info("TTS %d/%d (%s, voice=%s)", i + 1, total, line.speaker, voice)
        seg_path = os.path.join(segments_dir, f"segment_{i:04d}_{line.speaker}.wav")
        service = tts_by_speaker.get(line.speaker)
        if not service:
            raise RuntimeError(f"Unknown speaker: {line.speaker}")
        out = service.generate_audio(line.paragraph, seg_path)
        if not out:
            raise RuntimeError(f"Failed to generate audio for line {i + 1}/{total}")
        segment_paths.append(seg_path)
    return segment_paths


def _concat_to_audio(segment_paths: list[str], output_file: str) -> None:
    if not segment_paths:
        raise ValueError("No segments to concatenate")
    if not _have_cmd("ffmpeg"):
        raise RuntimeError("Missing `ffmpeg`. Install ffmpeg to stitch TTS segments into the final audio file.")

    output_dir = os.path.dirname(output_file)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    tmpdir = os.path.dirname(segment_paths[0])
    list_path = os.path.join(tmpdir, "concat_list.txt")
    with open(list_path, "w", encoding="utf-8") as f:
        for p in segment_paths:
            # concat demuxer requires this exact format
            escaped = p.replace("'", "'\\''")
            f.write(f"file '{escaped}'\n")

    # Re-encode to match the requested output container/codec. Default skill output is mp3.
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        list_path,
        "-c:a",
        "libmp3lame",
        "-q:a",
        "3",
        output_file,
    ]
    _run(cmd)
    if not os.path.exists(output_file):
        raise RuntimeError(f"ffmpeg failed to produce output: {output_file}")


def generate_markdown(script: Script, title: str = "Podcast Script") -> str:
    """Generate a markdown script from the podcast script."""
    lines = [f"# {title}", ""]

    for line in script.lines:
        speaker_name = "**Host (Male)**" if line.speaker == "male" else "**Host (Female)**"
        lines.append(f"{speaker_name}: {line.paragraph}")
        lines.append("")

    return "\n".join(lines)


def generate_podcast(
    script_file: str,
    output_file: str,
    transcript_file: Optional[str] = None,
) -> str:
    """Generate a podcast from a script JSON file."""

    # Read script JSON
    with open(script_file, "r", encoding="utf-8") as f:
        script_json = json.load(f)

    if "lines" not in script_json:
        raise ValueError(f"Invalid script format: missing 'lines' key. Got keys: {list(script_json.keys())}")

    script = Script.from_dict(script_json)
    logger.info(f"Loaded script with {len(script.lines)} lines")

    # Generate transcript markdown if requested
    if transcript_file:
        title = script_json.get("title", "Podcast Script")
        markdown_content = generate_markdown(script, title)
        transcript_dir = os.path.dirname(transcript_file)
        if transcript_dir:
            os.makedirs(transcript_dir, exist_ok=True)
        with open(transcript_file, "w", encoding="utf-8") as f:
            f.write(markdown_content)
        logger.info(f"Generated transcript to {transcript_file}")

    # Convert to audio
    with tempfile.TemporaryDirectory(prefix="podcast_tts_") as tmpdir:
        segment_paths = _render_segments(script, segments_dir=tmpdir)
        _concat_to_audio(segment_paths, output_file=output_file)

    result = f"Successfully generated podcast to {output_file}"
    if transcript_file:
        result += f" and transcript to {transcript_file}"
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate podcast from script JSON file")
    parser.add_argument(
        "--script-file",
        required=True,
        help="Absolute path to script JSON file",
    )
    parser.add_argument(
        "--output-file",
        required=True,
        help="Output path for generated podcast MP3",
    )
    parser.add_argument(
        "--transcript-file",
        required=False,
        help="Output path for transcript markdown file (optional)",
    )

    args = parser.parse_args()

    try:
        result = generate_podcast(
            args.script_file,
            args.output_file,
            args.transcript_file,
        )
        print(result)
    except Exception as e:
        import traceback
        print(f"Error generating podcast: {e}")
        traceback.print_exc()
