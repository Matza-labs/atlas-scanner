"""Unit tests for GitHubConnector."""

import base64
from unittest.mock import MagicMock, patch

import httpx
import pytest

from atlas_sdk.enums import Platform
from atlas_scanner.config import ScanConfig
from atlas_scanner.connectors.github import GitHubConnector


@pytest.fixture
def config():
    return ScanConfig(
        platform=Platform.GITHUB_ACTIONS,
        target_url="https://github.com",
        api_token="ghp_mocktoken",
        job_filter=["*"],
    )


class TestGitHubConnector:

    @patch("atlas_scanner.connectors.github.httpx.Client")
    def test_connect_success(self, mock_client_cls, config):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"login": "testuser"}
        mock_client.get.return_value = mock_resp

        connector = GitHubConnector(config)
        connector.connect()

        mock_client.get.assert_called_once_with("/user")
        assert connector._client is not None

    @patch("atlas_scanner.connectors.github.httpx.Client")
    def test_connect_failure(self, mock_client_cls, config):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.get.side_effect = httpx.HTTPError("Failed")

        connector = GitHubConnector(config)
        with pytest.raises(ConnectionError):
            connector.connect()

    def test_fetch_pipeline_configs(self, config):
        connector = GitHubConnector(config)
        connector._client = MagicMock()

        # Mock /user/repos
        mock_repos_resp = MagicMock()
        mock_repos_resp.status_code = 200
        mock_repos_resp.json.return_value = [
            {"full_name": "org/repo1", "default_branch": "main", "id": 123},
        ]

        # Mock /contents/.github/workflows
        mock_files_resp = MagicMock()
        mock_files_resp.status_code = 200
        mock_files_resp.json.return_value = [
            {"name": "build.yml", "html_url": "https://url"},
        ]

        # Mock specific file content
        mock_file_resp = MagicMock()
        mock_file_resp.status_code = 200
        mock_file_resp.json.return_value = {
            "content": base64.b64encode(b"name: CI").decode("utf-8")
        }

        connector._client.get.side_effect = [
            mock_repos_resp,
            mock_files_resp,
            mock_file_resp,
        ]

        configs = connector.fetch_pipeline_configs()

        assert len(configs) == 1
        assert configs[0].job_name == "org/repo1: build.yml"
        assert configs[0].content == "name: CI"
        assert configs[0].platform == Platform.GITHUB_ACTIONS

    def test_fetch_build_logs(self, config):
        connector = GitHubConnector(config)
        connector._client = MagicMock()

        # Mock /actions/runs
        mock_runs_resp = MagicMock()
        mock_runs_resp.json.return_value = {
            "workflow_runs": [{"id": 42}]
        }

        # Mock /actions/runs/42/jobs
        mock_jobs_resp = MagicMock()
        mock_jobs_resp.json.return_value = {
            "jobs": [{"id": 100, "name": "build", "status": "completed", "conclusion": "success"}]
        }

        # Mock /actions/jobs/100/logs
        mock_log_resp = MagicMock()
        mock_log_resp.text = "Step 1\nStep 2"
        
        connector._client.get.side_effect = [
            mock_runs_resp,
            mock_jobs_resp,
            mock_log_resp,
        ]

        logs = connector.fetch_build_logs("org/repo1")
        assert len(logs) == 1
        assert logs[0].job_name == "org/repo1/build"
        assert logs[0].raw_log == "Step 1\nStep 2"
        assert logs[0].status == "success"
