from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from urllib.parse import urlparse

from src.config import get_app_config


@dataclass(frozen=True)
class CIDGuardrailConfig:
    enabled: bool = True
    block_on_detection: bool = True
    max_query_chars: int = 512
    allow_personal_data_queries: bool = False
    block_private_network_urls: bool = True
    allowed_fetch_domains: tuple[str, ...] = ()


_SENSITIVE_INTENT_PATTERNS = [
    ("doxxing-intent", re.compile(r"\b(home|residential|private)\s+address\b", re.IGNORECASE)),
    ("ssn-intent", re.compile(r"\bsocial\s+security\s+number\b|\bssn\b", re.IGNORECASE)),
    ("passport-intent", re.compile(r"\bpassport\s+number\b", re.IGNORECASE)),
    ("dob-intent", re.compile(r"\b(date\s+of\s+birth|dob)\b", re.IGNORECASE)),
    ("phone-intent", re.compile(r"\b(phone|mobile|cell)\s+number\b", re.IGNORECASE)),
]

_IDENTIFIER_PATTERNS = [
    ("email", re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)),
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("phone", re.compile(r"\b(?:\+?\d{1,3}[-.\s]?)?(?:\(?\d{2,4}\)?[-.\s]?)\d{3}[-.\s]?\d{4}\b")),
    ("credit-card", re.compile(r"\b(?:\d[ -]*?){13,19}\b")),
    ("api-key", re.compile(r"\b(?:sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})\b")),
]

_BLOCKED_HOSTS = {
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "::1",
    "169.254.169.254",
    "metadata.google.internal",
    "metadata",
}


def _to_bool(value: object, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return default


def _load_guardrail_config() -> CIDGuardrailConfig:
    config = get_app_config()
    cfg = {}
    if config.model_extra and isinstance(config.model_extra.get("cid_guardrails"), dict):
        cfg = config.model_extra["cid_guardrails"]

    allowed_domains = cfg.get("allowed_fetch_domains", [])
    if not isinstance(allowed_domains, list):
        allowed_domains = []

    return CIDGuardrailConfig(
        enabled=_to_bool(cfg.get("enabled"), True),
        block_on_detection=_to_bool(cfg.get("block_on_detection"), True),
        max_query_chars=int(cfg.get("max_query_chars", 512)),
        allow_personal_data_queries=_to_bool(cfg.get("allow_personal_data_queries"), False),
        block_private_network_urls=_to_bool(cfg.get("block_private_network_urls"), True),
        allowed_fetch_domains=tuple(str(domain).lower().strip() for domain in allowed_domains if str(domain).strip()),
    )


def _host_allowed(host: str, allowed_domains: tuple[str, ...]) -> bool:
    if not allowed_domains:
        return True
    for domain in allowed_domains:
        if host == domain or host.endswith(f".{domain}"):
            return True
    return False


def detect_cid_signals(text: str) -> list[str]:
    signals: list[str] = []
    for label, pattern in _SENSITIVE_INTENT_PATTERNS:
        if pattern.search(text):
            signals.append(label)
    for label, pattern in _IDENTIFIER_PATTERNS:
        if pattern.search(text):
            signals.append(label)
    return signals


def enforce_query_guardrails(query: str, tool_name: str = "web_search") -> None:
    cfg = _load_guardrail_config()
    if not cfg.enabled:
        return

    normalized_query = query.strip()
    if len(normalized_query) > cfg.max_query_chars:
        raise ValueError(
            f"Blocked `{tool_name}` query because it exceeds the configured length limit ({cfg.max_query_chars} chars)."
        )

    if cfg.allow_personal_data_queries:
        return

    signals = detect_cid_signals(normalized_query)
    if signals and cfg.block_on_detection:
        signal_preview = ", ".join(sorted(set(signals))[:3])
        raise ValueError(
            f"Blocked `{tool_name}` query due to possible confidential personal data leakage signals: {signal_preview}. "
            "Please rephrase with non-identifying and aggregated terms."
        )


def enforce_fetch_url_guardrails(url: str, tool_name: str = "web_search_internal") -> None:
    cfg = _load_guardrail_config()
    if not cfg.enabled:
        return

    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(f"Blocked `{tool_name}` URL because only http/https schemes are allowed.")

    if parsed.username or parsed.password:
        raise ValueError(f"Blocked `{tool_name}` URL with embedded credentials.")

    host = (parsed.hostname or "").lower()
    if not host:
        raise ValueError(f"Blocked `{tool_name}` URL because hostname is missing.")

    if not _host_allowed(host, cfg.allowed_fetch_domains):
        raise ValueError(f"Blocked `{tool_name}` URL because host '{host}' is not in allowed_fetch_domains.")

    if not cfg.block_private_network_urls:
        return

    if host in _BLOCKED_HOSTS or host.endswith(".local") or host.endswith(".internal"):
        raise ValueError(f"Blocked `{tool_name}` URL because host '{host}' is private or local.")

    try:
        host_ip = ipaddress.ip_address(host)
    except ValueError:
        return

    if (
        host_ip.is_private
        or host_ip.is_loopback
        or host_ip.is_link_local
        or host_ip.is_multicast
        or host_ip.is_reserved
        or host_ip.is_unspecified
    ):
        raise ValueError(f"Blocked `{tool_name}` URL because host IP '{host_ip}' is private or unsafe.")
