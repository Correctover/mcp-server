# Copyright 2024-2026 Correctover Team
# Licensed under the Apache License, Version 2.0 (the "License")
#
"""Correctover CarbonTracker — LLM推理碳排放监控与优化

核心公式:
  Token使用 → 模型能耗系数(Wh/1K tokens) → 总能耗(Wh) → CO₂排放(kg)

换算参数:
  - 碳排放系数: 0.6 kg CO₂/kWh (中国电网, 信通院2024)
  - PUE: 1.3 (数据中心平均能效比)
  - 模型能耗按tier分三档: premium/standard/mini

产品定位:
  Correctover = LLM算力节能引擎
  每次路由优化 = 减少无效GPU推理 = 节电 = 减碳
  每次检查点恢复 = 跳过已完成的推理 = 零碳排放
"""
import time
import threading
from typing import Dict, List, Optional, Any


# ── 能耗系数表 ──────────────────────────────────────────────────
# 单位: Wh / 1K tokens (含PUE 1.3)
# 来源: EPRI/独立研究 + ODCC数据中心能效白皮书
# 计算: 单次推理能耗 × PUE / 平均token吞吐量

MODEL_ENERGY = {
    # OpenAI
    "gpt-4o":           {"wh_per_1k": 0.80, "tier": "premium"},
    "gpt-4o-mini":      {"wh_per_1k": 0.10, "tier": "mini"},
    "gpt-3.5-turbo":    {"wh_per_1k": 0.20, "tier": "mini"},
    # Anthropic
    "claude-sonnet-4":   {"wh_per_1k": 0.70, "tier": "premium"},
    "claude-3-5-haiku":  {"wh_per_1k": 0.15, "tier": "mini"},
    # DeepSeek
    "deepseek-chat":     {"wh_per_1k": 0.30, "tier": "standard"},
    "deepseek-reasoner": {"wh_per_1k": 0.55, "tier": "premium"},
    # Google
    "gemini-2.0-flash":  {"wh_per_1k": 0.10, "tier": "mini"},
    "gemini-1.5-pro":    {"wh_per_1k": 0.65, "tier": "premium"},
    # DashScope
    "qwen-max":          {"wh_per_1k": 0.35, "tier": "standard"},
    "qwen-plus":         {"wh_per_1k": 0.12, "tier": "mini"},
    "qwen-turbo":        {"wh_per_1k": 0.08, "tier": "mini"},
}

# 按tier的默认值
_TIER_ENERGY_DEFAULT = {
    "premium":  0.70,
    "standard": 0.30,
    "mini":     0.12,
}

# ── 碳排放参数 ──────────────────────────────────────────────────
CARBON_INTENSITY_GRID = 0.6    # kg CO₂/kWh — 中国电网平均(信通院2024)
PUE_AVERAGE = 1.3              # 数据中心平均PUE (Uptime Institute 2024)


def _get_wh_per_1k(model: str) -> float:
    """获取模型每1K tokens的能耗(Wh), 含PUE"""
    info = MODEL_ENERGY.get(model)
    if info:
        return info["wh_per_1k"]
    # fallback: 按tier查默认值
    from correctover.classifier import get_model_tier
    tier = get_model_tier(model)
    return _TIER_ENERGY_DEFAULT.get(tier, 0.30)


def estimate_wh(model: str, input_tokens: int, output_tokens: int) -> float:
    """估算一次API调用的能耗(Wh)"""
    total_1k = (input_tokens + output_tokens) / 1000.0
    return _get_wh_per_1k(model) * total_1k


def estimate_co2_kg(model: str, input_tokens: int, output_tokens: int) -> float:
    """估算一次API调用的碳排放(kg CO₂)"""
    wh = estimate_wh(model, input_tokens, output_tokens)
    kwh = wh / 1000.0
    return kwh * CARBON_INTENSITY_GRID


