# Copyright 2024-2025 Correctover Team
# Licensed under the Apache License, Version 2.0 (the "License")
# Correctover™ — Proprietary MAPE-K Adaptive Loop Architecture

#
"""Correctover SDK — Runtime patches for compiled module bugs.

This module applies monkey-patches to fix bugs in the compiled Cython
_engine.so that cannot be fixed at source level without recompilation.

Patches applied:
  1. Contract._validate_similarity — Fix Jaccard calculation (was only
     returning 1.0 for exact word-set matches, 0.0 for everything else)
  2. Contract.validate — Delegate similarity to fixed implementation
  3. SelfHealingEngine.call — Fix contract_result and validation_passed
     not being populated in CallResult

These patches are applied at import time and are transparent to users.
"""
import json as _json


def _apply_patches():
    """Apply all runtime patches to the compiled _engine module."""
    from correctover._engine import (
        Contract, ContractCheck, ContractResult,
        SelfHealingEngine, CallResult, SemanticDomain,
        ContractViolationError,
    )

    # ── Patch 1: Fix Jaccard similarity calculation ────────────────
    #
    # Bug: The compiled _validate_similarity always returns jaccard=1.0
    # when word sets are identical, and 0.0 for everything else.
    # This makes similarity validation useless for real-world outputs
    # that are similar but not word-for-word identical.
    #
    # Fix: Correct Jaccard = |A ∩ B| / |A ∪ B|

    _original_validate = Contract.validate

    def _fixed_validate_similarity(self, output: str) -> ContractCheck:
        """Fixed Jaccard word-level similarity validation."""
        if not output or not output.strip():
            return ContractCheck(
                strategy="similarity",
                passed=False,
                detail="empty_text",
            )

        threshold = self.similarity_threshold
        reference = self.reference_text

        if not reference or not reference.strip():
            return ContractCheck(
                strategy="similarity",
                passed=True,
                detail="no_reference",
            )

        # Tokenize: lowercase, split on whitespace, remove punctuation
        import re
        def _tokenize(text):
            # Strip markdown/formatting, lowercase, split
            clean = re.sub(r'[^\w\s]', '', text.lower())
            return set(clean.split())

        ref_tokens = _tokenize(reference)
        out_tokens = _tokenize(output)

        if not ref_tokens or not out_tokens:
            return ContractCheck(
                strategy="similarity",
                passed=False,
                detail="empty_tokens",
            )

        # Use composite similarity score:
        # 1. Jaccard = |A ∩ B| / |A ∪ B| (symmetric, penalizes length mismatch)
        # 2. Containment = |A ∩ B| / |A| (how much of reference is covered)
        # Final score = max(jaccard, containment) — containment is more practical
        # for LLM outputs where responses are typically longer than references
        intersection = ref_tokens & out_tokens
        union = ref_tokens | out_tokens
        jaccard = len(intersection) / len(union) if union else 0.0
        containment = len(intersection) / len(ref_tokens) if ref_tokens else 0.0
        score = max(jaccard, containment)

        passed = score >= threshold
        return ContractCheck(
            strategy="similarity",
            passed=passed,
            detail=f"jaccard={jaccard:.3f} containment={containment:.3f} score={score:.3f} threshold={threshold}",
        )

    def _patched_validate(self, output: str) -> ContractResult:
        """Patched validate() that uses fixed Jaccard for similarity."""
        checks = []

        # Schema validation (delegate to original compiled code)
        if self.output_schema:
            checks.append(self._validate_schema(output))

        # Determinism hash validation (delegate to original)
        if self.determinism_hash:
            checks.append(self._validate_determinism(output))

        # Similarity validation (USE FIXED VERSION)
        if self.similarity_threshold is not None and self.reference_text:
            checks.append(_fixed_validate_similarity(self, output))

        # Entity validation (delegate to original)
        if self.required_entities:
            checks.append(self._validate_entities(output))

        # Forbidden patterns (delegate to original)
        if self.forbidden_patterns:
            checks.append(self._validate_forbidden(output))

        # Determine overall result
        passed = all(c.passed for c in checks) if checks else True
        contract_type = "multi" if len(checks) > 1 else (
            checks[0].strategy if checks else "none"
        )

        return ContractResult(
            passed=passed,
            checks=checks,
            contract_type=contract_type,
        )

    # Apply the validate patch
    Contract.validate = _patched_validate

    # ── Patch 2: Fix contract_result in engine.call() ──────────────
    #
    # Bug: engine.call() returns CallResult with contract_result=None
    # and validation_passed=None even when a Contract is provided.
    #
    # Fix: Wrap engine.call() to post-validate and fill the fields.

    _original_call = SelfHealingEngine.call

    async def _patched_call(self, prompt, *args, **kwargs):
        """Patched call() that properly populates contract_result.

        Uses *args/**kwargs to avoid signature mismatch with call_sync()
        which passes model/task_type/etc. as positional args.
        """
        result = await _original_call(self, prompt, *args, **kwargs)

        # Extract contract from kwargs if provided
        contract = kwargs.get("contract")

        # If contract was provided but result wasn't validated, do it now
        if contract is not None and result.contract_result is None and result.text:
            contract_result = contract.validate(result.text)
            semantic_domain = result.semantic_domain
            # We can't modify CallResult (it's a compiled dataclass),
            # so we create a new one with the fixed fields
            try:
                new_result = CallResult(
                    text=result.text,
                    provider=result.provider,
                    model=result.model,
                    success=result.success,
                    fault=result.fault,
                    original_provider=result.original_provider,
                    original_model=result.original_model,
                    latency_ms=result.latency_ms,
                    from_cache=result.from_cache,
                    downgraded=result.downgraded,
                    heal_level=result.heal_level,
                    semantic_domain=semantic_domain,
                    validation_passed=contract_result.passed,
                    contract_result=contract_result.to_dict() if hasattr(contract_result, 'to_dict') else None,
                    mapek_trace=result.mapek_trace,
                    raw_response=result.raw_response,
                )
                # Handle STRONG_EQUIVALENCE + contract fail → raise error
                if (semantic_domain == SemanticDomain.STRONG_EQUIVALENCE
                        and not contract_result.passed
                        and result.success):
                    raise ContractViolationError(
                        f"Contract validation failed in STRONG_EQUIVALENCE domain: "
                        f"{[c.detail for c in contract_result.checks if not c.passed]}"
                    )
                return new_result
            except TypeError:
                # CallResult constructor doesn't match expected signature
                # Fall back to setting attributes directly
                try:
                    object.__setattr__(result, 'validation_passed', contract_result.passed)
                    object.__setattr__(result, 'contract_result',
                                       contract_result.to_dict() if hasattr(contract_result, 'to_dict') else None)
                except (TypeError, AttributeError):
                    pass  # Compiled dataclass may not allow attribute setting

        return result

    SelfHealingEngine.call = _patched_call


# Apply patches on import
try:
    _apply_patches()
except Exception as e:
    import sys
    print(f"[Correctover] Warning: patch application failed: {e}", file=sys.stderr)
