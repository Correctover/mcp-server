# Copyright 2024-2025 Correctover Team
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""Structured JSON logging configuration for Correctover SDK.

Enterprise requirement: all logs must be machine-parseable (JSON format).
Set CORRECTOVER_LOG_FORMAT=text to revert to human-readable output.
"""

import json
import logging
import os
import sys
import time


class JSONFormatter(logging.Formatter):
    """Formats log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        # Include any extra fields
        if hasattr(record, "nb_provider"):
            log_entry["provider"] = record.nb_provider
        if hasattr(record, "nb_model"):
            log_entry["model"] = record.nb_model
        if hasattr(record, "nb_phase"):
            log_entry["mapek_phase"] = record.nb_phase
        if hasattr(record, "nb_fault"):
            log_entry["fault_category"] = record.nb_fault
        if hasattr(record, "nb_action"):
            log_entry["recovery_action"] = record.nb_action
        if hasattr(record, "nb_latency_ms"):
            log_entry["latency_ms"] = record.nb_latency_ms
        if record.exc_info and record.exc_info[0] is not None:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry, ensure_ascii=False)


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """Configure structured JSON logging for Correctover.

    Set CORRECTOVER_LOG_FORMAT=text for human-readable output (dev mode).
    Set CORRECTOVER_LOG_LEVEL=DEBUG for debug output.
    """
    log_format = os.environ.get("CORRECTOVER_LOG_FORMAT", "json")
    log_level_str = os.environ.get("CORRECTOVER_LOG_LEVEL", "INFO")
    log_level = getattr(logging, log_level_str.upper(), level)

    logger = logging.getLogger("correctover")
    logger.setLevel(log_level)

    # Remove existing handlers
    logger.handlers.clear()

    handler = logging.StreamHandler(sys.stderr)

    if log_format == "text":
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        ))
    else:
        handler.setFormatter(JSONFormatter())

    logger.addHandler(handler)
    return logger


def get_logger(name: str = "correctover") -> logging.Logger:
    """Get a Correctover logger with structured JSON output."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        setup_logging()
    return logger
