"""CI/CD platform connectors."""

from atlas_scanner.connectors.base import (  # noqa: F401
    BaseConnector,
    BuildLog,
    DocFileEntry,
    PipelineConfig,
)
from atlas_scanner.connectors.gitlab import GitLabConnector  # noqa: F401
from atlas_scanner.connectors.jenkins import JenkinsConnector  # noqa: F401
