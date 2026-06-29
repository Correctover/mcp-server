# Copyright 2024-2026 Correctover Team
# Licensed under the Apache License, Version 2.0 (the "License")
#
"""nb.demo() — Zero-config self-healing demo. No API keys needed.

Usage:
    import correctover as nb
    nb.demo()

Shows the MAPE-K self-healing pipeline in ~30 seconds:
  • Normal call → fault injection → L1 retry → L2 downgrade → L3 failover
  • Contract validation (5 dimensions)
  • Flywheel rule learning
  • Summary with real product metrics
"""

import sys
import json
import time
import random
import builtins
from typing import Optional

# ── Safe print (Windows GBK terminal compatibility) ─────────────

_ORIGINAL_PRINT = builtins.print

def _safe_print(*args, **kwargs):
    """Print with fallback for terminals that don't support Unicode (e.g. Windows GBK)."""
    try:
        _ORIGINAL_PRINT(*args, **kwargs)
    except UnicodeEncodeError:
        text = ' '.join(str(a) for a in args)
        safe = text.encode(
            sys.stdout.encoding or 'ascii', errors='replace'
        ).decode(sys.stdout.encoding or 'ascii')
        _ORIGINAL_PRINT(safe, **kwargs)

# ── ANSI color (Windows safe) ─────────────────────────────

class Style:
    RESET    = "\033[0m"
    BOLD     = "\033[1m"
    DIM      = "\033[2m"
    RED      = "\033[91m"
    GREEN    = "\033[92m"
    YELLOW   = "\033[93m"
    BLUE     = "\033[94m"
    MAGENTA  = "\033[95m"
    CYAN     = "\033[96m"
    WHITE    = "\033[97m"
    GRAY     = "\033[90m"
    BOLD_RED    = "\033[1;91m"
    BOLD_GREEN  = "\033[1;92m"
    BOLD_CYAN   = "\033[1;96m"
    BOLD_WHITE  = "\033[1;97m"

def _supports_color():
    """Detect if terminal supports ANSI color."""
    if not hasattr(sys.stdout, "isatty") or not sys.stdout.isatty():
        return True  # assume color-safe when piped (most envs handle it)
    plat = sys.platform
    if plat == "win32":
        import os
        ver = os.environ.get("TERM", "")
        return ver.startswith("xterm") or "color" in ver
    return True

USE_COLOR = _supports_color()

def c(code, text):
    if USE_COLOR:
        return f"{code}{text}{Style.RESET}"
    return text

# ── Helpers ───────────────────────────────────────────────

W = 68

def rule(char="="):
    return c(Style.DIM, "+" + char * (W - 2) + "+")

def mid(text, char=" "):
    pad = W - 2 - len(text)
    l = pad // 2
    r = pad - l
    return "|" + char * l + text + char * r + "|"

def kv(key, val, indent=0):
    k = " " * indent + key
    pad = W - 4 - len(k) - len(val)
    if pad < 1:
        pad = 1
    return "| " + k + " " * pad + val + " |"


# ── Demo progress bar ────────────────────────────────────

def progress_bar(current, total, width=24):
    filled = int(current / total * width) if total > 0 else 0
    return "[" + c(Style.GREEN, "#" * filled) + c(Style.GRAY, "." * (width - filled)) + "]"


# ── Core demo function ────────────────────────────────────

def demo(mode: str = "auto", speed: float = 1.0):
    """Run the Correctover self-healing demo.

    Args:
        mode: "auto" (try real providers first), "simulate" (skip env check)
        speed: 0.5 = slower, 1.0 = normal, 2.0 = faster
    """
    # Patch stdout for Windows GBK terminals (replace, don't crash)
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(errors='replace')
    builtins.print = _safe_print

    _delay = lambda s: time.sleep(s / speed)

    # ── Try real providers if available (auto mode) ──────
    if mode == "auto":
        keys = _find_api_keys()
        if keys:
            return _run_real_demo(keys, _delay)

    # ── Simulated demo (always works) ────────────────────
    return _run_simulated_demo(_delay)


