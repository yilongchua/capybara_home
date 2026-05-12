"""Configuration for report quality gate in work mode."""

from pydantic import BaseModel, Field


class QualityGateConfig(BaseModel):
    enabled: bool = Field(default=True, description="Enable report artifact quality gate before successful write_file completion.")
    max_repair_passes: int = Field(default=1, ge=0, le=3, description="Maximum focused repair passes before allowing write to proceed.")


_quality_gate_config: QualityGateConfig = QualityGateConfig()


def get_quality_gate_config() -> QualityGateConfig:
    return _quality_gate_config


def set_quality_gate_config(config: QualityGateConfig) -> None:
    global _quality_gate_config
    _quality_gate_config = config


def load_quality_gate_config_from_dict(config_dict: dict) -> None:
    global _quality_gate_config
    _quality_gate_config = QualityGateConfig(**config_dict)
