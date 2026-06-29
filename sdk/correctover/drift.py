# Copyright 2024-2026 Correctover Team
# Licensed under the Apache License, Version 2.0 (the "License")
#
"""Correctover DriftMonitor — 持续漂移监控与告警

4类漂移检测:
  1. 语义漂移 (Semantic Drift): 同一prompt的输出质量持续下滑
  2. 模型行为漂移 (Model Behavior Drift): Provider偷偷换模型/降级
  3. 路由策略漂移 (Routing Drift): 路由决策偏离预期策略
  4. Provider性能漂移 (Provider Drift): 延迟/错误率渐进式恶化

检测方式: 滑动窗口 + EMA趋势 + 变化率阈值
告警级别: INFO / WARN / CRITICAL
"""
import time
import math
from typing import Dict, List, Optional, Any, Tuple
from collections import deque

DEFAULT_WINDOW_SIZE = 50
DEFAULT_EMA_ALPHA = 0.15
DEFAULT_LATENCY_DRIFT_PCT = 0.30
DEFAULT_ERROR_RATE_THRESHOLD = 0.10
DEFAULT_SIMILARITY_DROP = 0.15
DEFAULT_ROUTING_DEVIATION = 0.25
DEFAULT_OUTPUT_LENGTH_DRIFT_PCT = 0.40


class DriftAlert:
    __slots__ = ("drift_type", "severity", "detail", "provider", "model", "ts", "metrics")

    def __init__(self, drift_type, severity, detail, provider="", model="", metrics=None):
        self.drift_type = drift_type
        self.severity = severity
        self.detail = detail
        self.provider = provider
        self.model = model
        self.ts = time.time()
        self.metrics = metrics or {}

    def as_dict(self):
        return {"drift_type": self.drift_type, "severity": self.severity,
                "detail": self.detail, "provider": self.provider,
                "model": self.model, "ts": self.ts, "metrics": self.metrics}


