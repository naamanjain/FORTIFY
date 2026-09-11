from __future__ import annotations

import hashlib
import hmac

from .security_config import SecurityPolicyConfig


class IdentityTokenizer:
    """Deterministic pseudonymization for analytics-facing personnel identifiers."""

    def __init__(self, secret: str | bytes, *, config: SecurityPolicyConfig | None = None) -> None:
        self.config = config or SecurityPolicyConfig()
        key = secret.encode("utf-8") if isinstance(secret, str) else secret
        if len(key) < self.config.minimum_token_secret_length:
            raise ValueError("Tokenization secret is too short for prototype use")
        self._key = key

    def tokenize(self, person_id: str) -> str:
        if not person_id:
            raise ValueError("person_id must be non-empty")
        digest = hmac.new(self._key, person_id.encode("utf-8"), hashlib.sha256).hexdigest()[:24]
        return f"{self.config.token_prefix}{digest}"

    def verify(self, person_id: str, token: str) -> bool:
        return hmac.compare_digest(self.tokenize(person_id), token)
