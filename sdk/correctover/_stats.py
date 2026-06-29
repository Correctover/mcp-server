# Copyright 2024-2025 Correctover Team
# Licensed under the Apache License, Version 2.0 (the "License")
# Correctover™ — Proprietary MAPE-K Adaptive Loop Architecture

#
"""Correctover Usage Statistics & ROI Engine.

Purpose: 不是算积分消耗，而是给客户看ROI——
  "你付了¥699/年，这个月帮你避免了¥1269的停机损失"

Four counterfactual modes:
  1. Model price difference — savings from downgrade/fallback (hard numbers)
  2. Downtime savings — industry benchmark counterfactual
  3. Full traffic panorama — complete local ledger
  4. ROI vs license cost — prove the subscription pays for itself

All data stays LOCAL — never sent to our servers unless customer opts in.
Customer does nothing — SDK auto-records everything transparently.
"""

import json
import os
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, List, Any


# ── Model Price Table (USD per 1M tokens) ────────────────────────

MODEL_PRICES: Dict[str, Dict[str, float]] = {
    # OpenAI
    "gpt-4o":              {"input": 2.50,  "output": 10.00, "source": "openai.com/pricing"},
    "gpt-4o-mini":         {"input": 0.15,  "output": 0.60,  "source": "openai.com/pricing"},
    "gpt-4-turbo":         {"input": 10.00, "output": 30.00, "source": "openai.com/pricing"},
    "gpt-4":               {"input": 30.00, "output": 60.00, "source": "openai.com/pricing"},
    "gpt-3.5-turbo":       {"input": 0.50,  "output": 1.50,  "source": "openai.com/pricing"},
    "o1":                  {"input": 15.00, "output": 60.00, "source": "openai.com/pricing"},
    "o1-mini":             {"input": 3.00,  "output": 12.00, "source": "openai.com/pricing"},
    "o3-mini":             {"input": 1.10,  "output": 4.40,  "source": "openai.com/pricing"},
    # Anthropic
    "claude-3.5-sonnet":   {"input": 3.00,  "output": 15.00, "source": "anthropic.com/pricing"},
    "claude-3-opus":       {"input": 15.00, "output": 75.00, "source": "anthropic.com/pricing"},
    "claude-3-haiku":      {"input": 0.25,  "output": 1.25,  "source": "anthropic.com/pricing"},
    "claude-sonnet-4":     {"input": 3.00,  "output": 15.00, "source": "anthropic.com/pricing"},
    # DeepSeek
    "deepseek-chat":       {"input": 0.27,  "output": 1.10,  "source": "deepseek.com/pricing"},
    "deepseek-v3":         {"input": 0.27,  "output": 1.10,  "source": "deepseek.com/pricing"},
    "deepseek-r1":         {"input": 0.55,  "output": 2.19,  "source": "deepseek.com/pricing"},
    "deepseek-reasoner":   {"input": 0.55,  "output": 2.19,  "source": "deepseek.com/pricing"},
    # Google
    "gemini-2.0-flash":    {"input": 0.10,  "output": 0.40,  "source": "ai.google.dev/pricing"},
    "gemini-2.5-pro":      {"input": 1.25,  "output": 10.00, "source": "ai.google.dev/pricing"},
    "gemini-2.5-flash":    {"input": 0.15,  "output": 0.60,  "source": "ai.google.dev/pricing"},
    # Mistral
    "mistral-large":       {"input": 2.00,  "output": 6.00,  "source": "mistral.ai/pricing"},
    "mistral-medium":      {"input": 0.70,  "output": 2.10,  "source": "mistral.ai/pricing"},
    "mistral-small":       {"input": 0.20,  "output": 0.60,  "source": "mistral.ai/pricing"},
    # Qwen
    "qwen-max":            {"input": 1.60,  "output": 6.40,  "source": "aliyun.com/product/bailian"},
    "qwen-plus":           {"input": 0.40,  "output": 1.60,  "source": "aliyun.com/product/bailian"},
    "qwen-turbo":          {"input": 0.05,  "output": 0.20,  "source": "aliyun.com/product/bailian"},
    # Zhipu
    "glm-4":               {"input": 1.40,  "output": 1.40,  "source": "bigmodel.cn/pricing"},
    "glm-4-flash":         {"input": 0.10,  "output": 0.10,  "source": "bigmodel.cn/pricing"},
}

