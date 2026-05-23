"""Unit tests for the subagent-output parser used by the researcher dispatcher.

This is the seam between the LLM-driven subagent's free-text JSON output and
the structured ``ResearchOutcome`` the loop persists into the ledger. Getting
this wrong silently corrupts every objective's ledger, so it has its own
tests.
"""

from __future__ import annotations

from src.control_plane.autoresearch_loop.researcher import _parse_subagent_result


def test_parse_returns_empty_dict_for_none_or_empty() -> None:
    assert _parse_subagent_result(None) == {}
    assert _parse_subagent_result("") == {}
    assert _parse_subagent_result("   ") == {}


def test_parse_extracts_plain_json_object() -> None:
    raw = '{"status": "succeeded", "vault_title": "Soba 101", "source_count": 4}'
    parsed = _parse_subagent_result(raw)
    assert parsed["status"] == "succeeded"
    assert parsed["vault_title"] == "Soba 101"
    assert parsed["source_count"] == 4


def test_parse_handles_markdown_fenced_json() -> None:
    raw = '```json\n{"status": "partial", "vault_title": "Soba notes"}\n```'
    parsed = _parse_subagent_result(raw)
    assert parsed["status"] == "partial"
    assert parsed["vault_title"] == "Soba notes"


def test_parse_extracts_json_when_wrapped_in_prose() -> None:
    """Subagents sometimes prepend stray reasoning; the parser must still find the JSON."""
    raw = (
        "Here is my report:\n"
        '{"status": "succeeded", "vault_title": "Soba in Singapore", "source_count": 5, '
        '"key_findings": ["Found 5 shops"], "uncertainty": ""}\n'
        "End of report."
    )
    parsed = _parse_subagent_result(raw)
    assert parsed["status"] == "succeeded"
    assert parsed["vault_title"] == "Soba in Singapore"
    assert parsed["source_count"] == 5


def test_parse_returns_empty_dict_when_no_braces_found() -> None:
    assert _parse_subagent_result("no json here, sorry") == {}


def test_parse_returns_empty_dict_on_unparseable_payload() -> None:
    # Looks like JSON but is malformed.
    raw = '{"status": "succeeded", "vault_title":}'
    assert _parse_subagent_result(raw) == {}
