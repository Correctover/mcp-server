# Copyright 2024-2026 Correctover Team
# Licensed under the Apache License, Version 2.0 (the "License")
#
"""nb.status() — 终端仪表盘（Claude Code 风格）

实时显示授权计划、Provider 健康、用量统计、近期活动。

Usage:
    import correctover as nb
    nb.status()          # 一次性刷新
    nb.status(watch=True)  # 持续监控（每 5 秒刷新）
"""

import os
import sys
import time
import json
from datetime import datetime
from typing import Any, Dict, List, Optional


# ── ANSI colors (Claude Code inspired palette) ───────────────

class C:
    """Terminal colors — CC-inspired compact palette."""
    RST    = "\033[0m"
    BOLD   = "\033[1m"
    DIM    = "\033[2m"
    ITA    = "\033[3m"
    R      = "\033[91m"
    G      = "\033[92m"
    Y      = "\033[93m"
    B      = "\033[94m"
    M      = "\033[95m"
    C      = "\033[96m"
    W      = "\033[97m"
    GY     = "\033[90m"
    BG     = "\033[1;92m"
    BB     = "\033[1;96m"
    BW     = "\033[1;97m"
    BR     = "\033[1;91m"
    BY     = "\033[1;93m"

    @staticmethod
    def ok() -> str:
        return f"{C.G}●{C.RST}"

    @staticmethod
    def warn() -> str:
        return f"{C.Y}●{C.RST}"

    @staticmethod
    def err() -> str:
        return f"{C.R}●{C.RST}"

    @staticmethod
    def off() -> str:
        return f"{C.GY}○{C.RST}"

    @staticmethod
    def spin(i: int) -> str:
        chars = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        return f"{C.C}{chars[i % len(chars)]}{C.RST}"


def _use_color() -> bool:
    if not hasattr(sys.stdout, "isatty") or not sys.stdout.isatty():
        return True
    if sys.platform == "win32":
        return os.environ.get("TERM", "").startswith("xterm") or "color" in os.environ.get("TERM", "")
    return True

USE_COLOR = _use_color()

def c(code: str, text: str) -> str:
    if USE_COLOR:
        return f"{code}{text}{C.RST}"
    return text

# ── Terminal width ──────────────────────────────────────────

def _term_width() -> int:
    try:
        import shutil
        return shutil.get_terminal_size((80, 24)).columns
    except Exception:
        return 80

W = 72  # default, recalculated on each call

# ─── Data collectors ─────────────────────────────────────────

def _get_license_info() -> Dict[str, Any]:
    """Collect license status."""
    info = {"plan": "unknown", "valid": False, "label": "未激活",
            "days": None, "expires": None, "device_bound": False}
    try:
        from correctover.license import (
            get_plan, is_pro, is_expired, is_device_bound,
            days_remaining, plan_summary, PlanLabels,
        )
        plan = get_plan()
        info["plan"] = plan
        info["label"] = PlanLabels.get(plan, plan)
        info["valid"] = plan not in ("free", "none", "")
        info["expired"] = is_expired()
        info["pro"] = is_pro()
        info["device_bound"] = is_device_bound()
        info["days"] = days_remaining()
        info["summary"] = plan_summary()
        info["pro_plans"] = bool(is_pro())
    except Exception:
        info["plan"] = "error"
    return info


def _get_provider_health() -> List[Dict[str, Any]]:
    """Collect provider health status."""
    providers = []
    try:
        from correctover._engine import SelfHealingEngine
        engine = SelfHealingEngine()
        try:
            hc = engine.health_check()
            for name, status in hc.items():
                providers.append({
                    "name": name,
                    "status": status,
                    "latency_ms": hc.get(f"{name}_latency", 0),
                })
        except Exception:
            pass
        engine.close_sync()
    except Exception:
        pass

    # Fallback: check env for configured providers
    if not providers:
        for provider, env_var in [
            ("deepseek", "DEEPSEEK_API_KEY"),
            ("openai", "OPENAI_API_KEY"),
            ("anthropic", "ANTHROPIC_API_KEY"),
            ("dashscope", "DASHSCOPE_API_KEY"),
        ]:
            if os.environ.get(env_var, ""):
                providers.append({"name": provider, "status": "configured", "latency_ms": 0})

    return providers


