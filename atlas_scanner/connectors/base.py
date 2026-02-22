"""Abstract base connector and shared data classes.

All platform-specific connectors (Jenkins, GitLab, GitHub) must
implement the BaseConnector interface.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from atlas_sdk.enums import Platform

from atlas_scanner.config import ScanConfig

logger = logging.getLogger(__name__)


@dataclass
class PipelineConfig:
    """Raw pipeline definition fetched from a CI platform."""

    job_name: str
    path: str
    content: str
    platform: Platform
    job_type: str = ""
    branch: str | None = None
    metadata: dict = field(default_factory=dict)


@dataclass
class BuildLog:
    """A single build log entry."""

    job_name: str
    build_number: int
    raw_log: str
    status: str = ""
    duration_ms: int | None = None
    timestamp: str | None = None


@dataclass
class DocFileEntry:
    """A documentation file detected in a repository."""

    path: str
    content: str
    detected_type: str = "other"


class BaseConnector(ABC):
    """Abstract connector interface for CI/CD platforms.

    Each connector handles one platform (Jenkins, GitLab, etc.)
    and provides methods to fetch pipeline configs, build logs,
    and documentation files via read-only API access.
    """

    def __init__(self, config: ScanConfig) -> None:
        self.config = config

    @abstractmethod
    def connect(self) -> None:
        """Validate credentials and establish connection.

        Raises:
            ConnectionError: If the platform is unreachable or auth fails.
        """

    @abstractmethod
    def fetch_pipeline_configs(self) -> list[PipelineConfig]:
        """Fetch all pipeline/job definitions within scan scope.

        Returns:
            List of raw pipeline configurations.
        """

    @abstractmethod
    def fetch_build_logs(self, job_name: str, depth: int | None = None) -> list[BuildLog]:
        """Fetch build logs for a specific job.

        Args:
            job_name: The job/project to fetch logs for.
            depth: Number of recent builds (defaults to config.log_depth).

        Returns:
            List of build logs, most recent first.
        """

    @abstractmethod
    def fetch_doc_files(self) -> list[DocFileEntry]:
        """Detect and fetch documentation files from the platform.

        Returns:
            List of documentation file entries.
        """

    def _matches_filter(self, job_name: str) -> bool:
        """Check if a job matches the configured filter."""
        if "*" in self.config.job_filter:
            return True
        return any(
            self._glob_match(pattern, job_name)
            for pattern in self.config.job_filter
        )

    @staticmethod
    def _glob_match(pattern: str, name: str) -> bool:
        """Simple glob matching: supports * and exact match."""
        if pattern == "*":
            return True
        if "*" in pattern:
            import fnmatch
            return fnmatch.fnmatch(name, pattern)
        return pattern == name
