"""Scanner orchestrator — the main entry point for atlas-scanner.

Coordinates:
  1. Reads ScanConfig (or ScanRequestEvent)
  2. Instantiates the correct connector (Jenkins / GitLab)
  3. Fetches pipeline configs, build logs, doc files
  4. Sanitizes all logs
  5. Publishes ScanResultEvent to Redis Streams
"""

from __future__ import annotations

import logging
from typing import Any

from atlas_sdk.enums import Platform
from atlas_sdk.events import ScanResultEvent

from atlas_scanner.config import ScanConfig
from atlas_scanner.connectors.base import BaseConnector
from atlas_scanner.connectors.gitlab import GitLabConnector
from atlas_scanner.connectors.jenkins import JenkinsConnector
from atlas_scanner.publisher import Publisher
from atlas_scanner.sanitizer import sanitize_log

logger = logging.getLogger(__name__)

# Registry of platform → connector class
CONNECTOR_MAP: dict[Platform, type[BaseConnector]] = {
    Platform.JENKINS: JenkinsConnector,
    Platform.GITLAB: GitLabConnector,
}


class Scanner:
    """Main scanner orchestrator.

    Usage:
        scanner = Scanner(config, redis_url="redis://localhost:6379")
        result = scanner.run()
    """

    def __init__(
        self,
        config: ScanConfig,
        redis_url: str = "redis://localhost:6379",
        publish: bool = True,
    ) -> None:
        self.config = config
        self._redis_url = redis_url
        self._publish = publish
        self._connector: BaseConnector | None = None
        self._publisher: Publisher | None = None

    def run(self) -> ScanResultEvent:
        """Execute a full scan.

        Returns:
            ScanResultEvent with all fetched data (logs sanitized).
        """
        logger.info(
            "Starting scan: platform=%s url=%s",
            self.config.platform,
            self.config.target_url,
        )

        # 1. Create connector
        connector_cls = CONNECTOR_MAP.get(self.config.platform)
        if not connector_cls:
            raise ValueError(f"Unsupported platform: {self.config.platform}")

        self._connector = connector_cls(self.config)
        self._connector.connect()

        # 2. Fetch pipeline configs
        logger.info("Fetching pipeline configs...")
        pipeline_configs = self._connector.fetch_pipeline_configs()

        # 3. Fetch build logs and sanitize
        logger.info("Fetching build logs (depth=%d)...", self.config.log_depth)
        all_logs: list[dict[str, Any]] = []
        for pc in pipeline_configs:
            logs = self._connector.fetch_build_logs(
                pc.job_name, depth=self.config.log_depth
            )
            for log in logs:
                all_logs.append({
                    "job_name": log.job_name,
                    "build_number": log.build_number,
                    "log": sanitize_log(log.raw_log),
                    "status": log.status,
                    "duration_ms": log.duration_ms,
                    "timestamp": log.timestamp,
                })

        # 4. Fetch documentation files
        logger.info("Detecting documentation files...")
        doc_files = self._connector.fetch_doc_files()

        # 5. Build event
        event = ScanResultEvent(
            scan_request_id="",
            platform=self.config.platform,
            pipeline_configs=[
                {
                    "job_name": pc.job_name,
                    "path": pc.path,
                    "content": pc.content,
                    "job_type": pc.job_type,
                    "branch": pc.branch,
                    "metadata": pc.metadata,
                }
                for pc in pipeline_configs
            ],
            build_logs=all_logs,
            doc_files=[
                {
                    "path": df.path,
                    "content": df.content,
                    "detected_type": df.detected_type,
                }
                for df in doc_files
            ],
        )

        # 6. Publish to Redis
        if self._publish:
            self._publisher = Publisher(self._redis_url)
            self._publisher.connect()
            self._publisher.publish_scan_result(event)
            self._publisher.close()

        logger.info(
            "Scan complete: %d configs, %d logs, %d docs",
            len(pipeline_configs),
            len(all_logs),
            len(doc_files),
        )
        return event
