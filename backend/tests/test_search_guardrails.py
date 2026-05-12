from src.security.search_guardrails import CIDGuardrailConfig, detect_cid_signals, enforce_fetch_url_guardrails, enforce_query_guardrails


def test_detect_cid_signals_finds_common_identifiers():
    signals = detect_cid_signals("Contact me at person@example.com and 123-45-6789")
    assert "email" in signals
    assert "ssn" in signals


def test_enforce_query_guardrails_blocks_sensitive_query(monkeypatch):
    monkeypatch.setattr(
        "src.security.search_guardrails._load_guardrail_config",
        lambda: CIDGuardrailConfig(enabled=True, block_on_detection=True),
    )

    try:
        enforce_query_guardrails("Find the social security number of Jane Doe", tool_name="web_search")
        assert False, "Expected CID guardrail to block sensitive query"
    except ValueError as e:
        assert "Blocked `web_search` query" in str(e)


def test_enforce_query_guardrails_allows_when_disabled(monkeypatch):
    monkeypatch.setattr(
        "src.security.search_guardrails._load_guardrail_config",
        lambda: CIDGuardrailConfig(enabled=False),
    )

    enforce_query_guardrails("Find the social security number of Jane Doe", tool_name="web_search")


def test_enforce_fetch_url_guardrails_blocks_private_hosts(monkeypatch):
    monkeypatch.setattr(
        "src.security.search_guardrails._load_guardrail_config",
        lambda: CIDGuardrailConfig(enabled=True, block_private_network_urls=True),
    )

    try:
        enforce_fetch_url_guardrails("http://localhost/admin", tool_name="web_search_internal")
        assert False, "Expected URL guardrail to block localhost URL"
    except ValueError as e:
        assert "private or local" in str(e)


def test_enforce_fetch_url_guardrails_blocks_non_http(monkeypatch):
    monkeypatch.setattr(
        "src.security.search_guardrails._load_guardrail_config",
        lambda: CIDGuardrailConfig(enabled=True),
    )

    try:
        enforce_fetch_url_guardrails("ftp://example.com/data", tool_name="web_search_internal")
        assert False, "Expected URL guardrail to block non-http URL"
    except ValueError as e:
        assert "http/https" in str(e)


def test_enforce_fetch_url_guardrails_respects_allowed_domains(monkeypatch):
    monkeypatch.setattr(
        "src.security.search_guardrails._load_guardrail_config",
        lambda: CIDGuardrailConfig(enabled=True, allowed_fetch_domains=("example.com",)),
    )

    enforce_fetch_url_guardrails("https://sub.example.com/path", tool_name="web_search_internal")

    try:
        enforce_fetch_url_guardrails("https://another.org/path", tool_name="web_search_internal")
        assert False, "Expected URL guardrail to block disallowed domain"
    except ValueError as e:
        assert "allowed_fetch_domains" in str(e)