_PRICE_TABLE_UPDATED = "2026-06-02"


# ── Industry Benchmark: Manual Recovery Time ─────────────────────

DOWNTIME_BENCHMARKS: Dict[str, Dict[str, Any]] = {
    "RATE_LIMIT":     {"avg_minutes": 2,  "cost_per_minute_cny": 2.7, "desc": "429限流 → 手动降频/等待"},
    "AUTH_ERROR":     {"avg_minutes": 15, "cost_per_minute_cny": 2.7, "desc": "401 key失效 → 换key/联系团队"},
    "SERVER_ERROR":   {"avg_minutes": 5,  "cost_per_minute_cny": 2.7, "desc": "500 服务端错误 → 等恢复/切provider"},
    "TIMEOUT":        {"avg_minutes": 3,  "cost_per_minute_cny": 2.7, "desc": "超时 → 调参/重试"},
    "QUOTA_EXCEEDED": {"avg_minutes": 15, "cost_per_minute_cny": 2.7, "desc": "配额耗尽 → 充值/换账号"},
    "CONNECTION_ERROR":{"avg_minutes": 5,  "cost_per_minute_cny": 2.7, "desc": "网络错误 → 排查/切换"},
    "UNKNOWN":        {"avg_minutes": 5,  "cost_per_minute_cny": 2.7, "desc": "未知错误 → 通用处理"},
}


# ── Data Structures ──────────────────────────────────────────────

@dataclass
class CallRecord:
    """Single API call record."""
    timestamp: float
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    success: bool = True
    latency_ms: float = 0.0
    from_cache: bool = False
    downgraded: bool = False
    original_model: str = ""
    heal_level: str = ""
    fault_category: str = ""
    cost_usd: float = 0.0
    counterfactual_usd: float = 0.0


@dataclass
class ProtectionEvent:
    """A self-healing protection event."""
    timestamp: float
    action: str
    original_model: str = ""
    fallback_model: str = ""
    fault_category: str = ""
    failover_time_ms: float = 0.0
    savings_usd: float = 0.0
    downtime_saved_cny: float = 0.0


# ── Stats Engine ─────────────────────────────────────────────────

