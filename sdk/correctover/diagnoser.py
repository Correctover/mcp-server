# Copyright 2024-2025 Correctover Team
# Licensed under the Apache License, Version 2.0 (the "License");
# Correctover™ — Proprietary MAPE-K Adaptive Loop Architecture

#
"""Correctover — L1 Diagnoser module.

Semantic boundary: identify fault only, output label, NO action.

This module re-exports the canonical Diagnoser from _engine.py for
backward compatibility. All logic lives in a single source of truth.
"""

# Canonical source of truth: _engine.py
from ._engine import (
    FaultCategory,
    Diagnosis,
    Diagnoser,
    _STATUS_MAP as STATUS_MAP,
    _DECISION as DECISION,
    _PATTERNS as PATTERNS,
    _COMPILED as COMPILED,
)

# Version: import from package __init__ for consistency
try:
    from correctover import __version__
except ImportError:
    __version__ = "4.4.2"

__all__ = [
    "FaultCategory", "Diagnosis", "Diagnoser",
    "STATUS_MAP", "DECISION", "PATTERNS", "COMPILED",
]
