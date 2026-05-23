import os
import re
from pathlib import Path
from typing import Optional

import requests

DEFAULT_GATEWAY_BASE_URL = os.getenv("CAPYBARA_HOME_GATEWAY_BASE_URL", "http://127.0.0.1:8001")
THREAD_ID_ENV_KEYS = ("CAPYBARA_HOME_THREAD_ID", "THREAD_ID")


def _detect_thread_id(output_file: str) -> Optional[str]:
    for key in THREAD_ID_ENV_KEYS:
        value = os.getenv(key)
        if value:
            return value

    normalized = output_file.replace("\\", "/")
    match = re.search(r"/threads/([^/]+)/user-data/outputs/", normalized)
    if match:
        return match.group(1)
    return None


def generate_video(
    prompt_file: str,
    reference_images: list[str],
    output_file: str,
    aspect_ratio: str = "16:9",
) -> str:
    ignored_ref_count = len(reference_images)

    prompt_text = Path(prompt_file).read_text(encoding="utf-8").strip()
    output_name = Path(output_file).stem
    thread_id = _detect_thread_id(output_file)
    if not thread_id:
        return (
            "Error: Could not detect thread_id from output path. "
            "This script requires thread-bound execution. "
            "Ensure CAPYBARA_HOME_THREAD_ID/THREAD_ID is present in runtime context."
        )

    endpoint = f"{DEFAULT_GATEWAY_BASE_URL.rstrip('/')}/api/threads/{thread_id}/generation/jobs"
    response = requests.post(
        endpoint,
        json={
            "kind": "video",
            "prompt": prompt_text,
            "output_name": output_name,
            "aspect_ratio": aspect_ratio,
        },
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    job = payload.get("job", {})
    job_id = job.get("id")
    prompt_id = job.get("prompt_id")
    expected_path = job.get("expected_virtual_path")

    message = (
        "Video generation submitted successfully. "
        f"job_id={job_id}, prompt_id={prompt_id}, expected_output={expected_path}. "
        "A background poller will complete this job and publish completion in chat."
    )
    if ignored_ref_count:
        message += f" Note: {ignored_ref_count} reference image(s) were provided but are currently ignored by this async submission path."
    return message


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Submit async video generation job to ComfyUI backend")
    parser.add_argument(
        "--prompt-file",
        required=True,
        help="Absolute path to prompt text/JSON file",
    )
    parser.add_argument(
        "--reference-images",
        nargs="*",
        default=[],
        help="Absolute paths to reference images (currently unused by async workflow)",
    )
    parser.add_argument(
        "--output-file",
        required=True,
        help="Output file name hint (basename is used for capyhome/{name})",
    )
    parser.add_argument(
        "--aspect-ratio",
        required=False,
        default="16:9",
        help="Aspect ratio placeholder (currently unused by video workflow)",
    )

    args = parser.parse_args()

    try:
        print(
            generate_video(
                args.prompt_file,
                args.reference_images,
                args.output_file,
                args.aspect_ratio,
            )
        )
    except Exception as e:
        print(f"Error while submitting video generation: {e}")