class StatsEngine:
    """Correctover ROI Statistics Engine.

    Purpose: prove the subscription pays for itself.
    "你付了¥699/年，本月避免¥1269停机损失，ROI = 4.2x"
    """

    def __init__(self, persist_path: Optional[str] = None):
        self._lock = threading.Lock()
        self._persist_path = persist_path or os.path.join(
            os.path.expanduser("~"), ".correctover", "stats.json"
        )
        self._call_records: List[CallRecord] = []
        self._protection_events: List[ProtectionEvent] = []
        self._start_time = time.time()
        self._load()

    # ── Recording ────────────────────────────────────────────────

    def record_call(self, result: Any) -> None:
        """Record an API call from a CallResult."""
        try:
            if isinstance(result, dict):
                provider = result.get("provider", "")
                model = result.get("model", "")
                input_tokens = result.get("input_tokens", 0)
                output_tokens = result.get("output_tokens", 0)
                success = result.get("success", True)
                latency_ms = result.get("latency_ms", 0.0)
                from_cache = result.get("from_cache", False)
                downgraded = result.get("downgraded", False)
                original_model = result.get("original_model", model)
                heal_level = result.get("heal_level", "")
            else:
                provider = getattr(result, "provider", "")
                model = getattr(result, "model", "")
                input_tokens = getattr(result, "input_tokens", 0)
                output_tokens = getattr(result, "output_tokens", 0)
                success = getattr(result, "success", True)
                latency_ms = getattr(result, "latency_ms", 0.0)
                from_cache = getattr(result, "from_cache", False)
                downgraded = getattr(result, "downgraded", False)
                original_model = getattr(result, "original_model", model)
                heal_level = getattr(result, "heal_level", "")

            cost_usd = self._compute_cost(model, input_tokens, output_tokens)
            counterfactual_usd = 0.0
            if downgraded and original_model and original_model != model:
                counterfactual_usd = self._compute_cost(original_model, input_tokens, output_tokens)
            else:
                counterfactual_usd = cost_usd

            record = CallRecord(
                timestamp=time.time(), provider=provider, model=model,
                input_tokens=input_tokens, output_tokens=output_tokens,
                success=success, latency_ms=latency_ms,
                from_cache=from_cache, downgraded=downgraded,
                original_model=original_model, heal_level=heal_level,
                fault_category="", cost_usd=cost_usd,
                counterfactual_usd=counterfactual_usd,
            )

            with self._lock:
                self._call_records.append(record)
                if len(self._call_records) > 10000:
                    self._call_records = self._call_records[-10000:]

            if len(self._call_records) % 100 == 0:
                self._persist()
        except Exception:
            pass

    def record_protection(
        self, action: str,
        original_model: str = "", fallback_model: str = "",
        fault_category: str = "", failover_time_ms: float = 0.0,
        input_tokens: int = 0, output_tokens: int = 0,
    ) -> None:
        """Record a self-healing protection event."""
        try:
            # Model price difference savings
            savings_usd = 0.0
            if original_model and fallback_model and original_model != fallback_model:
                original_cost = self._compute_cost(original_model, input_tokens, output_tokens)
                fallback_cost = self._compute_cost(fallback_model, input_tokens, output_tokens)
                savings_usd = max(0, original_cost - fallback_cost)

            # Downtime counterfactual
            downtime_saved_cny = 0.0
            if action in ("auto_retry", "model_fallback", "failover"):
                benchmark = DOWNTIME_BENCHMARKS.get(
                    fault_category, DOWNTIME_BENCHMARKS["UNKNOWN"]
                )
                downtime_saved_cny = (
                    benchmark["avg_minutes"] * benchmark["cost_per_minute_cny"]
                )

            event = ProtectionEvent(
                timestamp=time.time(), action=action,
                original_model=original_model, fallback_model=fallback_model,
                fault_category=fault_category,
                failover_time_ms=failover_time_ms,
                savings_usd=savings_usd,
                downtime_saved_cny=downtime_saved_cny,
            )

            with self._lock:
                self._protection_events.append(event)
                if len(self._protection_events) > 10000:
                    self._protection_events = self._protection_events[-10000:]
        except Exception:
            pass

    # ── Query API ────────────────────────────────────────────────

    def savings_report(self, period: Optional[str] = None) -> Dict[str, Any]:
        """Generate comprehensive savings report with ROI."""
        if period is None:
            period = time.strftime("%Y-%m")

        with self._lock:
            calls = [r for r in self._call_records
                     if time.strftime("%Y-%m", time.gmtime(r.timestamp)) == period]
            events = [e for e in self._protection_events
                      if time.strftime("%Y-%m", time.gmtime(e.timestamp)) == period]

        # Model distribution
        model_dist: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"requests": 0, "tokens": 0})
        for r in calls:
            model_dist[r.model]["requests"] += 1
            model_dist[r.model]["tokens"] += r.input_tokens + r.output_tokens

        # Protection events
        prot_counts: Dict[str, int] = defaultdict(int)
        total_savings_usd = 0.0
        total_downtime_saved_cny = 0.0
        for e in events:
            prot_counts[e.action] += 1
            total_savings_usd += e.savings_usd
            total_downtime_saved_cny += e.downtime_saved_cny

        # Counterfactual
        total_input = sum(r.input_tokens for r in calls)
        total_output = sum(r.output_tokens for r in calls)
        total_actual_cost = sum(r.cost_usd for r in calls)
        total_counterfactual_cost = sum(r.counterfactual_usd for r in calls)

        if_no_nb_model_cost = total_counterfactual_cost
        if total_counterfactual_cost == 0 and calls:
            if_no_nb_model_cost = self._compute_cost("gpt-4o", total_input, total_output)

        if_no_nb_downtime = total_downtime_saved_cny
        manual_retries = prot_counts.get("auto_retry", 0)
        if_no_nb_manual_retry = manual_retries * 2 * 0.5

        # ROI calculation
        from correctover.license import get_plan, PLAN_PRICES
        plan = get_plan()
        license_cost_cny = PLAN_PRICES.get(plan, 0)
        # Prorate annual cost to monthly
        monthly_license_cny = round(license_cost_cny / 12, 1) if license_cost_cny > 0 else 0

        cny_to_usd = 0.14
        total_saved_cny = (
            total_downtime_saved_cny
            + if_no_nb_manual_retry
            + (if_no_nb_model_cost - total_actual_cost) / cny_to_usd
        )

        roi = round(total_saved_cny / monthly_license_cny, 1) if monthly_license_cny > 0 else 0

        return {
            "period": period,
            "total_requests": len(calls),
            "total_tokens": {"input": total_input, "output": total_output, "total": total_input + total_output},
            "model_distribution": dict(model_dist),
            "protection_events": dict(prot_counts),
            "savings": {
                "model_difference_usd": round(total_savings_usd, 4),
                "downtime_saved_cny": round(total_downtime_saved_cny, 2),
                "manual_retry_saved_cny": round(if_no_nb_manual_retry, 2),
                "total_saved_cny": round(total_saved_cny, 2),
            },
            "counterfactual": {
                "if_no_nb": {
                    "all_original_model_cost_usd": round(if_no_nb_model_cost, 4),
                    "downtime_cost_cny": round(if_no_nb_downtime, 2),
                    "manual_retry_cost_cny": round(if_no_nb_manual_retry, 2),
                    "total_loss_cny": round(if_no_nb_downtime + if_no_nb_manual_retry, 2),
                },
                "with_nb": {
                    "actual_cost_usd": round(total_actual_cost, 4),
                    "actual_downtime_cny": 0.0,
                    "protection_events": sum(prot_counts.values()),
                },
            },
            "roi": {
                "license_plan": plan,
                "annual_cost_cny": license_cost_cny,
                "monthly_cost_cny": monthly_license_cny,
                "monthly_saved_cny": round(total_saved_cny, 2),
                "roi_ratio": f"{roi}x",
                "verdict": "值了" if roi >= 1 else "还在回本中" if roi > 0 else "需要更多数据",
            },
            "price_table_updated": _PRICE_TABLE_UPDATED,
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

    def console_summary(self) -> str:
        """One-line console output for real-time display."""
        with self._lock:
            if not self._protection_events:
                return ""
            last = self._protection_events[-1]

        parts = []
        if last.savings_usd > 0:
            parts.append(f"模型差价省${last.savings_usd:.4f}")
        if last.downtime_saved_cny > 0:
            parts.append(f"停机省¥{last.downtime_saved_cny:.1f}")
        if last.failover_time_ms > 0:
            parts.append(f"自愈{last.failover_time_ms:.0f}ms")

        if not parts:
            return ""

        action_cn = {
            "diagnosis": "诊断", "auto_retry": "重试",
            "model_fallback": "降级切换", "failover": "Failover",
            "cache_hit": "缓存命中",
        }.get(last.action, last.action)

        return f"[NB {action_cn}] {' | '.join(parts)}"

    def dashboard_data(self) -> Dict[str, Any]:
        """Data for nb-doctor terminal dashboard."""
        report = self.savings_report()

        with self._lock:
            recent = [
                {
                    "time": time.strftime("%H:%M:%S", time.gmtime(e.timestamp)),
                    "action": e.action,
                    "savings_usd": round(e.savings_usd, 4),
                    "downtime_cny": round(e.downtime_saved_cny, 2),
                }
                for e in self._protection_events[-10:]
            ]

        return {
            "savings_this_month": report["savings"],
            "roi": report["roi"],
            "total_requests": report["total_requests"],
            "protection_events": report["protection_events"],
            "recent_events": recent,
        }

    def weekly_summary(self) -> str:
        """Weekly email summary markdown."""
        report = self.savings_report()
        lines = [
            f"# Correctover 周报 — {time.strftime('%Y-%m-%d')}",
            "",
            f"## 本月概览",
            f"- API请求: {report['total_requests']}",
            f"- 保护事件: {sum(report['protection_events'].values())}",
            "",
            f"## 省钱效果",
            f"- 模型差价: ${report['savings']['model_difference_usd']}",
            f"- 停机避免: ¥{report['savings']['downtime_saved_cny']}",
            f"- 总节省: ¥{report['savings']['total_saved_cny']}",
            "",
            f"## ROI",
            f"- 月费: ¥{report['roi']['monthly_cost_cny']}",
            f"- 月省: ¥{report['roi']['monthly_saved_cny']}",
            f"- ROI: {report['roi']['roi_ratio']}",
            f"- 结论: {report['roi']['verdict']}",
            "",
            f"## 反推：如果没有NB",
            f"- 停机损失: ¥{report['counterfactual']['if_no_nb']['downtime_cost_cny']}",
            f"- 手动重试: ¥{report['counterfactual']['if_no_nb']['manual_retry_cost_cny']}",
            f"- 总潜在损失: ¥{report['counterfactual']['if_no_nb']['total_loss_cny']}",
        ]
        return "\n".join(lines)

    def upgrade_triggers(self) -> List[Dict[str, str]]:
        """Check for natural upgrade triggers."""
        report = self.savings_report()
        triggers = []

        diagnosis_count = report["protection_events"].get("diagnosis", 0)
        if diagnosis_count > 50:
            triggers.append({
                "type": "frequency",
                "message": f"本月诊断{diagnosis_count}次，故障频率高 → Pro省时87%",
                "cta": "升级Pro: correctover.cn/buy.html",
            })

        failover_count = report["protection_events"].get("failover", 0)
        if failover_count > 0:
            triggers.append({
                "type": "crisis",
                "message": f"检测到{failover_count}次关键故障 → Pro版3秒自动切换",
                "cta": "升级Pro: correctover.cn/buy.html",
            })

        return triggers

    # ── Internal ─────────────────────────────────────────────────

    def _compute_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """Compute USD cost for a model call."""
        prices = MODEL_PRICES.get(model)
        if not prices:
            model_lower = model.lower()
            for key, val in MODEL_PRICES.items():
                if key.lower() in model_lower or model_lower in key.lower():
                    prices = val
                    break
        if not prices:
            prices = MODEL_PRICES["gpt-4o"]
        input_cost = prices["input"] * input_tokens / 1_000_000
        output_cost = prices["output"] * output_tokens / 1_000_000
        return round(input_cost + output_cost, 6)

    def _persist(self) -> None:
        """Persist stats to local JSON."""
        try:
            os.makedirs(os.path.dirname(self._persist_path), exist_ok=True)
            with self._lock:
                data = {
                    "version": 2,
                    "start_time": self._start_time,
                    "call_records": [asdict(r) for r in self._call_records[-5000:]],
                    "protection_events": [asdict(e) for e in self._protection_events[-5000:]],
                }
            with open(self._persist_path, "w") as f:
                json.dump(data, f, ensure_ascii=False)
        except Exception:
            pass

    def _load(self) -> None:
        """Load persisted stats."""
        try:
            if not os.path.exists(self._persist_path):
                return
            with open(self._persist_path, "r") as f:
                data = json.load(f)
            for r in data.get("call_records", []):
                self._call_records.append(CallRecord(**r))
            for e in data.get("protection_events", []):
                self._protection_events.append(ProtectionEvent(**e))
        except Exception:
            pass

    def reset(self) -> None:
        """Reset all stats. Testing only."""
        with self._lock:
            self._call_records.clear()
            self._protection_events.clear()
        try:
            if os.path.exists(self._persist_path):
                os.remove(self._persist_path)
        except Exception:
            pass


# ── Module-level singleton ───────────────────────────────────────

stats = StatsEngine()


# ── Public convenience functions ─────────────────────────────────

def record_call(result):
    stats.record_call(result)

def record_protection(action, original_model="", fallback_model="",
                      fault_category="", failover_time_ms=0.0,
                      input_tokens=0, output_tokens=0):
    stats.record_protection(
        action, original_model, fallback_model,
        fault_category, failover_time_ms, input_tokens, output_tokens
    )

def savings_report(period=None):
    return stats.savings_report(period)

def console_summary():
    return stats.console_summary()

def dashboard_data():
    return stats.dashboard_data()

def weekly_summary():
    return stats.weekly_summary()

def upgrade_triggers():
    return stats.upgrade_triggers()