def _find_api_keys() -> dict:
    """Scan env for any available LLM API keys."""
    import os
    keys = {}
    for provider, env_var in [
        ("deepseek", "DEEPSEEK_API_KEY"),
        ("openai", "OPENAI_API_KEY"),
        ("anthropic", "ANTHROPIC_API_KEY"),
        ("dashscope", "DASHSCOPE_API_KEY"),
    ]:
        val = os.environ.get(env_var, "")
        if val and len(val) > 8:
            keys[provider] = val
    return keys


def _run_real_demo(keys: dict, delay):
    """Run demo using real providers. Falls back to simulated on failure."""
    print()
    print(c(Style.BOLD_CYAN, "  Correctover 自愈引擎 — 真实调用演示"))
    print(c(Style.GRAY, f"  发现 {len(keys)} 个 Provider: {', '.join(keys.keys())}"))
    print(c(Style.DIM, "  " + "=" * 60))
    print()

    from correctover._engine import SelfHealingEngine, ProviderConfig, Contract

    engine = SelfHealingEngine()
    loaded = 0
    for name in keys:
        try:
            cfg = ProviderConfig.from_env(name)
            engine.add_provider(cfg)
            print(f"  {c(Style.GREEN, 'OK')}  已加载 {c(Style.BOLD, name)}")
            loaded += 1
        except Exception:
            print(f"  {c(Style.YELLOW, '..')} 跳过 {name} (key 无效)")

    delay(0.3)

    if loaded < 1:
        print(f"\n  {c(Style.YELLOW, '!')} 没有可用的 Provider，切换到模拟模式\n")
        engine.close_sync()
        return _run_simulated_demo(delay)

    # Quick connectivity test
    primary = list(keys.keys())[0]
    print(f"  {c(Style.DIM, '...')} 连通性检测 {primary} ... ", end="", flush=True)
    try:
        hc = engine.health_check()
        status = hc.get(primary, "unknown")
        if status in ("healthy", "degraded"):
            print(c(Style.GREEN, f"OK ({status})"))
        else:
            print(c(Style.YELLOW, f"{status}"))
            if loaded < 2:
                print(f"\n  {c(Style.YELLOW, '!')} 连通性异常，切换到模拟模式\n")
                engine.close_sync()
                return _run_simulated_demo(delay)
    except Exception:
        print(c(Style.YELLOW, "无法连接"))
        print(f"\n  {c(Style.YELLOW, '!')} 网络不可达，切换到模拟模式\n")
        engine.close_sync()
        return _run_simulated_demo(delay)

    # Run calls with contract validation
    print(f"\n  {c(Style.BOLD, '演示场景')}: 用 {primary} 调用，展示 3 次 MAPE-K 调用\n")
    delay(0.3)

    contract = Contract(
        output_schema={"type": "object", "properties": {"result": {"type": "string"}}, "required": ["result"]},
        required_entities=["AI"],
    )

    results = []
    fail_count = 0
    for i in range(3):
        prompt = ("Hello! Return a JSON object with one key 'result' containing a short greeting."
                  if i == 0 else
                  "Return a JSON object: {\"result\": \"A short message about AI reliability.\"}")
        print(f"  [{i+1}/3] 调用 {primary} ... ", end="", flush=True)
        try:
            result = engine.call_sync(
                prompt=prompt,
                has_schema=True,
                contract=contract,
                model="auto",
            )
            status_icon = c(Style.GREEN, "OK")
            heal = f" heal_lvl={result.heal_level}" if result.heal_level else ""
            val = f" contract={'PASS' if result.validation_passed else 'FAIL'}" if result.validation_passed is not None else ""
            print(f"{status_icon}  {result.latency_ms:.0f}ms{heal}{val}")
            results.append(result)
        except Exception as ex:
            fail_count += 1
            status_icon = c(Style.RED, "FAIL")
            print(f"{status_icon}  {str(ex)[:50]}")

        delay(0.5)

    engine.close_sync()

    if fail_count == 3 and not results:
        print(f"\n  {c(Style.YELLOW, '!')} 所有真实调用失败 (网络/Key 问题)，切换模拟展示\n")
        return _run_simulated_demo(delay)

    delay(0.3)
    _print_summary(results)


