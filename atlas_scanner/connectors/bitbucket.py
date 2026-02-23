"""Bitbucket Pipelines connector — fetches bitbucket-pipelines.yml via API."""

from __future__ import annotations

import logging
from typing import Any

from atlas_scanner.connectors.base import BaseConnector

logger = logging.getLogger(__name__)


class BitbucketConnector(BaseConnector):
    """Connects to Bitbucket and fetches pipeline definitions.

    Uses the Bitbucket REST API 2.0 to retrieve bitbucket-pipelines.yml
    from repositories.
    """

    platform = "bitbucket"

    def __init__(self, base_url: str = "https://api.bitbucket.org/2.0", token: str = "", workspace: str = "") -> None:
        super().__init__(base_url, token)
        self.workspace = workspace

    def fetch_pipelines(self, repo_slug: str) -> list[dict[str, Any]]:
        """Fetch pipeline config from a Bitbucket repository."""
        url = f"{self.base_url}/repositories/{self.workspace}/{repo_slug}/src/main/bitbucket-pipelines.yml"
        headers = {"Authorization": f"Bearer {self.token}"}

        try:
            import requests
            resp = requests.get(url, headers=headers, timeout=30)
            resp.raise_for_status()
            content = resp.text
            logger.info("Fetched pipeline config for %s/%s", self.workspace, repo_slug)
            return [{
                "job_name": repo_slug,
                "path": "bitbucket-pipelines.yml",
                "content": content,
                "job_type": "bitbucket_pipelines",
                "platform": "bitbucket",
            }]
        except Exception as e:
            logger.error("Failed to fetch Bitbucket pipeline: %s", e)
            return []
