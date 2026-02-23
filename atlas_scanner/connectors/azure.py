"""Azure DevOps connector — fetches pipeline YAML via Azure DevOps REST API."""

from __future__ import annotations

import logging
from typing import Any

from atlas_scanner.connectors.base import BaseConnector

logger = logging.getLogger(__name__)


class AzureDevOpsConnector(BaseConnector):
    """Connects to Azure DevOps and fetches pipeline definitions.

    Uses the Azure DevOps REST API to retrieve YAML pipeline files
    from repositories.
    """

    platform = "azure_devops"

    def __init__(self, base_url: str, token: str, organization: str = "", project: str = "") -> None:
        super().__init__(base_url, token)
        self.organization = organization
        self.project = project

    def fetch_pipelines(self) -> list[dict[str, Any]]:
        """Fetch all pipeline definitions from Azure DevOps."""
        url = f"{self.base_url}/{self.organization}/{self.project}/_apis/pipelines?api-version=7.1"
        headers = {"Authorization": f"Basic {self.token}"}

        try:
            import requests
            resp = requests.get(url, headers=headers, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            pipelines = data.get("value", [])
            logger.info("Fetched %d pipeline(s) from Azure DevOps", len(pipelines))
            return [
                {
                    "job_name": p.get("name", ""),
                    "path": p.get("folder", "") + "/" + p.get("name", ""),
                    "content": "",  # content fetched separately
                    "job_type": "azure_pipelines",
                    "platform": "azure_devops",
                }
                for p in pipelines
            ]
        except Exception as e:
            logger.error("Failed to fetch Azure DevOps pipelines: %s", e)
            return []

    def fetch_pipeline_yaml(self, pipeline_id: int) -> str:
        """Fetch YAML content for a specific pipeline."""
        url = (
            f"{self.base_url}/{self.organization}/{self.project}"
            f"/_apis/pipelines/{pipeline_id}/runs?api-version=7.1"
        )
        headers = {"Authorization": f"Basic {self.token}"}

        try:
            import requests
            resp = requests.get(url, headers=headers, timeout=30)
            resp.raise_for_status()
            return resp.text
        except Exception as e:
            logger.error("Failed to fetch pipeline YAML: %s", e)
            return ""
