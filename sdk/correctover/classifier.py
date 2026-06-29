# Copyright 2024-2026 Correctover Team
# Licensed under the Apache License, Version 2.0 (the "License")
#
"""Task complexity classifier — rule-based, no AI needed.

Classifies prompts into complexity tiers to route to appropriate models.
Zero dependency, sub-millisecond classification.
"""
import re
from enum import Enum
from typing import Optional


class Complexity(str, Enum):
    SIMPLE = "simple"
    MODERATE = "moderate"
    COMPLEX = "complex"


# Indicators of complex tasks
_COMPLEX_KEYWORDS = frozenset([
    "analyze", "analysis", "explain", "reasoning", "reason",
    "compare", "evaluate", "synthesize", "critique", "debate",
    "design", "architect", "implement", "refactor", "debug",
    "optimize", "algorithm", "complex", "derive", "prove",
    "math", "calculate", "compute", "solve", "equation",
    "phd", "academic", "research", "hypothesis", "experiment",
    "strateg", "forecast", "predict", "model", "simulation",
    "代码审查", "架构", "分析", "推理", "设计", "优化",
    "调试", "算法", "数学", "证明", "研究",
])

# Indicators of code/technical tasks
_CODE_INDICATORS = frozenset([
    "code", "function", "class", "method", "api", "sql", "query",
    "regex", "parse", "serialize", "compile", "deploy", "test",
    "debug", "error", "exception", "stack trace", "bug", "fix",
    "代码", "函数", "类", "接口", "调试", "错误", "修复",
])

# Simple task patterns
_SIMPLE_PATTERNS = [
    re.compile(r"^(translate|summarize|paraphrase|rewrite)\b", re.I),
    re.compile(r"^(hi|hello|hey|你好|您好)\b", re.I),
    re.compile(r"^(what is|define|who is|when was|where is)\b", re.I),
    re.compile(r"^(list|name|give me)\b", re.I),
    re.compile(r"(format|convert|change).*(json|yaml|csv|xml|markdown)", re.I),
]

# Moderate task patterns
_MODERATE_PATTERNS = [
    re.compile(r"(write|create|generate|draft)\b", re.I),
    re.compile(r"(extract|parse|pull|find).*(data|info|entity|key)", re.I),
    re.compile(r"(classify|categorize|label|tag)\b", re.I),
]


def classify(prompt: str, task_type: str = "") -> Complexity:
    """Classify a prompt's complexity. Rule-based, zero AI call.

    Args:
        prompt: The user prompt text.
        task_type: Optional task type hint (e.g. "extraction", "creative_writing").

    Returns:
        Complexity level: SIMPLE, MODERATE, or COMPLEX.
    """
    if not prompt:
        return Complexity.SIMPLE

    text = prompt.strip()
    text_lower = text.lower()
    token_estimate = len(text.split())

    # Score-based classification
    score = 0

    # Task type hints override
    if task_type in ("creative_writing", "brainstorming"):
        return Complexity.MODERATE
    if task_type in ("extraction", "classification"):
        return Complexity.SIMPLE
    if task_type in ("summarization", "translation"):
        return Complexity.SIMPLE

    # Simple pattern match (strong signal for simple)
    is_simple_pattern = False
    for pat in _SIMPLE_PATTERNS:
        if pat.search(text_lower):
            is_simple_pattern = True
            break

    # Complex keyword match
    for kw in _COMPLEX_KEYWORDS:
        if kw in text_lower:
            score += 2
            break

    # Code indicator
    for kw in _CODE_INDICATORS:
        if kw in text_lower:
            score += 1
            break

    # Code blocks
    if "```" in text:
        score += 2

    # Long prompts
    if token_estimate > 500:
        score += 2
    elif token_estimate > 100:
        score += 1

    # Multi-step instructions
    if text_lower.count("\n") > 5 or text_lower.count(". ") > 4:
        score += 1

    # Moderate pattern match
    for pat in _MODERATE_PATTERNS:
        if pat.search(text_lower):
            score += 1
            break

    # Simple pattern overrides everything for short prompts
    if is_simple_pattern and score < 3:
        return Complexity.SIMPLE

    # Very short + no complex indicators = simple
    if token_estimate < 8 and score == 0:
        return Complexity.SIMPLE

    # Score thresholds
    if score >= 3:
        return Complexity.COMPLEX
    elif score >= 1:
        return Complexity.MODERATE
    else:
        return Complexity.SIMPLE


# Model tiers based on complexity
# Maps complexity → preferred model family (cheapest that can handle it)
COMPLEXITY_MODEL_MAP = {
    Complexity.SIMPLE: "mini",       # gpt-4o-mini, claude-3-5-haiku, deepseek-chat
    Complexity.MODERATE: "standard", # gpt-4o, claude-sonnet-4, deepseek-chat
    Complexity.COMPLEX: "premium",   # gpt-4o, claude-sonnet-4, deepseek-reasoner
}

# Cost per 1M tokens (input/output) — approximate, for routing decisions
MODEL_COSTS = {
    # OpenAI
    "gpt-4o": {"input": 2.50, "output": 10.00, "tier": "premium"},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60, "tier": "mini"},
    "gpt-3.5-turbo": {"input": 0.50, "output": 1.50, "tier": "mini"},
    # Anthropic
    "claude-sonnet-4": {"input": 3.00, "output": 15.00, "tier": "premium"},
    "claude-3-5-haiku": {"input": 0.80, "output": 4.00, "tier": "mini"},
    # DeepSeek
    "deepseek-chat": {"input": 0.27, "output": 1.10, "tier": "standard"},
    "deepseek-reasoner": {"input": 0.55, "output": 2.19, "tier": "premium"},
    # Google
    "gemini-2.0-flash": {"input": 0.10, "output": 0.40, "tier": "mini"},
    "gemini-1.5-pro": {"input": 1.25, "output": 5.00, "tier": "premium"},
    # DashScope
    "qwen-max": {"input": 0.40, "output": 1.20, "tier": "standard"},
    "qwen-plus": {"input": 0.08, "output": 0.20, "tier": "mini"},
    "qwen-turbo": {"input": 0.03, "output": 0.06, "tier": "mini"},
}

# Provider default models
PROVIDER_MODELS = {
    "openai": ["gpt-4o", "gpt-4o-mini", "gpt-3.5-turbo"],
    "anthropic": ["claude-sonnet-4", "claude-3-5-haiku"],
    "deepseek": ["deepseek-chat", "deepseek-reasoner"],
    "google": ["gemini-2.0-flash", "gemini-1.5-pro"],
    "dashscope": ["qwen-max", "qwen-plus", "qwen-turbo"],
}


def get_cost_per_token(model: str, token_type: str = "input") -> float:
    """Get cost per token for a model."""
    info = MODEL_COSTS.get(model)
    if not info:
        return 0.001  # default fallback
    return info[token_type] / 1_000_000


def get_model_tier(model: str) -> str:
    """Get the cost tier for a model."""
    info = MODEL_COSTS.get(model)
    return info["tier"] if info else "standard"
