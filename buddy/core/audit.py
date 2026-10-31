"""Rotating local metadata-only audit trail. Never log transcripts, audio or keys."""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler

from buddy.core.config import Config
from buddy.core.errors import ConfigurationError


class AuditLog:
    def __init__(self, config: Config) -> None:
        self._logger = logging.getLogger(f"buddy.audit.{uuid.uuid4().hex}")
        self._logger.setLevel(logging.INFO)
        self._logger.propagate = False
        self._handler: RotatingFileHandler | None = None
        if config.logging.enabled:
            try:
                directory = config.data_dir / "logs"
                directory.mkdir(parents=True, exist_ok=True, mode=0o700)
                path = directory / "actions.jsonl"
                descriptor = os.open(path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
                os.close(descriptor)
                os.chmod(path, 0o600)
                self._handler = RotatingFileHandler(
                    path,
                    maxBytes=config.logging.max_bytes,
                    backupCount=config.logging.backups,
                    encoding="utf-8",
                )
                self._logger.addHandler(self._handler)
            except OSError:
                raise ConfigurationError(
                    "Cannot create the local audit log; check BUDDY_DATA_DIR."
                ) from None

    def record(self, event: str, **metadata: str | int | float | bool) -> None:
        allowed = {"state", "provider", "characters", "duration_ms", "error_type", "source", "ok"}
        safe = {key: value for key, value in metadata.items() if key in allowed}
        self._logger.info(
            json.dumps(
                {
                    "time": datetime.now(UTC).isoformat(),
                    "event": event,
                    **safe,
                },
                ensure_ascii=False,
            )
        )

    def close(self) -> None:
        if self._handler:
            self._logger.removeHandler(self._handler)
            self._handler.close()
