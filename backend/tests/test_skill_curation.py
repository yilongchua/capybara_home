"""Tests for skill curation proposal flow."""

from pathlib import Path

from src.config.paths import Paths
from src.config.skill_curation_config import SkillCurationConfig, set_skill_curation_config
from src.skills.curation import generate_skill_proposals


def test_generate_skill_proposals_creates_disabled_proposal(monkeypatch, tmp_path: Path):
    set_skill_curation_config(
        SkillCurationConfig(
            enabled=True,
            proposal_only=True,
            min_confidence=0.2,
            require_human_approval=True,
        )
    )

    trajectory_dir = tmp_path / "threads" / "thread-1" / "logs" / "trajectory"
    trajectory_dir.mkdir(parents=True, exist_ok=True)
    trajectory_file = trajectory_dir / "sample.jsonl"
    trajectory_file.write_text(
        "\n".join(
            [
                '{"event":"tool_call_start","payload":{"tool":"read_file"}}',
                '{"event":"tool_call_start","payload":{"tool":"read_file"}}',
                '{"event":"tool_call_start","payload":{"tool":"read_file"}}',
            ]
        ),
        encoding="utf-8",
    )

    skills_root = tmp_path / "skills"
    (skills_root / "custom").mkdir(parents=True, exist_ok=True)

    extensions_config = tmp_path / "extensions_config.json"
    extensions_config.write_text('{"mcpServers": {}, "skills": {}}', encoding="utf-8")

    monkeypatch.setattr("src.skills.curation.get_paths", lambda: Paths(base_dir=tmp_path))
    monkeypatch.setattr("src.skills.curation.get_skills_root_path", lambda: skills_root)
    monkeypatch.setattr("src.skills.curation.ExtensionsConfig.resolve_config_path", lambda config_path=None: extensions_config)

    proposals = generate_skill_proposals(limit=1)
    assert len(proposals) == 1
    proposal = proposals[0]
    assert proposal["require_human_approval"] is True
    proposal_path = Path(proposal["path"])
    assert proposal_path.exists()
    assert (proposal_path / "SKILL.md").exists()
