"""
Shared utilities for standalone CLI entrypoints consumed by n8n.

stdout is reserved for the final JSON payload. All progress and diagnostics go
to stderr via logging so workflow engines can parse the output safely.
"""
from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass
from datetime import datetime
from time import perf_counter
from typing import Any, Callable


class RecoverableCLIError(Exception):
    """Operational problem that can be retried or handled by the caller."""


@dataclass
class CLIResult:
    status: str
    command: str
    started_at: str
    finished_at: str
    duration_seconds: float
    summary: dict[str, Any]
    warnings: list[str]
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "command": self.command,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_seconds": self.duration_seconds,
            "summary": self.summary,
            "warnings": self.warnings,
            "error": self.error,
        }


def build_stderr_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


def emit_json(result: CLIResult) -> None:
    print(json.dumps(result.to_dict(), ensure_ascii=False))


def run_cli_job(
    command: str,
    handler: Callable[[logging.Logger], tuple[dict[str, Any], list[str]]],
) -> int:
    logger = build_stderr_logger(command)
    started_at = datetime.now().isoformat(timespec="seconds")
    start = perf_counter()
    try:
        summary, warnings = handler(logger)
        emit_json(
            CLIResult(
                status="ok",
                command=command,
                started_at=started_at,
                finished_at=datetime.now().isoformat(timespec="seconds"),
                duration_seconds=round(perf_counter() - start, 3),
                summary=summary,
                warnings=warnings,
            )
        )
        return 0
    except RecoverableCLIError as exc:
        logger.error(str(exc))
        emit_json(
            CLIResult(
                status="recoverable_error",
                command=command,
                started_at=started_at,
                finished_at=datetime.now().isoformat(timespec="seconds"),
                duration_seconds=round(perf_counter() - start, 3),
                summary={},
                warnings=[],
                error=str(exc),
            )
        )
        return 1
    except Exception as exc:
        logger.exception("Errore critico")
        emit_json(
            CLIResult(
                status="critical_error",
                command=command,
                started_at=started_at,
                finished_at=datetime.now().isoformat(timespec="seconds"),
                duration_seconds=round(perf_counter() - start, 3),
                summary={},
                warnings=[],
                error=str(exc),
            )
        )
        return 2