def _get_usage_stats() -> Dict[str, Any]:
    """Collect usage statistics."""
    stats = {
        "calls": 0, "tokens_in": 0, "tokens_out": 0,
        "cost_usd": 0.0, "savings_usd": 0.0,
        "carbon_kg": 0.0, "savings_pct": 0.0,
        "routing_decisions": 0, "checkpoint_resumes": 0,
    }
    try:
        from correctover._stats import stats as _stats
        report = _stats.savings_report()
        stats["calls"] = report.get("total_requests", 0)
        tokens = report.get("total_tokens", {})
        stats["tokens_in"] = tokens.get("input", 0)
        stats["tokens_out"] = tokens.get("output", 0)
        savings = report.get("savings", {})
        stats["savings_usd"] = savings.get("model_difference_usd", 0)
        cf = report.get("counterfactual", {})
        nb_data = cf.get("with_nb", {})
        wo_data = cf.get("if_no_nb", {})
        stats["cost_usd"] = nb_data.get("actual_cost_usd", 0)
        actual = nb_data.get("actual_cost_usd", 1)
        if actual > 0:
            stats["savings_pct"] = (
                (wo_data.get("all_original_model_cost_usd", 0) - actual) / actual
            ) * 100
    except Exception:
        pass

    try:
        from correctover.carbon import get_carbon_tracker
        ct = get_carbon_tracker()
        r = ct.report()
        stats["carbon_kg"] = r.get("actual", {}).get("co2_kg", 0)
    except Exception:
        pass

    try:
        from correctover.drift import get_drift_monitor
        dm = get_drift_monitor()
        s = dm.status()
        stats["drift_alerts"] = s.get("drift_detected", 0)
        stats["drift_healthy"] = s.get("healthy", True)
    except Exception:
        stats["drift_alerts"] = 0
        stats["drift_healthy"] = True

    return stats


def _get_recent_activity() -> List[Dict[str, Any]]:
    """Collect recent repair/activity log."""
    activity = []
    try:
        from correctover._stats import stats as _stats
        recent = getattr(_stats, "recent_events", None)
        if recent:
            activity = recent()[:8]
    except Exception:
        pass
    return activity


# ── Render blocks ────────────────────────────────────────────

def _render_header(info: Dict[str, Any]) -> str:
    """CC-style status header line."""
    lines = []
    ver = "unknown"
    try:
        from correctover._version import __version__
        ver = __version__
    except Exception:
        pass

    # Left: SDK info
    left = f"  {c(C.BB, 'Correctover')} {c(C.GY, 'SDK')} {c(C.W, 'v' + ver)}"

    # Right: status indicators
    plan_dot = C.ok() if info.get("pro") else (C.warn() if info.get("valid") else C.off())
    plan_text = info.get("label", "未激活")

    right = f"{c(C.G, '●')} {c(C.W, 'Healthy')}  │  {plan_dot} {c(C.W, plan_text)}"

    pad = W - len(left) - len(right) - 4
    if pad < 2:
        pad = 2

    header = f"┌{'─' * (W - 2)}┐"
    title = f"│{left}{' ' * pad}{right}│"
    subtitle = f"│  {c(C.GY, '进程内嵌入 · 生产级稳定 · 即装即用')}{' ' * (W - 48)}│"

    lines = [header, title, subtitle]
    return '\n'.join(lines)


def _render_license_block(info: Dict[str, Any]) -> str:
    """Render license section."""
    lines = []
    lines.append(f"│  {c(C.BW, 'License')}")
    lines.append(f"│    {c(C.GY, 'Plan:')}   {c(C.W, info.get('label', '未知'))}")

    days = info.get("days")
    if days is not None and days >= 0:
        expiry = info.get("summary", "")
        lines.append(f"│    {c(C.GY, 'Days:')}   {c(C.W, str(days))}{c(C.GY, '天剩余')}")

    if info.get("device_bound"):
        lines.append(f"│    {c(C.GY, 'Device:')} {c(C.G, '●')}{c(C.GY, ' 已绑定')}")
    else:
        lines.append(f"│    {c(C.GY, 'Device:')} {c(C.Y, '○')}{c(C.GY, ' 未绑定')}")

    if info.get("expired"):
        lines.append(f"│    {c(C.BR, '⚠ 已过期 — 修复功能已停止')}")

    return '\n'.join(lines)