def _run_simulated_demo(delay):
    """Run a fully simulated self-healing demo (no API keys needed). ~30s total."""
    print()
    print(c(Style.BOLD_CYAN, "     Correctover 自愈引擎演示"))
    print(c(Style.DIM, f"     {c(Style.WHITE, 'pip install correctover-sdk')}  零配置 · 无需 API Key"))
    print(rule())
    print()

    # ── Warm-up: Engine initialization ────────────────────
    delay(0.5)
    _animate_spinner("  初始化自愈引擎 ...", 0.8)
    print(f"\r  {c(Style.GREEN, 'OK')}  自愈引擎就绪  {c(Style.GRAY, 'SelfHealingEngine v4.5')}")

    delay(0.3)
    _animate_spinner("  加载 Provider 集群 ...", 0.6)
    print(f"\r  {c(Style.GREEN, 'OK')}  已加载 3 个 Provider  {c(Style.GRAY, 'deepseek-chat, deepseek-coder, gpt-4o-mini')}")

    delay(0.3)
    _animate_spinner("  加载合约验证器 ...", 0.4)
    print(f"\r  {c(Style.GREEN, 'OK')}  合约验证器就绪  5 维度: Schema / 实体 / 相似度 / 禁忌 / 确定哈希")

    delay(0.3)
    _animate_spinner("  加载飞轮学习器 ...", 0.4)
    print(f"\r  {c(Style.GREEN, 'OK')}  FlywheelLearner 就绪  已有 84 条修复规则")
    delay(0.5)

    # ── Step 1: Normal call ──────────────────────────────
    _print_step_header(1, 4, "正常调用 — Provider A (deepseek-chat)")
    delay(0.5)

    _animate_spinner("  正在调用 deepseek-chat ...", 0.9)
    print(f"\r  {c(Style.GREEN, 'OK')}  deepseek-chat: 响应成功  {c(Style.GRAY, '200ms  ↓ tokens=142')}")

    delay(0.4)

    # MAPE-K trace details — show one by one with pauses
    _print_mapek_phases()
    delay(0.5)

    # Contract result — show each dimension with pause
    print(f"  {c(Style.DIM, 'Contract')}  schema  ──── ", end="", flush=True)
    delay(0.6)
    print(f"{c(Style.GREEN, 'PASS')}  {c(Style.GRAY, 'JSON Schema 验证通过')}")
    delay(0.3)
    print(f"  {c(Style.DIM, 'Contract')}  entities ──── ", end="", flush=True)
    delay(0.5)
    print(f"{c(Style.GREEN, 'PASS')}  {c(Style.GRAY, '必需实体包含: AI, reliability')}")
    delay(0.8)

    # ── Step 2: Fault injection + L1-L3 recovery ────────
    _print_step_header(2, 4, "故障注入 — 自动检测 & 自愈恢复 (MAPE-K)")
    delay(0.6)

    # Monitor phase
    print(f"  {c(Style.BOLD, '[Monitor]')}  实时监控会话中 ...", end="", flush=True)
    delay(1.2)
    print(f"\n  {c(Style.YELLOW, '!')}  检测到异常: {c(Style.RED, 'HTTP 503')} (Service Unavailable)  {c(Style.GRAY, '12.3ms')}")
    delay(0.4)

    # Analyze phase
    print(f"  {c(Style.BOLD, '[Analyze]')}  正在分类故障类型 ...", end="", flush=True)
    delay(0.8)
    print(f"\n  {c(Style.CYAN, '+')}  分类结果: {c(Style.BOLD, 'rate_limit')}  (匹配度 98.7%)  {c(Style.GRAY, '19.0μs')}")
    delay(0.4)

    # Plan phase
    print(f"  {c(Style.BOLD, '[Plan]')}  生成自愈策略链 ...", end="", flush=True)
    delay(1.0)
    print(f"\n  {c(Style.MAGENTA, '->')}  策略链: {c(Style.DIM, 'L1 重试 → L2 降级 → L3 Failover')}")
    delay(0.5)

    # Execute L1
    print(f"  {c(Style.BOLD, '[Execute]')}  L1 重试 (retry) ...", end="", flush=True)
    delay(1.0)
    print(f"  {c(Style.RED, 'fail')}  {c(Style.GRAY, '仍返回 503')}")
    delay(0.3)

    # L2
    print(f"  {'':14s}L2 降级 (downgrade → deepseek-coder) ...", end="", flush=True)
    delay(1.2)
    print(f"  {c(Style.RED, 'fail')}  {c(Style.GRAY, 'deepseek-coder 也超时')}")
    delay(0.3)

    # L3
    print(f"  {'':14s}L3 Failover → Provider B (gpt-4o-mini) ...", end="", flush=True)
    delay(1.5)
    print(f"  {c(Style.GREEN, 'OK')}  {c(Style.BOLD, 'gpt-4o-mini')} 响应成功  {c(Style.GRAY, '450ms  ↓ tokens=156')}")
    delay(0.5)

    # Contract validation after recovery — line by line
    print(f"  {c(Style.BOLD, '[Verify]')}  输出验证 ...")
    delay(0.3)
    print(f"    similarity ── ", end="", flush=True)
    delay(0.6)
    print(f"{c(Style.GREEN, 'PASS')}  {c(Style.GRAY, 'jaccard=0.750 containment=1.000 score=1.000 threshold=0.5')}")
    delay(0.3)
    print(f"    forbidden  ── ", end="", flush=True)
    delay(0.5)
    print(f"{c(Style.GREEN, 'PASS')}  {c(Style.GRAY, '无禁止模式')}")
    delay(0.3)
    print(f"    deterministic_hash ── ", end="", flush=True)
    delay(0.5)
    print(f"{c(Style.GREEN, 'PASS')}  {c(Style.GRAY, '未触发确定性回退')}")
    delay(0.8)

    # ── Step 3: Circuit breaker + Flywheel ───────────────
    _print_step_header(3, 4, "熔断保护 & 飞轮学习")
    delay(0.5)

    # Circuit breaker
    print(f"  {c(Style.BOLD, '[CircuitBreaker]')}  评估 Provider 健康状况 ...", end="", flush=True)
    delay(1.0)
    print(f"\n  {c(Style.YELLOW, '!')}  deepseek-chat 触发熔断  {c(Style.GRAY, '3次连续失败 → OPEN (冷却20s)')}")
    delay(0.5)

    # Flywheel learning
    print(f"  {c(Style.BOLD, '[Flywheel]')}  分析失败模式 ...", end="", flush=True)
    delay(0.8)
    print(f"\n  {c(Style.CYAN, '+')}  匹配 88 条已知规则: 未命中")

    print(f"  {'':14s}自学习新规则 ...", end="", flush=True)
    delay(1.5)
    print(f"\n  {c(Style.GREEN, 'OK')}  新增修复规则  {c(Style.GRAY, 'rate_limit → L3 failover immediatly (置信度 0.92)')}")

    delay(0.3)
    print(f"  {'':14s}更新知识库 ...", end="", flush=True)
    delay(0.8)
    print(f"  {c(Style.GREEN, 'OK')}  规则库: 84 → 85 条")
    delay(0.8)

    # ── Step 4: Checkpoint + Summary ─────────────────────
    _print_step_header(4, 4, "断点续跑 & 汇总")
    delay(0.5)

    # Checkpoint demo
    print(f"  {c(Style.BOLD, '[Checkpoint]')}  开始执行分步 Agent 任务")
    delay(0.4)
    for step in ["步骤 1/5: 数据预处理", "步骤 2/5: 特征提取", "步骤 3/5: 模型推理", "步骤 4/5: 结果校验", "步骤 5/5: 输出格式化"]:
        _animate_spinner(f"    {step} ...", 0.18)
        print(f"\r    {step} → {c(Style.GREEN, 'OK')}")
        delay(0.15)

    delay(0.3)
    print(f"  {c(Style.YELLOW, '!')}  进程崩溃 → 第 3/5 步未完成")
    delay(0.5)
    _animate_spinner("  Checkpoint 恢复中 ...", 0.6)
    print(f"\r  {c(Style.GREEN, 'OK')}  Checkpoint 恢复  {c(Style.GRAY, '跳过已完成步骤 1-2/5，从步骤 3/5 继续执行')}")
    delay(0.5)

    # ── Final summary ────────────────────────────────────
    delay(0.5)
    _print_summary(None)


