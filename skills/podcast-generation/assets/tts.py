import os
import subprocess
from pathlib import Path
from typing import Optional

# Auto-accept Coqui TTS non-commercial license agreement (only relevant if XTTS is enabled).
os.environ.setdefault("COQUI_TOS_AGREED", "1")
# Allow CPU fallback for unsupported MPS ops (prevents hard failures on Apple Silicon).
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")


def _get_xtts_speaker_wav() -> str | None:
    # Prefer explicit env var so this skill doesn't depend on the app's settings module.
    speaker = os.getenv("XTTS_SPEAKER_WAV")
    if speaker:
        return speaker

    # Skill-local default: assets/max_verstappen_final.wav (if present).
    default_path = (Path(__file__).resolve().parent / "max_verstappen_final.wav")
    if default_path.exists():
        return str(default_path)

    # Best-effort fallback for when this runs inside the full CapyHome app environment.
    try:
        from backend.config.config import settings  # type: ignore

        return getattr(settings, "XTTS_SPEAKER_WAV", None)
    except Exception:
        return None


class NativeSayService:
    def __init__(self, voice: str):
        self.voice = voice

    def generate(self, text: str, output_path: str) -> bool:
        cmd = ["say", "-v", self.voice, "-o", output_path, "--data-format=LEI16@44100", text]
        result = subprocess.run(cmd, capture_output=True, text=True)
        return result.returncode == 0


class XTTSv2Service:
    def __init__(self, *, speaker_wav: str, language: str):
        self.device = "cpu"
        self.tts = None
        self.speaker_wav = speaker_wav
        self.language = language
        self._init_model()

    def _init_model(self) -> None:
        try:
            import torch
            from TTS.api import TTS
            from TTS.config.shared_configs import BaseAudioConfig, BaseDatasetConfig, BaseTrainingConfig
            from TTS.tts.configs.xtts_config import XttsConfig
            from TTS.tts.models.xtts import XttsAudioConfig

            # Register safe globals for PyTorch 2.4+ safe loading
            if hasattr(torch.serialization, "add_safe_globals"):
                torch.serialization.add_safe_globals(
                    [XttsConfig, XttsAudioConfig, BaseDatasetConfig, BaseAudioConfig, BaseTrainingConfig]
                )

            self.tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to(self.device)
        except Exception:
            self.tts = None

    def generate(self, text: str, output_path: str) -> bool:
        if not self.tts:
            return False
        if not self.speaker_wav or not os.path.exists(self.speaker_wav):
            return False
        try:
            self.tts.tts_to_file(
                text=text,
                speaker_wav=self.speaker_wav,
                language=self.language,
                file_path=output_path,
            )
            return os.path.exists(output_path)
        except Exception:
            return False


class TTSService:
    def __init__(self, *, say_voice: str):
        self.say_service = NativeSayService(voice=say_voice)
        self.xtts_service: XTTSv2Service | None = None
        self.xtts_speaker_wav = _get_xtts_speaker_wav()
        self.xtts_language = os.getenv("XTTS_LANGUAGE", "en")

    def _get_xtts(self) -> XTTSv2Service | None:
        if not self.xtts_speaker_wav or not os.path.exists(self.xtts_speaker_wav):
            return None
        if self.xtts_service is None:
            self.xtts_service = XTTSv2Service(speaker_wav=self.xtts_speaker_wav, language=self.xtts_language)
        return self.xtts_service

    def generate_audio(self, text: str, output_path: str) -> Optional[str]:
        output_dir = os.path.dirname(output_path)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)

        xtts = self._get_xtts()
        if xtts and xtts.generate(text, output_path):
            return output_path

        if self.say_service.generate(text, output_path) and os.path.exists(output_path):
            return output_path
        return None
