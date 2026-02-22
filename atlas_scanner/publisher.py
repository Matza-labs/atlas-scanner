"""Redis Streams publisher for scan results.

Publishes ScanResultEvent to the `atlas.scan.results` stream for
downstream consumption by atlas-parser and atlas-log-analyzer.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from atlas_sdk.events import ScanResultEvent

logger = logging.getLogger(__name__)

STREAM_SCAN_RESULTS = "atlas.scan.results"


class Publisher:
    """Publishes events to Redis Streams."""

    def __init__(self, redis_url: str = "redis://localhost:6379") -> None:
        self._redis_url = redis_url
        self._client: Any = None

    def connect(self) -> None:
        """Connect to Redis.

        Raises:
            ConnectionError: If Redis is unreachable.
        """
        try:
            import redis
        except ImportError as e:
            raise ImportError("redis is required: pip install redis") from e

        try:
            self._client = redis.from_url(self._redis_url, decode_responses=True)
            self._client.ping()
            logger.info("Connected to Redis at %s", self._redis_url)
        except Exception as e:
            raise ConnectionError(f"Failed to connect to Redis: {e}") from e

    def publish_scan_result(self, event: ScanResultEvent) -> str:
        """Publish a ScanResultEvent to Redis Streams.

        Args:
            event: The scan result to publish.

        Returns:
            The Redis message ID.
        """
        if not self._client:
            raise RuntimeError("Not connected. Call connect() first.")

        data = event.model_dump(mode="json")
        message_id = self._client.xadd(
            STREAM_SCAN_RESULTS,
            {"data": json.dumps(data)},
        )
        logger.info(
            "Published scan result %s to %s (msg: %s)",
            event.event_id,
            STREAM_SCAN_RESULTS,
            message_id,
        )
        return str(message_id)

    def close(self) -> None:
        """Close the Redis connection."""
        if self._client:
            self._client.close()
            self._client = None
