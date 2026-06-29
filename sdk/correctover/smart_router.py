# Copyright 2024-2025 Correctover Team
# Licensed under the Apache License, Version 2.0 (the "License");
# Correctover™ — Proprietary MAPE-K Adaptive Loop Architecture

#
"""Correctover v4.4.2 — Smart Router (backward compatibility).

Smart routing is integrated into SelfHealingEngine.
This module re-exports the engine for compatibility.
"""
from ._engine import SelfHealingEngine as SmartRouter, ProviderConfig, FaultCategory

__all__ = ["SmartRouter", "ProviderConfig", "FaultCategory"]