class CarbonTracker:
    """碳排放追踪器 — 嵌入式SDK自动计算

    用法:
        from correctover import CarbonTracker
        ct = CarbonTracker()

        # 自动集成到Client/Router/Checkpoint
        # 也可以手动记录
        ct.record_call("deepseek", "deepseek-chat", 1000, 500)
        ct.record_routing_savings("gpt-4o", "deepseek-chat", 1000, 500)
        ct.record_checkpoint_savings(steps_saved=3, tokens_per_step=2000, model="deepseek-chat")

        # 查看报告
        print(ct.report())
        print(ct.esg_summary())
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *a, **kw):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, carbon_intensity: float = None):
        if hasattr(self, "_initialized"):
            return
        self._initialized = True
        self._carbon_intensity = carbon_intensity or CARBON_INTENSITY_GRID
        self._calls: List[Dict] = []       # 实际API调用
        self._waste: List[Dict] = []        # 浪费的调用(429/故障)
        self._routing_savings: List[Dict] = []  # 路由优化节省
        self._checkpoint_savings: List[Dict] = []  # 检查点恢复节省
        self._start_time = time.time()
        self._lock = threading.Lock()

    # ── 记录API调用 ──────────────────────────────────────

    def record_call(self, provider: str, model: str,
                    input_tokens: int = 0, output_tokens: int = 0,
                    latency_ms: float = 0, avoided: bool = False):
        """记录一次API调用

        avoided=True: 429/故障导致的浪费调用
        """
        wh = estimate_wh(model, input_tokens, output_tokens)
        co2_kg = (wh / 1000.0) * self._carbon_intensity
        entry = {
            "provider": provider,
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "wh": wh,
            "co2_kg": co2_kg,
            "latency_ms": latency_ms,
            "ts": time.time(),
        }
        with self._lock:
            if avoided:
                self._waste.append(entry)
            else:
                self._calls.append(entry)

    # ── 路由优化节省 ──────────────────────────────────────

    def record_routing_savings(self, original_model: str, actual_model: str,
                                input_tokens: int, output_tokens: int):
        """路由优化节省的碳排放

        例: 原本要调用 gpt-4o, Router智能调度到 deepseek-chat
        """
        wh_original = estimate_wh(original_model, input_tokens, output_tokens)
        wh_actual = estimate_wh(actual_model, input_tokens, output_tokens)
        wh_saved = max(0, wh_original - wh_actual)
        co2_saved_kg = (wh_saved / 1000.0) * self._carbon_intensity

        from correctover.classifier import get_cost_per_token
        cost_original = (get_cost_per_token(original_model, "input") * input_tokens +
                         get_cost_per_token(original_model, "output") * output_tokens)
        cost_actual = (get_cost_per_token(actual_model, "input") * input_tokens +
                       get_cost_per_token(actual_model, "output") * output_tokens)
        cost_saved = max(0, cost_original - cost_actual)

        with self._lock:
            self._routing_savings.append({
                "original_model": original_model,
                "actual_model": actual_model,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "wh_saved": wh_saved,
                "co2_saved_kg": co2_saved_kg,
                "cost_saved_usd": cost_saved,
                "ts": time.time(),
            })

    # ── 检查点恢复节省 ──────────────────────────────────────

    def record_checkpoint_savings(self, steps_saved: int,
                                   tokens_per_step: int = 0,
                                   model: str = "deepseek-chat"):
        """检查点恢复节省的碳排放

        steps_saved: 跳过了多少步不需要重新执行
        tokens_per_step: 每步平均token数
        """
        total_tokens = steps_saved * tokens_per_step
        wh_saved = estimate_wh(model, total_tokens, 0)  # 只算input
        co2_saved_kg = (wh_saved / 1000.0) * self._carbon_intensity

        from correctover.classifier import get_cost_per_token
        cost_saved = get_cost_per_token(model, "input") * total_tokens

        with self._lock:
            self._checkpoint_savings.append({
                "steps_saved": steps_saved,
                "tokens_saved": total_tokens,
                "model": model,
                "wh_saved": wh_saved,
                "co2_saved_kg": co2_saved_kg,
                "cost_saved_usd": cost_saved,
                "ts": time.time(),
            })

    # ── 统计属性 ──────────────────────────────────────

    @property
    def total_wh(self) -> float:
        """总能耗(Wh) — 实际调用"""
        with self._lock:
            return sum(c["wh"] for c in self._calls)

    @property
    def total_kwh(self) -> float:
        """总能耗(kWh)"""
        return self.total_wh / 1000.0

    @property
    def total_co2_kg(self) -> float:
        """总碳排放(kg CO₂) — 实际调用"""
        with self._lock:
            return sum(c["co2_kg"] for c in self._calls)

    @property
    def total_co2_tons(self) -> float:
        """总碳排放(吨 CO₂)"""
        return self.total_co2_kg / 1000.0

    @property
    def waste_wh(self) -> float:
        """浪费能耗(Wh) — 429/故障"""
        with self._lock:
            return sum(c["wh"] for c in self._waste)

    @property
    def waste_co2_kg(self) -> float:
        """浪费碳排放(kg CO₂)"""
        with self._lock:
            return sum(c["co2_kg"] for c in self._waste)

    @property
    def saved_wh(self) -> float:
        """总节省能耗(Wh) — 路由+检查点"""
        with self._lock:
            r = sum(s["wh_saved"] for s in self._routing_savings)
            c = sum(s["wh_saved"] for s in self._checkpoint_savings)
            return r + c

    @property
    def saved_co2_kg(self) -> float:
        """总节省碳排放(kg CO₂)"""
        with self._lock:
            r = sum(s["co2_saved_kg"] for s in self._routing_savings)
            c = sum(s["co2_saved_kg"] for s in self._checkpoint_savings)
            return r + c

    @property
    def saved_cost_usd(self) -> float:
        """总节省费用(USD)"""
        with self._lock:
            r = sum(s["cost_saved_usd"] for s in self._routing_savings)
            c = sum(s["cost_saved_usd"] for s in self._checkpoint_savings)
            return r + c

    @property
    def carbon_intensity(self) -> float:
        """碳强度: g CO₂ / 1K tokens (加权平均)"""
        with self._lock:
            total_tokens = sum(c["input_tokens"] + c["output_tokens"] for c in self._calls)
            if total_tokens == 0:
                return 0.0
            return (self.total_co2_kg * 1000) / (total_tokens / 1000.0)

    @property
    def savings_rate(self) -> float:
        """节省率: saved / (actual + saved)"""
        total_wh = self.total_wh + self.saved_wh
        if total_wh == 0:
            return 0.0
        return self.saved_wh / total_wh

    @property
    def waste_rate(self) -> float:
        """浪费率: waste / (actual + waste)"""
        total = self.total_wh + self.waste_wh
        if total == 0:
            return 0.0
        return self.waste_wh / total

    # ── 报告 ──────────────────────────────────────

    def report(self) -> Dict[str, Any]:
        """完整碳报告"""
        with self._lock:
            total_calls = len(self._calls)
            waste_calls = len(self._waste)
            routing_count = len(self._routing_savings)
            checkpoint_count = len(self._checkpoint_savings)

            # 按Provider统计
            by_provider = {}
            for c in self._calls:
                p = c["provider"]
                if p not in by_provider:
                    by_provider[p] = {"calls": 0, "wh": 0, "co2_kg": 0, "tokens": 0}
                by_provider[p]["calls"] += 1
                by_provider[p]["wh"] += c["wh"]
                by_provider[p]["co2_kg"] += c["co2_kg"]
                by_provider[p]["tokens"] += c["input_tokens"] + c["output_tokens"]

            # 按Model统计
            by_model = {}
            for c in self._calls:
                m = c["model"]
                if m not in by_model:
                    by_model[m] = {"calls": 0, "wh": 0, "co2_kg": 0, "tokens": 0}
                by_model[m]["calls"] += 1
                by_model[m]["wh"] += c["wh"]
                by_model[m]["co2_kg"] += c["co2_kg"]
                by_model[m]["tokens"] += c["input_tokens"] + c["output_tokens"]

        uptime_hours = (time.time() - self._start_time) / 3600.0

        return {
            "uptime_hours": round(uptime_hours, 2),
            "actual": {
                "calls": total_calls,
                "wh": round(self.total_wh, 4),
                "kwh": round(self.total_kwh, 6),
                "co2_kg": round(self.total_co2_kg, 6),
                "co2_tons": round(self.total_co2_tons, 8),
            },
            "waste": {
                "calls": waste_calls,
                "wh": round(self.waste_wh, 4),
                "co2_kg": round(self.waste_co2_kg, 6),
            },
            "savings": {
                "routing_decisions": routing_count,
                "checkpoint_resumes": checkpoint_count,
                "wh": round(self.saved_wh, 4),
                "co2_kg": round(self.saved_co2_kg, 6),
                "cost_usd": round(self.saved_cost_usd, 6),
                "rate": round(self.savings_rate, 4),
            },
            "intensity": {
                "g_co2_per_1k_tokens": round(self.carbon_intensity, 4),
                "grid_factor": self._carbon_intensity,
            },
            "by_provider": by_provider,
            "by_model": by_model,
        }

    def esg_summary(self) -> Dict[str, Any]:
        """ESG报告格式 — 适合直接写入ESG/可持续发展报告

        参考标准:
        - GHG Protocol (温室气体核算体系)
        - 中国碳市场MRV要求
        """
        uptime_hours = (time.time() - self._start_time) / 3600.0
        return {
            "reporting_period": f"{round(uptime_hours, 1)} hours",
            "scope2_emissions_kg_co2": round(self.total_co2_kg, 6),
            "avoided_emissions_kg_co2": round(self.saved_co2_kg, 6),
            "waste_emissions_kg_co2": round(self.waste_co2_kg, 6),
            "energy_consumed_kwh": round(self.total_kwh, 6),
            "energy_saved_kwh": round(self.saved_wh / 1000.0, 6),
            "energy_waste_kwh": round(self.waste_wh / 1000.0, 6),
            "carbon_intensity_g_per_1k_tokens": round(self.carbon_intensity, 4),
            "savings_rate_pct": round(self.savings_rate * 100, 2),
            "waste_rate_pct": round(self.waste_rate * 100, 2),
            "grid_carbon_factor": f"{self._carbon_intensity} kg CO₂/kWh",
            "methodology": "Token-based estimation with model-tier energy coefficients",
            "data_sources": [
                "EPRI AI Energy Research 2024",
                "ODCC 数据中心算力碳效白皮书",
                "信通院 中国数据中心碳排放 2024",
            ],
        }

    # ── 遥测上报 ──────────────────────────────────────

    def flush_to_telemetry(self):
        """将碳报告上报遥测系统"""
        try:
            from correctover.telemetry import record_provider_call
            # 上报一个 carbon_report 事件
            # 使用 telemetry 的 flush 机制
            pass  # 遥测carbon_report通过专门的carbon_report事件
        except Exception:
            pass

    def get_telemetry_event(self) -> Dict[str, Any]:
        """生成遥测事件 — 供telemetry.so的flush调用"""
        r = self.report()
        return {
            "event": "carbon_report",
            "actual_wh": r["actual"]["wh"],
            "actual_co2_kg": r["actual"]["co2_kg"],
            "saved_wh": r["savings"]["wh"],
            "saved_co2_kg": r["savings"]["co2_kg"],
            "waste_wh": r["waste"]["wh"],
            "waste_co2_kg": r["waste"]["co2_kg"],
            "savings_rate": r["savings"]["rate"],
            "carbon_intensity": r["intensity"]["g_co2_per_1k_tokens"],
        }

    def reset(self):
        """重置所有计数器"""
        with self._lock:
            self._calls.clear()
            self._waste.clear()
            self._routing_savings.clear()
            self._checkpoint_savings.clear()
            self._start_time = time.time()


# ── 全局单例 ──────────────────────────────────────

_global_tracker = None

def get_carbon_tracker() -> CarbonTracker:
    """获取全局CarbonTracker"""
    global _global_tracker
    if _global_tracker is None:
        _global_tracker = CarbonTracker()
    return _global_tracker


def record_call(*a, **kw):
    get_carbon_tracker().record_call(*a, **kw)

def record_routing_savings(*a, **kw):
    get_carbon_tracker().record_routing_savings(*a, **kw)

def record_checkpoint_savings(*a, **kw):
    get_carbon_tracker().record_checkpoint_savings(*a, **kw)

def report():
    return get_carbon_tracker().report()

def esg_summary():
    return get_carbon_tracker().esg_summary()
