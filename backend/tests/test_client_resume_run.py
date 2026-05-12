"""Tests for CapybaraClient resume_run helper."""

from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage

from src.client import CapybaraClient
from src.config.resume_config import ResumeConfig, set_resume_config


@pytest.fixture
def mock_app_config():
    model = MagicMock()
    model.name = "test-model"
    model.supports_thinking = True
    model.supports_reasoning_effort = False
    model.model_dump.return_value = {"name": "test-model", "use": "langchain_openai:ChatOpenAI"}
    config = MagicMock()
    config.models = [model]
    config.get_model_config.return_value = MagicMock(supports_vision=False)
    return config


def test_resume_run_returns_final_text(mock_app_config):
    set_resume_config(ResumeConfig(enabled=True, require_checkpoint=True, max_resume_depth=3))
    agent = MagicMock()
    agent.stream.return_value = iter(
        [
            {"messages": [AIMessage(content="partial")]},
            {"messages": [AIMessage(content="final text")], "title": "Resume", "artifacts": ["/tmp/a.txt"]},
        ]
    )

    with patch("src.client.get_app_config", return_value=mock_app_config):
        client = CapybaraClient()
    with patch.object(client, "_ensure_agent"), patch.object(client, "_agent", agent):
        result = client.resume_run("thread-1", "run-1")

    assert result["resumed"] is True
    assert result["final_text"] == "final text"
    assert result["values"]["artifacts"] == ["/tmp/a.txt"]


def test_resume_run_rejects_when_disabled(mock_app_config):
    set_resume_config(ResumeConfig(enabled=False, require_checkpoint=True, max_resume_depth=3))
    with patch("src.client.get_app_config", return_value=mock_app_config):
        client = CapybaraClient()
    with pytest.raises(ValueError, match="disabled"):
        client.resume_run("thread-1", "run-1")
