"""Configuration for report quality gate in work mode."""

from pydantic import BaseModel, Field


class QualityGateConfig(BaseModel):
    enabled: bool = Field(default=True, description="Enable report artifact quality gate before successful write_file completion.")
    max_repair_passes: int = Field(default=3, ge=0, le=5, description="Maximum focused repair passes before allowing write to proceed.")
    block_on_failure: bool = Field(
        default=False,
        description="If true, block write_file on quality-gate failures; if false, fail-forward with warnings.",
    )
    blocking_path_patterns: list[str] = Field(
        default_factory=list,
        description="Optional path substrings that always block on quality-gate failure.",
    )


_quality_gate_config: QualityGateConfig = QualityGateConfig()


def get_quality_gate_config() -> QualityGateConfig:
    return _quality_gate_config


def set_quality_gate_config(config: QualityGateConfig) -> None:
    global _quality_gate_config
    _quality_gate_config = config


def load_quality_gate_config_from_dict(config_dict: dict) -> None:
    global _quality_gate_config
    _quality_gate_config = QualityGateConfig(**config_dict)
