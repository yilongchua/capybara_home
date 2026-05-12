"""Configuration for skill auto-curation."""

from pydantic import BaseModel, Field


class SkillCurationConfig(BaseModel):
    """Skill curation job configuration."""

    enabled: bool = Field(default=False, description="Enable skill curation proposal generation.")
    proposal_only: bool = Field(default=True, description="Keep generated skills as disabled proposals.")
    min_confidence: float = Field(default=0.65, ge=0.0, le=1.0, description="Minimum confidence required for proposal output.")
    require_human_approval: bool = Field(default=True, description="Require explicit human review before enablement.")


_skill_curation_config: SkillCurationConfig = SkillCurationConfig()


def get_skill_curation_config() -> SkillCurationConfig:
    """Get current skill-curation configuration."""
    return _skill_curation_config


def set_skill_curation_config(config: SkillCurationConfig) -> None:
    """Set skill-curation configuration."""
    global _skill_curation_config
    _skill_curation_config = config


def load_skill_curation_config_from_dict(config_dict: dict) -> None:
    """Load skill-curation configuration from dictionary."""
    global _skill_curation_config
    _skill_curation_config = SkillCurationConfig(**config_dict)
