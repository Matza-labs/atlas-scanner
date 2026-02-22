"""Jenkins CI connector.

Fetches pipeline definitions, build logs, and metadata via the Jenkins
REST API using the python-jenkins library. Read-only access only.
"""

from __future__ import annotations

import logging
from typing import Any

from atlas_sdk.enums import Platform

from atlas_scanner.config import ScanConfig
from atlas_scanner.connectors.base import BaseConnector, BuildLog, DocFileEntry, PipelineConfig

logger = logging.getLogger(__name__)


class JenkinsConnector(BaseConnector):
    """Read-only connector for Jenkins CI."""

    def __init__(self, config: ScanConfig) -> None:
        super().__init__(config)
        self._server: Any = None

    def connect(self) -> None:
        """Connect to Jenkins and verify access.

        Raises:
            ConnectionError: If Jenkins is unreachable or auth fails.
        """
        try:
            import jenkins
        except ImportError as e:
            raise ImportError(
                "python-jenkins is required: pip install python-jenkins"
            ) from e

        token = self.config.resolve_token()
        username = self.config.resolve_username()

        try:
            self._server = jenkins.Jenkins(
                self.config.target_url,
                username=username or None,
                password=token or None,
                timeout=self.config.timeout_seconds,
            )
            version = self._server.get_version()
            logger.info("Connected to Jenkins %s at %s", version, self.config.target_url)
        except Exception as e:
            raise ConnectionError(
                f"Failed to connect to Jenkins at {self.config.target_url}: {e}"
            ) from e

    def fetch_pipeline_configs(self) -> list[PipelineConfig]:
        """Fetch all matching job configurations from Jenkins.

        Handles both Pipeline (WorkflowJob) and Freestyle (FreeStyleProject)
        job types. Multi-branch pipelines are flattened.
        """
        if not self._server:
            raise RuntimeError("Not connected. Call connect() first.")

        configs: list[PipelineConfig] = []
        jobs = self._server.get_all_jobs()

        for i, job_info in enumerate(jobs):
            if i >= self.config.max_jobs:
                logger.warning("Hit max_jobs limit (%d), stopping.", self.config.max_jobs)
                break

            job_name = job_info.get("fullname", job_info.get("name", ""))
            if not self._matches_filter(job_name):
                continue

            try:
                config_xml = self._server.get_job_config(job_name)
                job_type = self._detect_job_type(config_xml)

                pipeline_config = PipelineConfig(
                    job_name=job_name,
                    path=f"jobs/{job_name}/config.xml",
                    content=config_xml,
                    platform=Platform.JENKINS,
                    job_type=job_type,
                    metadata={
                        "url": job_info.get("url", ""),
                        "color": job_info.get("color", ""),
                    },
                )
                configs.append(pipeline_config)
                logger.debug("Fetched config for %s (%s)", job_name, job_type)

            except Exception as e:
                logger.warning("Skipping job %s: %s", job_name, e)
                continue

        logger.info("Fetched %d pipeline configs from Jenkins.", len(configs))
        return configs

    def fetch_build_logs(
        self, job_name: str, depth: int | None = None
    ) -> list[BuildLog]:
        """Fetch recent build logs for a job.

        Args:
            job_name: Full job name (e.g. 'folder/my-pipeline').
            depth: Number of recent builds to fetch.

        Returns:
            Build logs ordered most recent first.
        """
        if not self._server:
            raise RuntimeError("Not connected. Call connect() first.")

        depth = depth or self.config.log_depth
        logs: list[BuildLog] = []

        try:
            job_info = self._server.get_job_info(job_name)
            builds = job_info.get("builds", [])[:depth]
        except Exception as e:
            logger.warning("Could not get builds for %s: %s", job_name, e)
            return []

        for build in builds:
            build_number = build.get("number", 0)
            try:
                raw_log = self._server.get_build_console_output(job_name, build_number)
                build_info = self._server.get_build_info(job_name, build_number)

                logs.append(BuildLog(
                    job_name=job_name,
                    build_number=build_number,
                    raw_log=raw_log,
                    status=build_info.get("result", "UNKNOWN") or "IN_PROGRESS",
                    duration_ms=build_info.get("duration"),
                    timestamp=str(build_info.get("timestamp", "")),
                ))
            except Exception as e:
                logger.warning(
                    "Skipping build %s#%d: %s", job_name, build_number, e
                )
                continue

        logger.info("Fetched %d build logs for %s.", len(logs), job_name)
        return logs

    def fetch_doc_files(self) -> list[DocFileEntry]:
        """Jenkins doesn't provide direct repo file access.

        Documentation detection requires SCM checkout, which is handled
        by atlas-scanner separately when repo URL is known.
        """
        return []

    @staticmethod
    def _detect_job_type(config_xml: str) -> str:
        """Detect Jenkins job type from config XML."""
        if "<flow-definition" in config_xml:
            return "pipeline"
        if "<org.jenkinsci.plugins.workflow" in config_xml:
            return "multibranch"
        if "<project>" in config_xml or "<freeStyleProject" in config_xml:
            return "freestyle"
        if "<maven2-moduleset" in config_xml:
            return "maven"
        return "unknown"