def _render_provider_block(providers: List[Dict[str, Any]]) -> str:
    """Render provider health section (CC-style dot indicators)."""
    lines = []
    lines.append(f"│  {c(C.BW, 'Provider Health')}")

    if not providers:
        lines.append(f"│    {c(C.GY, '没有配置的 Provider')}  {c(C.DIM, '(设置 DEEPSEEK_API_KEY 等环境变量)')}")
        return '\n'.join(lines)

    for p in providers:
        status = p.get("status", "unknown")
        name = p.get("name", "?")
        latency = p.get("latency_ms", 0)

        if status == "healthy":
            dot = C.ok()
            status_text = f"{c(C.G, 'healthy')}"
        elif status in ("degraded", "configured"):
            dot = C.warn()
            status_text = f"{c(C.Y, status)}"
        elif status in ("error", "unhealthy"):
            dot = C.err()
            status_text = f"{c(C.R, status)}"
        else:
            dot = C.off()
            status_text = f"{c(C.GY, status)}"

        latency_str = f"  {c(C.GY, str(latency)+'ms P50')}" if latency else ""
        lines.append(f"│    {dot}  {c(C.W, name)}{' ' * max(1, 14 - len(name))}{status_text}{latency_str}")

    return '\n'.join(lines)


def _render_usage_block(stats: Dict[str, Any]) -> str:
    """Render usage statistics section."""
    lines = []
    lines.append(f"│  {c(C.BW, 'Usage')}")

    calls = stats.get("calls", 0)
    tok_in = stats.get("tokens_in", 0)
    tok_out = stats.get("tokens_out", 0)
    cost = stats.get("cost_usd", 0)
    savings = stats.get("savings_usd", 0)
    savings_pct = stats.get("savings_pct", 0)
    carbon = stats.get("carbon_kg", 0)

    def fmt_num(n):
        if n >= 1_000_000:
            return f"{n/1_000_000:.1f}M"
        if n >= 1_000:
            return f"{n/1_000:.1f}K"
        return str(n)

    def fmt_tokens(n):
        if n >= 1_000_000:
            return f"{n/1_000_000:.1f}M"
        if n >= 1_000:
            return f"{n/1_000:.0f}K"
        return str(n)

    lines.append(f"│    {c(C.GY, 'Calls:')}  {c(C.W, fmt_num(calls))}")

    if tok_in or tok_out:
        lines.append(f"│    {c(C.GY, 'Tokens:')} {c(C.W, fmt_tokens(tok_in))}{c(C.GY, ' in / ')}{c(C.W, fmt_tokens(tok_out))}{c(C.GY, ' out')}")

    if savings > 0:
        lines.append(f"│    {c(C.GY, 'Saved:')}  {c(C.G, '$' + f'{savings:.2f}')}  {c(C.GY, f'({savings_pct:.1f}% vs premium)')}")
    elif cost > 0:
        lines.append(f"│    {c(C.GY, 'Cost:')}  {c(C.W, '$' + f'{cost:.4f}')}")

    if carbon > 0:
        lines.append(f"│    {c(C.GY, 'Carbon:')}{c(C.G, ' 🌱')} {carbon:.4f} kg CO₂")

    drift_alerts = stats.get("drift_alerts", 0)
    drift_healthy = stats.get("drift_healthy", True)
    if drift_alerts > 0:
        lines.append(f"│    {c(C.GY, 'Drift:')}  {c(C.Y if drift_alerts < 5 else C.R, str(drift_alerts) + ' alerts')}")
    elif not drift_healthy:
        lines.append(f"│    {c(C.GY, 'Drift:')}  {c(C.R, 'unhealthy')}")
    else:
        lines.append(f"│    {c(C.GY, 'Drift:')}  {c(C.G, '●')}{c(C.GY, ' stable')}")

    return '\n'.join(lines)


def _render_activity_block(activity: List[Dict[str, Any]]) -> str:
    """Render recent activity section."""
    lines = []
    lines.append(f"│  {c(C.BW, 'Recent')}")

    if not activity:
        lines.append(f"│    {c(C.GY, '(no recent activity)')}")
        return '\n'.join(lines)

    for event in activity[:6]:
        ts = event.get("ts", "") or event.get("time", "")
        if isinstance(ts, (int, float)):
            ts_str = datetime.fromtimestamp(ts).strftime("%H:%M:%S")
        else:
            ts_str = str(ts)[:8]

        action = event.get("action", event.get("type", ""))
        status = event.get("status", event.get("result", "ok"))
        detail = event.get("detail", event.get("message", ""))

        if status in ("ok", "success", "pass", True):
            status_dot = C.ok()
            status_color = C.G
        elif status in ("fail", "error", "503", "timeout"):
            status_dot = C.err()
            status_color = C.R
        else:
            status_dot = C.warn()
            status_color = C.Y

        detail_str = f"  {c(C.GY, detail[:48])}" if detail else ""
        lines.append(f"│    {c(C.GY, ts_str)}  {status_dot}  {c(status_color, action[:20])}{detail_str}")

    return '\n'.join(lines)