class DriftMonitor:
    """漂移监控器 — 嵌入式持续检测4类漂移"""

    def __init__(self, window_size=DEFAULT_WINDOW_SIZE):
        self._window_size = window_size
        self._alerts = []
        self._max_alerts = 200
        self._provider_windows = {}
        self._provider_ema = {}
        self._similarity_windows = {}
        self._similarity_baselines = {}
        self._routing_windows = {}
        self._output_length_windows = {}
        self._output_length_baselines = {}
        self._total_observations = 0
        self._drift_detected_count = 0
        self._start_time = time.time()

    def observe_call(self, provider, model, latency_ms=0, output_tokens=0, success=True, error_type=""):
        """观察一次API调用"""
        key = f"{provider}/{model}"
        self._total_observations += 1

        if key not in self._provider_windows:
            self._provider_windows[key] = deque(maxlen=self._window_size)
        self._provider_windows[key].append({"latency_ms": latency_ms, "success": success,
                                            "output_tokens": output_tokens, "ts": time.time()})

        if latency_ms > 0:
            old_ema = self._provider_ema.get(key, latency_ms)
            self._provider_ema[key] = DEFAULT_EMA_ALPHA * latency_ms + (1 - DEFAULT_EMA_ALPHA) * old_ema

        if output_tokens > 0:
            if key not in self._output_length_windows:
                self._output_length_windows[key] = deque(maxlen=self._window_size)
                self._output_length_baselines[key] = output_tokens
            self._output_length_windows[key].append(output_tokens)
            if len(self._output_length_windows[key]) < 10:
                self._output_length_baselines[key] = sum(self._output_length_windows[key]) / len(self._output_length_windows[key])

        self._check_latency_drift(key, provider, model)
        self._check_error_rate_drift(key, provider, model)
        self._check_output_length_drift(key, provider, model)

    def _check_latency_drift(self, key, provider, model):
        ema = self._provider_ema.get(key)
        if ema is None:
            return
        window = list(self._provider_windows.get(key, []))
        if len(window) < 10:
            return
        n = len(window)
        baseline_latency = sum(w["latency_ms"] for w in window[:n // 3]) / max(n // 3, 1)
        if baseline_latency > 0:
            drift_pct = (ema - baseline_latency) / baseline_latency
            if drift_pct > DEFAULT_LATENCY_DRIFT_PCT:
                severity = "CRITICAL" if drift_pct > 0.6 else "WARN" if drift_pct > 0.3 else "INFO"
                self._add_alert(DriftAlert("latency_drift", severity,
                    f"{key} latency EMA {ema:.0f}ms vs baseline {baseline_latency:.0f}ms (+{drift_pct*100:.0f}%)",
                    provider, model, {"ema_ms": round(ema,1), "baseline_ms": round(baseline_latency,1), "drift_pct": round(drift_pct*100,1)}))

    def _check_error_rate_drift(self, key, provider, model):
        window = list(self._provider_windows.get(key, []))
        if len(window) < 10:
            return
        recent = window[-20:]
        errors = sum(1 for w in recent if not w["success"])
        error_rate = errors / len(recent)
        if error_rate > DEFAULT_ERROR_RATE_THRESHOLD:
            severity = "CRITICAL" if error_rate > 0.3 else "WARN"
            self._add_alert(DriftAlert("error_rate_drift", severity,
                f"{key} error rate {error_rate*100:.0f}% ({errors}/{len(recent)})",
                provider, model, {"error_rate": round(error_rate*100,1)}))

    def _check_output_length_drift(self, key, provider, model):
        window = self._output_length_windows.get(key)
        baseline = self._output_length_baselines.get(key)
        if window is None or len(window) < 15 or baseline is None or baseline == 0:
            return
        recent = list(window)[-15:]
        recent_avg = sum(recent) / len(recent)
        drift_pct = (recent_avg - baseline) / baseline
        if abs(drift_pct) > DEFAULT_OUTPUT_LENGTH_DRIFT_PCT:
            direction = "shorter" if drift_pct < 0 else "longer"
            severity = "CRITICAL" if abs(drift_pct) > 0.6 else "WARN"
            self._add_alert(DriftAlert("model_behavior_drift", severity,
                f"{key} output {direction}: avg={recent_avg:.0f} vs baseline={baseline:.0f} ({drift_pct*100:+.0f}%)",
                provider, model, {"recent_avg": round(recent_avg,1), "baseline": round(baseline,1)}))

    def observe_similarity(self, prompt_key, score):
        """观察一次语义相似度"""
        if prompt_key not in self._similarity_windows:
            self._similarity_windows[prompt_key] = deque(maxlen=self._window_size)
            self._similarity_baselines[prompt_key] = score
        self._similarity_windows[prompt_key].append(score)
        window = self._similarity_windows[prompt_key]
        if len(window) < 10:
            self._similarity_baselines[prompt_key] = sum(window) / len(window)
        else:
            baseline = self._similarity_baselines.get(prompt_key, 1.0)
            recent_avg = sum(list(window)[-10:]) / 10.0
            drop = baseline - recent_avg
            if drop > DEFAULT_SIMILARITY_DROP:
                severity = "CRITICAL" if drop > 0.3 else "WARN"
                self._add_alert(DriftAlert("semantic_drift", severity,
                    f"Prompt[{prompt_key[:8]}] similarity dropped: {recent_avg:.3f} vs {baseline:.3f}",
                    metrics={"recent_avg": round(recent_avg,4), "baseline": round(baseline,4)}))

    def observe_routing_decision(self, strategy, provider, model):
        """观察一次路由决策"""
        if strategy not in self._routing_windows:
            self._routing_windows[strategy] = deque(maxlen=self._window_size)
        self._routing_windows[strategy].append(f"{provider}/{model}")
        window = list(self._routing_windows[strategy])
        if len(window) < 20:
            return
        recent = window[-20:]
        current_dist = {}
        for k in recent:
            current_dist[k] = current_dist.get(k, 0) + 1
        for k in current_dist:
            current_dist[k] /= len(recent)
        n = len(window)
        historical = window[:n // 3]
        hist_dist = {}
        for k in historical:
            hist_dist[k] = hist_dist.get(k, 0) + 1
        for k in hist_dist:
            hist_dist[k] /= len(historical)
        all_keys = set(list(current_dist.keys()) + list(hist_dist.keys()))
        tvd = sum(abs(current_dist.get(k, 0) - hist_dist.get(k, 0)) for k in all_keys) / 2
        if tvd > DEFAULT_ROUTING_DEVIATION:
            severity = "WARN" if tvd < 0.4 else "CRITICAL"
            self._add_alert(DriftAlert("routing_drift", severity,
                f"Strategy '{strategy}' routing deviation TVD={tvd:.2f}",
                metrics={"tvd": round(tvd,3)}))

    def _add_alert(self, alert):
        for existing in self._alerts[-10:]:
            if (existing.drift_type == alert.drift_type and
                existing.provider == alert.provider and
                existing.model == alert.model and
                alert.ts - existing.ts < 300):
                return
        self._alerts.append(alert)
        self._drift_detected_count += 1
        if len(self._alerts) > self._max_alerts:
            self._alerts = self._alerts[-self._max_alerts:]

    @property
    def alerts(self):
        return list(self._alerts[-20:])

    @property
    def critical_alerts(self):
        return [a for a in self.alerts if a.severity == "CRITICAL"]

    def status(self):
        by_type = {}
        for a in self._alerts:
            by_type[a.drift_type] = by_type.get(a.drift_type, 0) + 1
        by_severity = {}
        for a in self._alerts:
            by_severity[a.severity] = by_severity.get(a.severity, 0) + 1
        return {
            "total_observations": self._total_observations,
            "drift_detected": self._drift_detected_count,
            "tracked_providers": list(self._provider_ema.keys()),
            "alerts_by_type": by_type,
            "alerts_by_severity": by_severity,
            "recent_alerts": [a.as_dict() for a in self._alerts[-10:]],
            "healthy": len([a for a in self._alerts if a.severity == "CRITICAL"]) == 0,
        }

    def get_telemetry_event(self):
        s = self.status()
        return {"event": "drift_report", "total_observations": s["total_observations"],
                "drift_detected": s["drift_detected"], "alerts_by_type": s["alerts_by_type"],
                "alerts_by_severity": s["alerts_by_severity"], "healthy": s["healthy"]}

    def reset(self):
        self._provider_windows.clear()
        self._provider_ema.clear()
        self._similarity_windows.clear()
        self._similarity_baselines.clear()
        self._routing_windows.clear()
        self._output_length_windows.clear()
        self._output_length_baselines.clear()
        self._alerts.clear()
        self._total_observations = 0
        self._drift_detected_count = 0
        self._start_time = time.time()


_global_monitor = None

def get_drift_monitor():
    global _global_monitor
    if _global_monitor is None:
        _global_monitor = DriftMonitor()
    return _global_monitor

def observe_call(*a, **kw):
    get_drift_monitor().observe_call(*a, **kw)

def observe_similarity(*a, **kw):
    get_drift_monitor().observe_similarity(*a, **kw)

def observe_routing_decision(*a, **kw):
    get_drift_monitor().observe_routing_decision(*a, **kw)

def status():
    return get_drift_monitor().status()

def alerts():
    return get_drift_monitor().alerts