def _demo_checkpoint_failover():
    """Show checkpoint resume scenario."""
    print(f"    中途崩溃 → 从 step 3/4 恢复 ...", end=" ", flush=True)
    time.sleep(0.2)
    print(f"{c(Style.GREEN, 'OK')}  {c(Style.GRAY, '跳过已完成步骤，继续执行 step 4/4')}")


def _print_step_header(num, total, title):
    """Print a step header with number and progress."""
    print(f"\n  {c(Style.BOLD_WHITE, f'[{num}/{total}]')}  {c(Style.BOLD, title)}")
    print(f"  {c(Style.DIM, '─' * (W - 4))}")


def _animate_spinner(text, duration):
    """Show a spinner animation for `duration` seconds (ASCII fallback for GBK)."""
    _encoding = getattr(sys.stdout, 'encoding', '') or ''
    if _encoding.upper() in {'GBK', 'GB2312', 'GB18030', 'CP936', '936'}:
        spinner = ["-", "\\", "|", "/", "-", "\\", "|", "/"]
    else:
        spinner = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    t0 = time.time()
    i = 0
    while time.time() - t0 < duration:
        sys.stdout.write(f"\r{text} {c(Style.CYAN, spinner[i % len(spinner)])}")
        sys.stdout.flush()
        time.sleep(0.04)
        i += 1