def _render_dashboard_link(stats: Dict[str, Any]) -> str:
    """Render dashboard URL and last update time."""
    try:
        from correctover.dashboard import dashboard_url
        url = dashboard_url()
    except Exception:
        url = None

    left = f"  {c(C.GY, 'Web:')}  {c(C.BB, url or 'http://localhost:8765')}  {c(C.DIM, '(nb.dashboard())')}"
    right = f"{c(C.GY, 'Updated:')} {c(C.GY, datetime.now().strftime('%H:%M:%S'))}"

    pad = W - len(left) - len(right) - 4
    if pad < 2:
        pad = 2

    return f"│{left}{' ' * pad}{right}│"


def _render_cta_block() -> str:
    """Render conversion CTA at the bottom of the status dashboard."""
    lines = []
    sep = f"│{c(C.DIM, '─' * (W - 2))}│"
    blank = f"│{' ' * (W - 2)}│"

    lines.append(sep)
    lines.append(f"│  {c(C.BOLD, '🚀 升级 Pro 解锁全能力')}{' ' * (W - 34)}│")
    lines.append(blank)
    lines.append(f"│    {c(C.CYAN, '📦')}  pip install correctover-sdk{' ' * (W - 37)}│")
    lines.append(f"│    {c(C.CYAN, '🌐')}  文档 & 定价 → {c(C.BOLD_WHITE, 'https://correctover.cn')}{' ' * (W - 53)}│")
    lines.append(f"│    {c(C.CYAN, '🆓')}  7 天全功能试用{' ' * (W - 27)}│")
    lines.append(f"│    {c(C.CYAN, '🏢')}  企业定制 → {c(C.BOLD_WHITE, 'wangguigui@correctover.cn')}{' ' * (W - 59)}│")
    lines.append(blank)
    lines.append(sep)
    return '\n'.join(lines)


# ── Public API ────────────────────────────────────────────────

def status(watch: bool = False, interval: int = 5):
    """终端仪表盘 — 实时查看授权、Provider 健康、用量统计。

    Args:
        watch: 是否持续监控（每 interval 秒刷新）
        interval: 刷新间隔（秒）
    """
    global W

    try:
        W = _term_width()
        if W < 60:
            W = 72
        if W > 120:
            W = 120
    except Exception:
        W = 72

    if watch:
        try:
            _watch_loop(interval)
            return
        except KeyboardInterrupt:
            print(f"\n{c(C.GY, '  status 已退出')}")
            return

    _render_once()


def _render_once():
    """Single render of the terminal dashboard."""
    info = _get_license_info()
    providers = _get_provider_health()
    stats = _get_usage_stats()
    activity = _get_recent_activity()

    blocks = [
        _render_header(info),
        _render_license_block(info),
        _render_provider_block(providers),
        _render_usage_block(stats),
        _render_activity_block(activity),
        _render_dashboard_link(stats),
        _render_cta_block(),
        f"└{'─' * (W - 2)}┘",
    ]

    output = '\n'.join(blocks)
    print()
    print(output)
    print()


def _watch_loop(interval: int):
    """Watch mode — re-render every `interval` seconds."""
    try:
        while True:
            # Clear previous output (move cursor up)
            if USE_COLOR:
                sys.stdout.write("\033[?25l")  # hide cursor
                sys.stdout.flush()

            _render_once()

            # Countdown
            for remaining in range(interval, 0, -1):
                if USE_COLOR:
                    sys.stdout.write(
                        f"  {c(C.GY, '下一次刷新')} {c(C.W, str(remaining))}{c(C.GY, '秒')}  "
                        f"{c(C.DIM, '(Ctrl+C 退出)')}   "
                    )
                    sys.stdout.flush()
                time.sleep(1)

            # Move cursor up to overwrite
            if USE_COLOR:
                # Count lines rendered + countdown line + blank line + header lines
                line_count = 20  # approximate, safe over-estimate
                sys.stdout.write(f"\033[{line_count}A")
                sys.stdout.flush()

    except KeyboardInterrupt:
        pass
    finally:
        if USE_COLOR:
            sys.stdout.write("\033[?25h")  # show cursor
            sys.stdout.flush()
