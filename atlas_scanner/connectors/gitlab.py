"""GitLab CI connector.

Fetches .gitlab-ci.yml files, build logs, and documentation files via the
GitLab API using the python-gitlab library. Read-only access only.
"""

from __future__ import annotations

import logging
from typing import Any

from atlas_sdk.enums import Platform

from atlas_scanner.config import ScanConfig
from atlas_scanner.connectors.base import BaseConnector, BuildLog, DocFileEntry, PipelineConfig

logger = logging.getLogger(__name__)

# Documentation file patterns to detect
_DOC_PATTERNS = [
    ("README.md", "readme"),
    ("README.rst", "readme"),
    ("README", "readme"),
    ("docs/", "docs_dir"),
    ("RUNBOOK.md", "runbook"),
    ("ARCHITECTURE.md", "architecture"),
    ("adr/", "adr"),
    ("SECURITY.md", "security_policy"),
    ("CODEOWNERS", "codeowners"),
]


class GitLabConnector(BaseConnector):
    """Read-only connector for GitLab CI/CD."""

    def __init__(self, config: ScanConfig) -> None:
        super().__init__(config)
        self._gl: Any = None

    def connect(self) -> None:
        """Connect to GitLab and authenticate.

        Supports both gitlab.com and self-hosted instances.

        Raises:
            ConnectionError: If GitLab is unreachable or auth fails.
        """
        try:
            import gitlab
        except ImportError as e:
            raise ImportError(
                "python-gitlab is required: pip install python-gitlab"
            ) from e

        token = self.config.resolve_token()

        try:
            self._gl = gitlab.Gitlab(
                self.config.target_url,
                private_token=token,
                ssl_verify=self.config.verify_ssl,
                timeout=self.config.timeout_seconds,
            )
            self._gl.auth()
            logger.info("Authenticated with GitLab at %s", self.config.target_url)
        except Exception as e:
            raise ConnectionError(
                f"Failed to connect to GitLab at {self.config.target_url}: {e}"
            ) from e

    def fetch_pipeline_configs(self) -> list[PipelineConfig]:
        """Fetch .gitlab-ci.yml for all accessible projects."""
        if not self._gl:
            raise RuntimeError("Not connected. Call connect() first.")

        configs: list[PipelineConfig] = []
        projects = self._gl.projects.list(
            iterator=True,
            min_access_level=10,  # Guest or higher
            order_by="last_activity_at",
        )

        for i, project in enumerate(projects):
            if i >= self.config.max_jobs:
                logger.warning("Hit max_jobs limit (%d), stopping.", self.config.max_jobs)
                break

            if not self._matches_filter(project.path_with_namespace):
                continue

            try:
                ci_file = project.files.get(
                    file_path=".gitlab-ci.yml",
                    ref=project.default_branch or "main",
                )
                content = ci_file.decode().decode("utf-8", errors="replace")

                configs.append(PipelineConfig(
                    job_name=project.path_with_namespace,
                    path=".gitlab-ci.yml",
                    content=content,
                    platform=Platform.GITLAB,
                    job_type="gitlab_ci",
                    branch=project.default_branch,
                    metadata={
                        "project_id": project.id,
                        "web_url": project.web_url,
                        "visibility": project.visibility,
                    },
                ))
                logger.debug("Fetched .gitlab-ci.yml for %s", project.path_with_namespace)

            except Exception as e:
                logger.debug("No .gitlab-ci.yml in %s: %s", project.path_with_namespace, e)
                continue

        logger.info("Fetched %d pipeline configs from GitLab.", len(configs))
        return configs

    def fetch_build_logs(
        self, job_name: str, depth: int | None = None
    ) -> list[BuildLog]:
        """Fetch recent pipeline job logs for a GitLab project.

        Args:
            job_name: Project path (e.g. 'group/my-project').
            depth: Number of recent jobs to fetch logs for.
        """
        if not self._gl:
            raise RuntimeError("Not connected. Call connect() first.")

        depth = depth or self.config.log_depth
        logs: list[BuildLog] = []

        try:
            project = self._gl.projects.get(job_name)
            jobs = project.jobs.list(per_page=depth, order_by="id", sort="desc")
        except Exception as e:
            logger.warning("Could not get jobs for %s: %s", job_name, e)
            return []

        for job in jobs:
            try:
                trace = job.trace()
                raw_log = trace.decode("utf-8", errors="replace") if isinstance(trace, bytes) else str(trace)

                logs.append(BuildLog(
                    job_name=f"{job_name}/{job.name}",
                    build_number=job.id,
                    raw_log=raw_log,
                    status=job.status,
                    duration_ms=int(job.duration * 1000) if job.duration else None,
                    timestamp=job.created_at,
                ))
            except Exception as e:
                logger.warning("Skipping job %s/%d: %s", job_name, job.id, e)
                continue

        logger.info("Fetched %d build logs for %s.", len(logs), job_name)
        return logs

    def fetch_doc_files(self) -> list[DocFileEntry]:
        """Detect documentation files across accessible GitLab projects."""
        if not self._gl:
            raise RuntimeError("Not connected. Call connect() first.")

        doc_files: list[DocFileEntry] = []
        projects = self._gl.projects.list(
            iterator=True,
            min_access_level=10,
        )

        for i, project in enumerate(projects):
            if i >= self.config.max_jobs:
                break
            if not self._matches_filter(project.path_with_namespace):
                continue

            for file_pattern, doc_type in _DOC_PATTERNS:
                try:
                    f = project.files.get(
                        file_path=file_pattern.rstrip("/"),
                        ref=project.default_branch or "main",
                    )
                    content = f.decode().decode("utf-8", errors="replace")
                    doc_files.append(DocFileEntry(
                        path=f"{project.path_with_namespace}/{file_pattern}",
                        content=content,
                        detected_type=doc_type,
                    ))
                except Exception:
                    continue

        logger.info("Detected %d documentation files from GitLab.", len(doc_files))
        return doc_files
