"""Unit tests for atlas-scanner."""

from unittest.mock import MagicMock, patch

import pytest

from atlas_sdk.enums import Platform

from atlas_scanner.config import ScanConfig
from atlas_scanner.connectors.base import BuildLog, DocFileEntry, PipelineConfig
from atlas_scanner.sanitizer import redact_secrets, sanitize_log, strip_ansi


# ── ScanConfig tests ─────────────────────────────────────────────────


class TestScanConfig:
    def test_default_config(self):
        config = ScanConfig(
            platform=Platform.JENKINS,
            target_url="https://jenkins.example.com",
        )
        assert config.platform == Platform.JENKINS
        assert config.log_depth == 5
        assert config.job_filter == ["*"]
        assert config.verify_ssl is True

    def test_resolve_token_from_env(self):
        config = ScanConfig(
            platform=Platform.JENKINS,
            target_url="https://jenkins.example.com",
            token_ref="MY_TOKEN",
        )
        with patch.dict("os.environ", {"MY_TOKEN": "secret123"}):
            assert config.resolve_token() == "secret123"

    def test_resolve_token_missing_env(self):
        config = ScanConfig(
            platform=Platform.JENKINS,
            target_url="https://jenkins.example.com",
            token_ref="MISSING_VAR",
        )
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ValueError, match="MISSING_VAR"):
                config.resolve_token()

    def test_resolve_empty_token_ref(self):
        config = ScanConfig(
            platform=Platform.JENKINS,
            target_url="https://jenkins.example.com",
        )
        assert config.resolve_token() == ""


# ── Sanitizer tests ──────────────────────────────────────────────────


class TestSanitizer:
    def test_strip_ansi_colors(self):
        text = "\x1b[31mERROR\x1b[0m: build failed"
        assert strip_ansi(text) == "ERROR: build failed"

    def test_strip_ansi_bold(self):
        text = "\x1b[1mBuild\x1b[0m started"
        assert strip_ansi(text) == "Build started"

    def test_strip_ansi_multi(self):
        text = "\x1b[32m[Pipeline]\x1b[0m \x1b[34mstage\x1b[0m"
        assert strip_ansi(text) == "[Pipeline] stage"

    def test_no_ansi_passthrough(self):
        text = "Just plain text"
        assert strip_ansi(text) == text

    def test_redact_password(self):
        text = "Connecting with password=MyS3cretP@ss!"
        result = redact_secrets(text)
        assert "MyS3cretP@ss" not in result
        assert "***REDACTED***" in result

    def test_redact_token(self):
        text = "Using token=ghp_abc123def456ghi789jkl0"
        result = redact_secrets(text)
        assert "ghp_abc123def456ghi789jkl0" not in result

    def test_redact_aws_key(self):
        text = "Found key AKIAIOSFODNN7EXAMPLE"
        result = redact_secrets(text)
        assert "AKIAIOSFODNN7EXAMPLE" not in result

    def test_redact_github_pat(self):
        text = "ghp_ABCDEFghijklmnopqrstuvwxyz0123456789"
        result = redact_secrets(text)
        assert "ghp_" not in result

    def test_redact_gitlab_pat(self):
        text = "glpat-abc123-def456-ghi789"
        result = redact_secrets(text)
        assert "glpat-" not in result

    def test_redact_bearer_token(self):
        text = "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig"
        result = redact_secrets(text)
        assert "eyJhbGci" not in result

    def test_redact_api_key_value(self):
        text = "api_key=sk-12345abcde"
        result = redact_secrets(text)
        assert "sk-12345abcde" not in result

    def test_no_secrets_passthrough(self):
        text = "Building project at /home/user/app"
        assert redact_secrets(text) == text

    def test_full_sanitize(self):
        raw = "\x1b[32m[INFO]\x1b[0m Deploy with token=secret123"
        result = sanitize_log(raw)
        assert "\x1b[" not in result
        assert "secret123" not in result
        assert "[INFO]" in result
        assert "***REDACTED***" in result


# ── Data class tests ─────────────────────────────────────────────────


