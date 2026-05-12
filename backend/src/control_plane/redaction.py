from __future__ import annotations

import hashlib
import re
from typing import Any

from src.config import get_app_config

EMAIL_RE = re.compile(r"\b[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}\b", re.IGNORECASE)
PHONE_RE = re.compile(r"(?:(?:\+?\d{1,3}[\s\-]?)?(?:\(?\d{2,4}\)?[\s\-]?)?\d{3,4}[\s\-]?\d{4})")
CARD_RE = re.compile(r"\b(?:\d[ -]*?){13,16}\b")


class RedactionService:
    def __init__(self) -> None:
        self._config = get_app_config().redaction

    def redact_text(self, text: str) -> str:
        if not self._config.enabled or not text:
            return text

        redacted = text
        if self._config.mask_emails:
            redacted = EMAIL_RE.sub(lambda match: self._replacement(match.group(0)), redacted)
        if self._config.mask_phone_numbers:
            redacted = PHONE_RE.sub(lambda match: self._replacement(match.group(0)), redacted)
        if self._config.mask_credit_cards:
            redacted = CARD_RE.sub(lambda match: self._replacement(match.group(0)), redacted)

        for pattern in self._config.custom_patterns:
            replacement = pattern.replacement or self._config.replace_with
            redacted = re.sub(pattern.pattern, replacement, redacted)

        return redacted

    def redact_value(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.redact_text(value)
        if isinstance(value, list):
            return [self.redact_value(item) for item in value]
        if isinstance(value, dict):
            return {str(key): self.redact_value(item) for key, item in value.items()}
        return value

    def _replacement(self, value: str) -> str:
        if not self._config.hash_values:
            return self._config.replace_with
        digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:10]
        return f"{self._config.replace_with}:{digest}"
