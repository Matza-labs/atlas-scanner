# atlas-scanner

Scanner Agent for **PipelineAtlas** — runs inside the customer environment.

## Purpose

Connects to CI/CD platforms via read-only API tokens, fetches pipeline definitions, build logs, and metadata, then publishes raw scan data to Redis Streams for downstream processing.

## Supported Platforms

| Platform | Status |
|----------|--------|
| Jenkins | ✅ Completed |
| GitLab CI | ✅ Completed |
| GitHub Actions | 🟡 Phase 2 |

## Key Features

- **Read-only access** — never modifies pipelines or repos
- **Pluggable connectors** — abstract base class, one connector per CI platform
- **Log sanitization** — strips ANSI, redacts secrets before publishing
- **Configurable scope** — select which jobs/projects to scan, log depth
- **Multiple deployment modes** — Docker, Kubernetes pod, VM process, on-prem

## Dependencies

- `atlas-sdk` (shared models)
- `redis` (Redis Streams publishing)
- `python-jenkins` (Jenkins API)
- `python-gitlab` (GitLab API)

## Related Services

Publishes to → `atlas-parser`, `atlas-log-analyzer` (via Redis Streams)