class TestDataClasses:
    def test_pipeline_config(self):
        pc = PipelineConfig(
            job_name="my-pipeline",
            path="Jenkinsfile",
            content="pipeline { }",
            platform=Platform.JENKINS,
            job_type="pipeline",
        )
        assert pc.job_name == "my-pipeline"
        assert pc.platform == Platform.JENKINS

    def test_build_log(self):
        log = BuildLog(
            job_name="build",
            build_number=42,
            raw_log="Building...",
            status="SUCCESS",
        )
        assert log.build_number == 42
        assert log.status == "SUCCESS"

    def test_doc_file_entry(self):
        doc = DocFileEntry(
            path="README.md",
            content="# My Project",
            detected_type="readme",
        )
        assert doc.detected_type == "readme"


# ── Connector filter tests ───────────────────────────────────────────


class TestConnectorFilter:
    def _make_connector(self, job_filter: list[str]):
        """Create a mock connector to test filtering."""
        from atlas_scanner.connectors.base import BaseConnector

        config = ScanConfig(
            platform=Platform.JENKINS,
            target_url="https://jenkins.example.com",
            job_filter=job_filter,
        )

        # Create a concrete subclass for testing
        class MockConnector(BaseConnector):
            def connect(self): pass
            def fetch_pipeline_configs(self): return []
            def fetch_build_logs(self, j, d=None): return []
            def fetch_doc_files(self): return []

        return MockConnector(config)

    def test_wildcard_matches_all(self):
        c = self._make_connector(["*"])
        assert c._matches_filter("anything")

    def test_exact_match(self):
        c = self._make_connector(["my-job"])
        assert c._matches_filter("my-job")
        assert not c._matches_filter("other-job")

    def test_glob_match(self):
        c = self._make_connector(["deploy-*"])
        assert c._matches_filter("deploy-prod")
        assert c._matches_filter("deploy-staging")
        assert not c._matches_filter("build-main")

    def test_multiple_filters(self):
        c = self._make_connector(["build-*", "deploy-prod"])
        assert c._matches_filter("build-main")
        assert c._matches_filter("deploy-prod")
        assert not c._matches_filter("test-unit")


# ── Scanner orchestrator tests ───────────────────────────────────────


class TestScanner:
    def test_scanner_unsupported_platform(self):
        from atlas_scanner.scanner import Scanner

        config = ScanConfig(
            platform=Platform.GITHUB_ACTIONS,
            target_url="https://github.com",
        )
        scanner = Scanner(config, publish=False)
        with pytest.raises(ValueError, match="Unsupported platform"):
            scanner.run()

    def test_scanner_with_mock_connector(self):
        """Test the full scan flow with a mocked connector."""
        from atlas_scanner.scanner import CONNECTOR_MAP, Scanner

        config = ScanConfig(
            platform=Platform.JENKINS,
            target_url="https://jenkins.example.com",
            token_ref="",
        )

        # Mock connector
        mock_connector = MagicMock()
        mock_connector.fetch_pipeline_configs.return_value = [
            PipelineConfig(
                job_name="test-job",
                path="Jenkinsfile",
                content="pipeline { stages { stage('Build') { steps { sh 'make' } } } }",
                platform=Platform.JENKINS,
                job_type="pipeline",
            )
        ]
        mock_connector.fetch_build_logs.return_value = [
            BuildLog(
                job_name="test-job",
                build_number=1,
                raw_log="\x1b[32m[INFO]\x1b[0m Build with token=secret123",
                status="SUCCESS",
            )
        ]
        mock_connector.fetch_doc_files.return_value = []

        # Patch connector creation
        mock_cls = MagicMock(return_value=mock_connector)
        original = CONNECTOR_MAP.get(Platform.JENKINS)

        try:
            CONNECTOR_MAP[Platform.JENKINS] = mock_cls
            scanner = Scanner(config, publish=False)
            result = scanner.run()

            assert result.platform == Platform.JENKINS
            assert len(result.pipeline_configs) == 1
            assert len(result.build_logs) == 1
            # Verify logs were sanitized
            assert "secret123" not in result.build_logs[0]["log"]
            assert "\x1b[" not in result.build_logs[0]["log"]
            assert "***REDACTED***" in result.build_logs[0]["log"]
        finally:
            if original:
                CONNECTOR_MAP[Platform.JENKINS] = original
