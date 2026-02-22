"""Log sanitizer — ANSI strip and secret redaction.

From docs/README.md §4.2 and docs/SECURITY.md:
  - Strip ANSI characters
  - Remove secret patterns
  - Logs must never leave environment unfiltered
"""

from __future__ import annotations

import re

# ANSI escape sequence pattern
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")

# Secret patterns to redact (compiled for performance)
_SECRET_PATTERNS: list[re.Pattern] = [
    # Key=value patterns (password, token, secret, api_key, apikey, etc.)
    re.compile(
        r"((?:password|passwd|token|secret|api_?key|access_?key|auth)"
        r"\s*[=:]\s*)"
        r"(\S+)",
        re.IGNORECASE,
    ),
    # AWS Access Key IDs
    re.compile(r"(AKIA[A-Z0-9]{16})"),
    # AWS Secret Access Keys (in key=value context)
    re.compile(
        r"(aws_secret_access_key\s*[=:]\s*)(\S+)",
        re.IGNORECASE,
    ),
    # GitHub Personal Access Tokens
    re.compile(r"(ghp_[A-Za-z0-9]{36,})"),
    # GitLab Personal Access Tokens
    re.compile(r"(glpat-[A-Za-z0-9\-_]{20,})"),
    # Bearer tokens
    re.compile(r"(Bearer\s+)([A-Za-z0-9+/=\-_.]+)", re.IGNORECASE),
    # Generic hex/base64 token-like values after common keywords
    re.compile(
        r"((?:authorization|x-api-key|x-auth-token)\s*[=:]\s*)"
        r"(\S+)",
        re.IGNORECASE,
    ),
]

_REDACTED = "***REDACTED***"


def strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences from text."""
    return _ANSI_RE.sub("", text)


def redact_secrets(text: str) -> str:
    """Replace detected secret patterns with ***REDACTED***.

    This is a best-effort approach. It may not catch all secrets,
    but it covers the most common patterns across CI/CD logs.
    """
    result = text
    for pattern in _SECRET_PATTERNS:
        groups = pattern.groups if hasattr(pattern, "groups") else 0
        if pattern.groups >= 2:
            # Pattern has prefix + value groups — keep prefix, redact value
            result = pattern.sub(rf"\1{_REDACTED}", result)
        else:
            # Whole match is the secret
            result = pattern.sub(_REDACTED, result)
    return result


def sanitize_log(raw: str) -> str:
    """Full sanitization pipeline: ANSI strip → secret redaction.

    Args:
        raw: Raw build log text.

    Returns:
        Sanitized log text safe for downstream processing.
    """
    text = strip_ansi(raw)
    text = redact_secrets(text)
    return text