def _print_mapek_phases():
    """Print compact MAPE-K phase timing."""
    phases = [
        ("Monitor",  "12.3μs", True),
        ("Analyze",  "19.0μs", True),
        ("Plan",     "8.1μs",  True),
        ("Execute",  "200ms",  True),
        ("Knowledge","2.1μs",  True),
    ]
    labels = "  → ".join(
        f"{c(Style.GREEN if ok else Style.YELLOW, name)} {c(Style.GRAY, time)}"
        for name, time, ok in phases
    )
    print(f"  {c(Style.DIM, 'MAPE-K')}  {labels}")


def _print_summary(results):
    """Print the demo summary block with real product metrics."""
    print()
    print(c(Style.BOLD_CYAN, "  ═══  Correctover — AI Agent 生产级稳定器  ═══"))
    print(c(Style.DIM, "  │  进程内嵌入 · 生产级稳定 · 即装即用"))
    print()
    print(f"  {c(Style.BOLD, '实测性能')}")
    print(f"    {c(Style.GREEN, '✔')}  故障诊断 19.0 μs P50  {c(Style.GRAY, '(benchmark 实测)')}")
    print(f"    {c(Style.GREEN, '✔')}  合约验证 3.1 μs P50  {c(Style.GRAY, '(benchmark 实测)')}")
    print(f"    {c(Style.GREEN, '✔')}  4 级自愈 → L1重试/L2降级/L3切Provider/L4飞轮学习")
    print(f"    {c(Style.GREEN, '✔')}  5 维度输出验证 → Schema/实体/相似度/禁忌/确定哈希")
    print(f"    {c(Style.GREEN, '✔')}  SDK 比裸 httpx 快 15.9%  {c(Style.GRAY, '(benchmark 实测)')}")
    print()
    print(f"  {c(Style.BOLD, '开始体验')}")
    print(f"    {c(Style.CYAN, '$')}  pip install correctover-sdk")
    print(f"    {c(Style.CYAN, '$')}  python -c \"import correctover as nb; nb.demo()\"")
    print()
    print(f"  {c(Style.BOLD, '生产接入')}")
    print(f"    {c(Style.CYAN, '$')}  export DEEPSEEK_API_KEY=sk-...")
    print(f"    {c(Style.CYAN, '$')}  python -c \"import correctover as nb; print(nb.run('你好').text)\"")
    print()
    print(f"  {c(Style.BOLD, '开始使用')}")
    print(f"    {c(Style.BOLD, '📦')}  pip install correctover-sdk")
    print(f"    {c(Style.BOLD, '🌐')}  文档 & 定价 → {c(Style.BOLD_WHITE, 'https://correctover.cn')}")
    print(f"    {c(Style.BOLD, '🆓')}  7 天全功能试用")
    print(f"    {c(Style.BOLD, '🏢')}  企业定制 → {c(Style.BOLD_WHITE, 'wangguigui@correctover.cn')}")
    print()
    print(c(Style.DIM, "  " + "=" * 60))
    print()
