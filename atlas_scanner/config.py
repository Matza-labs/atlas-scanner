"""Scanner configuration model.

ScanConfig defines settings for a single scan run. Token values are
never stored — only references to environment variables.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from atlas_sdk.enums import Platform


class ScanConfig(BaseModel):
    """Configuration for a single scan run."""

    platform: Platform
    target_url: str
    token_ref: str = ""
    """Environment variable name holding the API token. Never the token itself."""

    username: str = ""
    """Username for authentication (Jenkins). Can also be an env var ref."""

    job_filter: list[str] = Field(default_factory=lambda: ["*"])
    """Which jobs/projects to scan. '*' means all."""

    log_depth: int = 5
    """Number of recent builds to fetch logs for, per job."""

    timeout_seconds: int = 30
    """Per-request HTTP timeout."""

    verify_ssl: bool = True
    """Whether to verify SSL certificates."""

    max_jobs: int = 500
    """Maximum number of jobs to scan (safety limit)."""

    def resolve_token(self) -> str:
        """Resolve the token from the environment variable.

        Raises:
            ValueError: If the referenced env var is not set.
        """
        import os

        if not self.token_ref:
            return ""
        value = os.environ.get(self.token_ref, "")
        if not value:
            raise ValueError(
                f"Environment variable '{self.token_ref}' is not set. "
                f"Set it with your read-only API token."
            )
        return value

    def resolve_username(self) -> str:
        """Resolve username — if it looks like an env var ref, resolve it."""
        import os

        if self.username.startswith("$"):
            return os.environ.get(self.username.lstrip("$"), self.username)
        return self.username
