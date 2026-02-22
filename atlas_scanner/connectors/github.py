"""GitHub Actions connector.

Fetches .github/workflows/*.yaml files, build logs, and documentation files via the
GitHub REST API using httpx. Read-only access only.
"""

from __future__ import annotations

import base64
import logging
from typing import Any

import httpx

from atlas_sdk.enums import Platform

from atlas_scanner.config import ScanConfig
from atlas_scanner.connectors.base import BaseConnector, BuildLog, DocFileEntry, PipelineConfig

logger = logging.getLogger(__name__)

# Documentation file patterns to detect
_DOC_PATTERNS = [
    ("README.md", "readme"),
    ("README.rst", "readme"),
    ("README", "readme"),
    ("docs", "docs_dir"),
    ("RUNBOOK.md", "runbook"),
    ("ARCHITECTURE.md", "architecture"),
    ("adr", "adr"),
    ("SECURITY.md", "security_policy"),
    ("CODEOWNERS", "codeowners"),
]


class GitHubConnector(BaseConnector):
    """Read-only connector for GitHub Actions."""

    def __init__(self, config: ScanConfig) -> None:
        super().__init__(config)
        self._client: httpx.Client | None = None
        # Default to api.github.com if target_url isn't a specific enterprise URL
        api_url = config.target_url.rstrip("/")
        if "api.github.com" not in api_url and "github.com" in api_url:
            self._api_base = "https://api.github.com"
        else:
            self._api_base = api_url

    def connect(self) -> None:
        """Connect to GitHub and authenticate.

        Raises:
            ConnectionError: If GitHub is unreachable or auth fails.
        """
        token = self.config.resolve_token()
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        self._client = httpx.Client(
            base_url=self._api_base,
            headers=headers,
            verify=self.config.verify_ssl,
            timeout=self.config.timeout_seconds,
        )

        try:
            # Verify authentication
            resp = self._client.get("/user")
            resp.raise_for_status()
            logger.info("Authenticated with GitHub as %s", resp.json().get("login", "unknown"))
        except httpx.HTTPError as e:
            raise ConnectionError(f"Failed to connect to GitHub at {self._api_base}: {e}") from e

    def fetch_pipeline_configs(self) -> list[PipelineConfig]:
        """Fetch .github/workflows/*.yml for all accessible repositories."""
        if not self._client:
            raise RuntimeError("Not connected. Call connect() first.")

        configs: list[PipelineConfig] = []
        
        try:
            # Get accessible repositories
            resp = self._client.get("/user/repos", params={"per_page": min(100, self.config.max_jobs)})
            resp.raise_for_status()
            repos = resp.json()
        except httpx.HTTPError as e:
            logger.error("Failed to fetch repositories: %s", e)
            return []

        for i, repo in enumerate(repos):
            if i >= self.config.max_jobs:
                logger.warning("Hit max_jobs limit (%d), stopping.", self.config.max_jobs)
                break

            repo_name = repo["full_name"]
            default_branch = repo.get("default_branch", "main")

            if not self._matches_filter(repo_name):
                continue

            try:
                # List workflow directory contents
                workflows_resp = self._client.get(f"/repos/{repo_name}/contents/.github/workflows")
                
                # 404 means no workflows directory
                if workflows_resp.status_code == 404:
                    logger.debug("No .github/workflows in %s", repo_name)
                    continue
                    
                workflows_resp.raise_for_status()
                files = workflows_resp.json()
                
                if not isinstance(files, list):
                    continue

                for file_info in files:
                    file_name: str = file_info["name"]
                    if not file_name.endswith((".yml", ".yaml")):
                        continue
                        
                    # Fetch specific file content
                    file_resp = self._client.get(f"/repos/{repo_name}/contents/.github/workflows/{file_name}")
                    file_resp.raise_for_status()
                    
                    file_data = file_resp.json()
                    content = base64.b64decode(file_data["content"]).decode("utf-8", errors="replace")

                    configs.append(PipelineConfig(
                        job_name=f"{repo_name}: {file_name}",
                        path=f".github/workflows/{file_name}",
                        content=content,
                        platform=Platform.GITHUB_ACTIONS,
                        job_type="github_actions",
                        branch=default_branch,
                        metadata={
                            "repo_id": repo["id"],
                            "html_url": file_info.get("html_url", ""),
                            "visibility": repo.get("visibility", "unknown"),
                        },
                    ))
                    logger.debug("Fetched %s for %s", file_name, repo_name)

            except httpx.HTTPError as e:
                logger.debug("Error fetching workflows for %s: %s", repo_name, e)
                continue

        logger.info("Fetched %d workflow configs from GitHub.", len(configs))
        return configs

    def fetch_build_logs(
        self, job_name: str, depth: int | None = None
    ) -> list[BuildLog]:
        """Fetch recent workflow run logs for a GitHub repository.

        Args:
            job_name: Repository name (e.g. 'owner/repo') or formatted job name ('owner/repo: file.yml').
        """
        if not self._client:
            raise RuntimeError("Not connected. Call connect() first.")

        # Extract repo name from job_name in case we get the formatted "repo: workflow.yml" name
        repo_name = job_name.split(":")[0].strip()
        depth = depth or self.config.log_depth
        logs: list[BuildLog] = []

        try:
            # Fetch recent workflow runs
            runs_resp = self._client.get(f"/repos/{repo_name}/actions/runs", params={"per_page": depth})
            runs_resp.raise_for_status()
            runs = runs_resp.json().get("workflow_runs", [])
        except httpx.HTTPError as e:
            logger.warning("Could not get workflow runs for %s: %s", repo_name, e)
            return []

        for run in runs:
            run_id = run["id"]
            
            # Fetch jobs for the run
            try:
                jobs_resp = self._client.get(f"/repos/{repo_name}/actions/runs/{run_id}/jobs")
                jobs_resp.raise_for_status()
                run_jobs = jobs_resp.json().get("jobs", [])
            except httpx.HTTPError as e:
                logger.debug("Could not get jobs for run %s: %s", run_id, e)
                continue

            # Fetch log for each job 
            # Note: GitHub API direct job log retrieval might redirect or return plain text
            for r_job in run_jobs:
                job_id = r_job["id"]
                try:
                    log_resp = self._client.get(f"/repos/{repo_name}/actions/jobs/{job_id}/logs")
                    # GitHub API for logs returns 302 redirect or logs directly if plain text
                    # Depending on httpx configuration, it follows redirects automatically.
                    log_resp.raise_for_status()
                    raw_log = log_resp.text

                    duration_ms = None
                    if r_job.get("started_at") and r_job.get("completed_at"):
                        # Basic duration parsing could go here, omitting for simplicity
                        pass

                    logs.append(BuildLog(
                        job_name=f"{repo_name}/{r_job['name']}",
                        build_number=run_id,
                        raw_log=raw_log,
                        status=r_job.get("conclusion", r_job.get("status", "unknown")),
                        duration_ms=duration_ms,
                        timestamp=r_job.get("started_at"),
                    ))
                except httpx.HTTPError as e:
                    logger.debug("Skipping log for job %s: %s", job_id, e)
                    continue

        logger.info("Fetched %d build logs for %s.", len(logs), repo_name)
        return logs

    def fetch_doc_files(self) -> list[DocFileEntry]:
        """Detect documentation files across accessible GitHub repositories."""
        if not self._client:
            raise RuntimeError("Not connected. Call connect() first.")

        doc_files: list[DocFileEntry] = []
        
        try:
            resp = self._client.get("/user/repos", params={"per_page": min(100, self.config.max_jobs)})
            resp.raise_for_status()
            repos = resp.json()
        except httpx.HTTPError:
            return []

        for i, repo in enumerate(repos):
            if i >= self.config.max_jobs:
                break
                
            repo_name = repo["full_name"]
            if not self._matches_filter(repo_name):
                continue

            for file_pattern, doc_type in _DOC_PATTERNS:
                try:
                    # Fetch file metadata
                    f_resp = self._client.get(f"/repos/{repo_name}/contents/{file_pattern}")
                    
                    if f_resp.status_code == 404:
                        continue
                        
                    f_resp.raise_for_status()
                    
                    # For a directory (like docs), GitHub API returns a list
                    data = f_resp.json()
                    if isinstance(data, list):
                        # For directories just record the path without content
                        doc_files.append(DocFileEntry(
                            path=f"{repo_name}/{file_pattern}",
                            content="[Directory Map omitted]",
                            detected_type=doc_type,
                        ))
                    else:
                        content = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
                        doc_files.append(DocFileEntry(
                            path=f"{repo_name}/{file_pattern}",
                            content=content,
                            detected_type=doc_type,
                        ))
                except httpx.HTTPError:
                    continue

        logger.info("Detected %d documentation files from GitHub.", len(doc_files))
        return doc_files
