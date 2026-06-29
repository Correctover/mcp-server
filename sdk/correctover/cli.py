# Copyright 2024-2026 Correctover Team
# Licensed under the Apache License, Version 2.0 (the "License")
# Correctover™ — Proprietary MAPE-K Adaptive Loop Architecture

#
"""Correctover CLI — Self-healing engine for LLM API calls.

Usage:
    nb-doctor scan              Scan environment for API keys and connectivity
    nb-doctor run               Start engine and run interactive test
    nb-doctor version           Show version
    nb-doctor status            License status & plan info
    nb-doctor upgrade           Upgrade to Pro
    nb-doctor auth <key>        Activate license key
    nb-doctor provider list     List configured providers
    nb-doctor provider status   Show provider health & costs
    nb-doctor route <prompt>    Test routing for a prompt
    nb-doctor checkpoint list   List all checkpointed agents
    nb-doctor checkpoint status <agent_id>  Show checkpoint status
    nb-doctor setup --provider deepseek --key sk-xxx   BYOK: 用自己的 API key
"""
import argparse
import sys
import os
import webbrowser

_print = print


def _scan_env():
    """Scan environment for API keys."""
    env_map = {
        "NVIDIA_API_KEY": ("nvidia", "https://integrate.api.nvidia.com/v1"),
        "DEEPSEEK_API_KEY": ("deepseek", "https://api.deepseek.com/v1"),
        "DASHSCOPE_API_KEY": ("dashscope", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        "OPENAI_API_KEY": ("openai", "https://api.openai.com/v1"),
        "ANTHROPIC_API_KEY": ("anthropic", "https://api.anthropic.com/v1"),
        "AZURE_OPENAI_API_KEY": ("azure", "Azure OpenAI"),
        "GOOGLE_API_KEY": ("google", "Google Gemini"),
        "GROQ_API_KEY": ("groq", "https://api.groq.com/openai/v1"),
    }
    found = []
    for env_var, (name, base_url) in env_map.items():
        key = os.environ.get(env_var, "")
        if key:
            found.append((name, env_var, True))
        else:
            found.append((name, env_var, False))
    return found


def cmd_scan(args):
    """扫描环境 + 可选生成修复脚本。"""
    fix_mode = getattr(args, "fix", False)
    json_mode = getattr(args, "json_output", False)

    if fix_mode or json_mode:
        from correctover._checkup import scan_structured
        result = scan_structured()

        if json_mode:
            import json
            # 简化为只输出关键字段
            output = {
                "version": result["version"],
                "timestamp": result["timestamp"],
                "summary": result["summary"],
                "checks": [
                    {"id": c["id"], "name": c["name"], "status": c["status"],
                     "detail": c["detail"], "fix_code": c.get("fix_code"),
                     "docs_url": c.get("docs_url")}
                    for c in result["checks"]
                ],
            }
            _print(json.dumps(output, ensure_ascii=False, indent=2))
            return

        # fix_mode: 输出人类可读 + 生成脚本
        _print("\n  🛡  Correctover — 全量诊断扫描")
        _print("  " + "─" * 55)
        summary = result["summary"]
        _print(f"  📊 {summary['passed']}/{summary['total']} 通过"
               f"  ❌{summary['failed']} 问题  ⚠️{summary['warn']} 警告")
        _print()

        for c in result["checks"]:
            icon = {"pass": "✅", "fail": "❌", "warn": "⚠️"}.get(c["status"], "❓")
            action = ""
            if c.get("fix_code") and c["status"] != "pass":
                action = "  💡 有修复方案"
            _print(f"  {icon} {c['name']:28s} {c['detail'][:50]}{action}")

        if result.get("fix_script"):
            fix_path = os.path.join(os.getcwd(), "correctover_fix.py")
            try:
                with open(fix_path, "w", encoding="utf-8") as f:
                    f.write(result["fix_script"])
                _print(f"\n  ✅ 修复脚本已生成: {fix_path}")
                _print(f"  ▶️  运行: python {fix_path}")
                _print(f"     查看生成的自愈配置代码并复制到你的项目中")
            except Exception as e:
                _print(f"\n  ❌ 无法写入修复脚本: {e}")
                _print(f"\n  ── 修复脚本内容如下（可手动复制）──")
                # 输出前几行
                for line in result["fix_script"].split("\n")[:30]:
                    _print(f"  {line}")
                _print("  ── 以上为修复脚本开头部分 ──")
        _print()
        return

    # 老版本 scan（只扫 key）
    providers = _scan_env()
    print("\n  Correctover — Environment Scan")
    print("  " + "─" * 45)
    healthy = 0
    for name, env_var, has_key in providers:
        icon = "✅" if has_key else "⬜"
        print(f"  {icon} {name:12s} {env_var}")
        if has_key:
            healthy += 1
    print(f"\n  Found {healthy}/{len(providers)} providers")
    if healthy < 2:
        print("  ⚠️  Fewer than 2 providers — self-healing needs redundancy!")
    print()


def cmd_run(args):
    from . import run as nb_run
    engine = nb_run(verbose=True)
    try:
        result = engine.call_sync("Say exactly: Correctover is alive!")
        print(f"\n  Test call result: {result[:100]}")
    except Exception as e:
        print(f"\n  Test call failed: {e}")
    try:
        stats = engine.get_stats()
        print(f"\n  Stats: calls={stats['call_count']}, heal={stats['heal_count']}, rate={stats['heal_rate']}")
    except Exception:
        pass


def cmd_version(args):
    try:
        from correctover import __version__
        print(f"Correctover v{__version__}")
    except Exception:
        print("Correctover (version unknown)")


def cmd_status(args):
    """Show license status and plan info."""
    try:
        from correctover import (
            get_plan, is_pro, is_trial, is_enterprise,
            days_remaining, plan_summary, max_providers, max_heal_level,
        )
    except Exception:
        print("  ❌ Could not load license module")
        return

    plan = get_plan()
    is_pro_user = is_pro()
    is_trial_user = is_trial()
    is_ent = is_enterprise()

    # Plan icon
    if is_ent:
        icon, label = "🏢", "Enterprise"
    elif is_pro_user:
        icon, label = "⚡", "Pro"
    elif is_trial_user:
        icon, label = "🧪", "Trial"
    else:
        icon, label = "🆓", "Free"

    print(f"\n  Correctover License Status")
    print(f"  {'─' * 40}")
    print(f"  {icon} Plan: {label}")
    try:
        print(f"  📅 Days remaining: {days_remaining()}")
    except Exception:
        pass
    print(f"  🔧 Max providers: {max_providers()}")
    print(f"  🩹 Max heal level: L{max_heal_level()}")

    # Feature access — based on actual consume_repair() behavior
    has_healing = is_pro_user or is_ent
    features = [
        ("Health check & diagnosis", True),
        ("MAPE-K trace", True),
        ("Metrics & Prometheus", True),
        ("L1 Smart Retry", has_healing),
        ("L2 Model Downgrade", has_healing),
        ("L3 Provider Failover", has_healing),
        ("L4 Flywheel Learning", has_healing),
        ("Contract Validation", has_healing),
        ("Semantic Topology", has_healing),
    ]
    print(f"\n  Feature Access:")
    for feat, allowed in features:
        status = "✅" if allowed else "🔒 (Pro)"
        print(f"  {status} {feat}")

    # Upgrade prompt for free users
    if not is_pro_user and not is_ent:
        print(f"\n  💡 Diagnosis is free, healing requires Pro.")
        print(f"     nb-doctor upgrade  →  unlock L1-L4 self-healing + contracts")
    print()


def cmd_upgrade(args):
    """Upgrade to Pro — opens browser to purchase page."""
    try:
        from correctover import is_pro, is_enterprise
        if is_pro() or is_enterprise():
            print("\n  ✅ You already have a Pro or Enterprise plan.")
            return
    except Exception:
        pass

    buy_url = "https://correctover.cn/buy"
    print("\n  🚀 Upgrade to Correctover Pro")
    print("  " + "─" * 40)
    print("  Pro unlocks:")
    print("  ✅ L3 provider failover (unlimited)")
    print("  ✅ L4 flywheel learning (93 rules)")
    print("  ✅ Contract validation (5 strategies)")
    print("  ✅ Semantic topology (3-domain protection)")
    print("  ✅ Unlimited providers")
    print()
    print(f"  Opening: {buy_url}")
    print()

    try:
        webbrowser.open(buy_url)
        print("  ✅ Browser opened. After purchase:")
        print("     nb-doctor auth NB-PRO-xxxxx")
    except Exception:
        print(f"  📋 Visit {buy_url} to purchase")
        print("     Then run: nb-doctor auth <your-key>")
    print()


def cmd_auth(args):
    """Activate a license key."""
    if not args.key:
        print("\n  ❌ Usage: nb-doctor auth <license-key>")
        print("     Example: nb-doctor auth NB-PRO-eyJ...\n")
        return

    key = args.key.strip()
    print(f"\n  🔑 Activating license...")

    try:
        from correctover import activate
        info = activate(key)
        if info and info.get("valid"):
            plan = info.get("plan", "unknown")
            exp = info.get("expires_at", "unknown")
            print(f"  ✅ Activated: {plan}")
            if exp and exp != 0:
                import time
                try:
                    days = (exp - int(time.time())) // 86400
                    print(f"  📅 Valid for: {days} days")
                except Exception:
                    print(f"  📅 Expires: {exp}")
            print(f"\n  Run 'nb-doctor status' to see your plan.\n")
        else:
            msg = info.get("message", "Unknown error") if info else "Activation failed"
            print(f"  ❌ {msg}")
            print(f"  Check your key or contact wangguigui@correctover.cn\n")
    except Exception as e:
        print(f"  ❌ Activation error: {e}")
        print(f"  Try: nb-doctor auth <your-key>\n")


def cmd_setup(args):
    """BYOK setup: configure your own API key for a provider."""
    import json, os

    PROVIDERS = {
        "deepseek":  {"env": "DEEPSEEK_API_KEY",  "url": "https://api.deepseek.com/v1",       "model": "deepseek-v4-flash"},
        "agnes":     {"env": "AGNES_API_KEY",      "url": "https://apihub.agnes-ai.com/v1",    "model": "agnes-2.0-flash"},
        "openai":    {"env": "OPENAI_API_KEY",     "url": "https://api.openai.com/v1",         "model": "gpt-4o-mini"},
        "anthropic": {"env": "ANTHROPIC_API_KEY",  "url": "https://api.anthropic.com/v1",      "model": "claude-haiku-4-5-20251001"},
    }

    provider = (args.provider or "").lower()
    key = args.key or ""

    if not provider or not key:
        print("用法: nb-doctor setup --provider deepseek --key sk-你的key")
        print("支持的 provider:", ", ".join(PROVIDERS.keys()))
        return

    if provider not in PROVIDERS:
        print(f"不支持的 provider: {provider}")
        print("支持:", ", ".join(PROVIDERS.keys()))
        return

    cfg = PROVIDERS[provider]

    # Write to ~/.correctover/config.json
    config_dir = os.path.expanduser("~/.correctover")
    config_file = os.path.join(config_dir, "config.json")
    os.makedirs(config_dir, exist_ok=True)

    try:
        with open(config_file) as f:
            config = json.load(f)
    except Exception:
        config = {}

    config.setdefault("providers", {})[provider] = {
        "api_key": key,
        "base_url": cfg["url"],
        "default_model": cfg["model"],
    }
    config["default_provider"] = provider

    with open(config_file, "w") as f:
        json.dump(config, f, indent=2)

    # Also set environment variable for current session
    os.environ[cfg["env"]] = key

    # Set persistent env var (Windows)
    try:
        import subprocess
        subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f'[System.Environment]::SetEnvironmentVariable("{cfg["env"]}", "{key}", "User")'],
            capture_output=True
        )
    except Exception:
        pass

    print(f"OK  Provider: {provider}")
    print(f"    API Key: {key[:8]}...{key[-4:]}")
    print(f"    Base URL: {cfg['url']}")
    print(f"    Default model: {cfg['model']}")
    print(f"    Config saved: {config_file}")
    print()
    print("测试连接中...")
    try:
        from correctover._engine import SelfHealingEngine, ProviderConfig
        engine = SelfHealingEngine()
        engine.add_provider(ProviderConfig(
            name=provider, base_url=cfg["url"],
            api_key=key, models=[cfg["model"]]
        ))
        result = engine.call_sync("hello", model=cfg["model"])
        print(f"连接成功！耗时 {round(result.latency_ms)}ms")
    except Exception as e:
        print(f"连接测试失败: {e}")
        print("请检查 API key 是否正确")


def cmd_provider(args):
    """Provider management commands."""
    subcmd = getattr(args, "provider_subcmd", None)

    if subcmd == "list":
        providers = _scan_env()
        print("\n  Correctover — Provider List")
        print("  " + "─" * 55)
        for name, env_var, has_key in providers:
            icon = "✅" if has_key else "⬜"
            key_status = "****..." if has_key else "no key"
            print(f"  {icon} {name:12s} {env_var:22s} {key_status}")
        print()

    elif subcmd == "status":
        try:
            from correctover.classifier import MODEL_COSTS, PROVIDER_MODELS
        except Exception:
            print("  ❌ Could not load provider data")
            return

        print("\n  Correctover — Provider Status & Pricing")
        print("  " + "─" * 65)
        print(f"  {'Provider':12s} {'Model':24s} {'Input/1M':>10s} {'Output/1M':>10s} {'Tier':>8s}")
        print("  " + "─" * 65)

        env_providers = _scan_env()
        available = {name for name, _, has_key in env_providers if has_key}

        for provider, models in PROVIDER_MODELS.items():
            for model in models:
                info = MODEL_COSTS.get(model, {})
                input_cost = f"${info.get('input', 0):.2f}" if info else "?"
                output_cost = f"${info.get('output', 0):.2f}" if info else "?"
                tier = info.get("tier", "?")
                icon = "✅" if provider in available else "⬜"
                print(f"  {icon} {provider:12s} {model:24s} {input_cost:>10s} {output_cost:>10s} {tier:>8s}")
        print()

    else:
        print("\n  Usage: nb-doctor provider <list|status>\n")


def cmd_route(args):
    """Test routing for a prompt."""
    prompt = getattr(args, "prompt", "")
    strategy = getattr(args, "strategy", "cost")
    if not prompt:
        print("\n  ❌ Usage: nb-doctor route \"your prompt here\"\n")
        return

    try:
        from correctover.router import Router
        from correctover.classifier import classify, COMPLEXITY_MODEL_MAP
    except Exception as e:
        print(f"  ❌ Router not available: {e}\n")
        return

    # Get available providers
    env_providers = _scan_env()
    available = [name for name, _, has_key in env_providers if has_key]
    if not available:
        available = ["openai", "anthropic", "deepseek"]

    router = Router(providers=available, strategy=strategy)
    decision = router.route(prompt, model="auto")

    complexity = classify(prompt)
    tier = COMPLEXITY_MODEL_MAP[complexity]

    _print(f"\n  Correctover — Routing Test")
    _print(f"  {'─' * 40}")
    _print(f"  Prompt: {prompt[:60]}{'...' if len(prompt) > 60 else ''}")
    _print(f"  Complexity: {complexity.value}")
    _print(f"  Model tier: {tier}")
    _print(f"  Strategy:   {strategy}")
    _print(f"  {'─' * 40}")
    _print(f"  → Provider: {decision.provider}")
    _print(f"  → Model:    {decision.model}")
    _print(f"  → Reason:   {decision.reason}")
    _print()


def cmd_diagnose(args):
    """Deep diagnostic — module health, provider connectivity, license, flywheel."""
    import importlib
    import time
    output_json = getattr(args, "json", False)
    results = {"timestamp": time.time(), "status": "ok", "checks": {}}

    def _report(name, status, detail=""):
        results["checks"][name] = {"status": status, "detail": detail}
        if output_json:
            return
        icon = "✅" if status == "pass" else "⚠️" if status == "warn" else "❌"
        _print(f"  {icon} {name:28s} {detail}")

    if not output_json:
        _print("  🔍 Correctover — Deep Diagnosis")
        _print(f"  {'─' * 55}")

    # ── 1. Module loading ──
    modules = [
        ("_engine", "SelfHealingEngine"),
        ("classifier", "classify"),
        ("router", "Router"),
        ("client", "Client"),
        ("checkpoint", "FileCheckpointStore"),
        ("gateway", "serve"),
        ("license", "activate"),
        ("telemetry", "TelemetryCollector"),
        ("_stats", "savings_report"),
        ("carbon", "CarbonTracker"),
        ("drift", "DriftMonitor"),
        ("free_provider", "setup_free_provider"),
    ]
    all_ok = True
    for mod_name, cls_name in modules:
        try:
            m = importlib.import_module(f"correctover.{mod_name}")
            getattr(m, cls_name)
            _report(f"mod:{mod_name}.{cls_name}", "pass")
        except Exception as e:
            all_ok = False
            _report(f"mod:{mod_name}.{cls_name}", "fail", str(e)[:60])

    # ── 2. Provider connectivity (env scan only, no API call) ──
    providers = _scan_env()
    available = [p for p in providers if p[2]]
    _report("providers", "pass" if available else "warn",
            f"{len(available)}/{len(providers)} have keys")

    # ── 3. License status ──
    try:
        from correctover import get_plan, is_pro, is_enterprise, is_expired, days_remaining, plan_summary
        plan = get_plan()
        remaining = days_remaining()
        pro = is_pro() or is_enterprise()
        expired = is_expired()
        lic_status = "pass" if pro and not expired else ("warn" if not expired else "fail")
        _report("license", lic_status,
                f"plan={plan} pro={pro} expired={expired} days_left={remaining}")
    except Exception as e:
        _report("license", "fail", str(e)[:60])

    # ── 4. Route health (test all 3 strategies) ──
    try:
        from correctover.router import Router
        from correctover.classifier import classify
        provider_names = [p[0] for p in providers if p[2]] or ["agnes", "deepseek"]
        for strategy in ["cost", "latency", "quality"]:
            router = Router(providers=provider_names, strategy=strategy)
            decision = router.route("hello world", model="auto")
            _report(f"route:{strategy}", "pass", f"→ {decision.provider}/{decision.model}")
    except Exception as e:
        _report("route:all", "warn", str(e)[:60])

    # ── 5. Flywheel status ──
    try:
        import os as _os2
        fw_path = _os2.path.expanduser("~/.correctover/flywheel_rules.json")
        if _os2.path.exists(fw_path):
            import json as _json2
            with open(fw_path) as f:
                rules = _json2.load(f)
            _report("flywheel", "pass", f"{len(rules)} rules cached")
        else:
            _report("flywheel", "warn", "no rules yet (first run)")
    except Exception as e:
        _report("flywheel", "warn", str(e)[:60])

    # ── 6. Checkpoint status ──
    try:
        from correctover.checkpoint import FileCheckpointStore
        store = FileCheckpointStore()
        agents = store.list_agents()
        _report("checkpoints", "pass" if agents else "warn",
                f"{len(agents)} agents" if agents else "none")
    except Exception as e:
        _report("checkpoints", "warn", str(e)[:60])

    # ── Overall verdict ──
    failures = sum(1 for c in results["checks"].values() if c["status"] == "fail")
    if failures:
        results["status"] = "fail"

    fix_mode = getattr(args, "fix", False)
    if fix_mode:
        from correctover._checkup import scan_structured
        scan_result = scan_structured()
        script = scan_result.get("fix_script", "")
        if script:
            fix_path = os.path.join(os.getcwd(), "correctover_fix.py")
            try:
                with open(fix_path, "w", encoding="utf-8") as f:
                    f.write(script)
                _print(f"  ✅ 修复脚本已生成: {fix_path}")
                _print(f"  ▶️  运行: python {fix_path}")
            except Exception as e:
                _print(f"  ❌ 无法写入修复脚本: {e}")

    if output_json:
        import json as _json3
        _print(_json3.dumps(results, indent=2))
    else:
        total = len(results["checks"])
        passed = sum(1 for c in results["checks"].values() if c["status"] == "pass")
        _print(f"  {'─' * 55}")
        _print(f"  Verdict: {passed}/{total} checks passed"
               f"  {'🎉' if failures == 0 else '⚠️  issues found'}")
        _print()


def cmd_checkpoint(args):
    """Checkpoint management commands."""
    subcmd = getattr(args, "checkpoint_subcmd", None)
    agent_id = getattr(args, "agent_id", None)

    try:
        from correctover.checkpoint import (
            Checkpoint, FileCheckpointStore, MemoryCheckpointStore,
        )
    except Exception as e:
        print(f"  ❌ Checkpoint module not available: {e}\n")
        return

    store = FileCheckpointStore()

    if subcmd == "list":
        agents = store.list_agents()
        print("\n  Correctover — Checkpointed Agents")
        print("  " + "─" * 55)
        if not agents:
            print("  (no agents with checkpoints)")
        for aid in agents:
            cp = Checkpoint(aid, store=store)
            st = cp.status()
            completed = st["steps_completed"]
            total = st["steps_total"]
            cost = st["total_cost_usd"]
            tokens = st["total_tokens_used"]
            print(f"  📦 {aid:30s}  {completed}/{total} steps  ${cost:.4f}  {tokens:,} tokens")
        print()

    elif subcmd == "status":
        if not agent_id:
            print("\n  ❌ Usage: nb-doctor checkpoint status <agent_id>\n")
            return
        cp = Checkpoint(agent_id, store=store)
        st = cp.status()
        resume = cp.resume_info()

        print(f"\n  Correctover — Checkpoint Status: {agent_id}")
        print(f"  {'─' * 50}")
        print(f"  Run ID:          {st['run_id']}")
        print(f"  Steps completed: {st['steps_completed']}")
        print(f"  Steps total:     {st['steps_total']}")
        print(f"  Skipped (resume):{st['steps_skipped_this_run']}")
        print(f"  Tokens used:     {st['total_tokens_used']:,}")
        print(f"  Cost:            ${st['total_cost_usd']:.4f}")

        if resume:
            print(f"\n  🔄 Resume: {resume.get('message', 'N/A')}")

        if st["steps"]:
            print(f"\n  Steps:")
            for name, info in st["steps"].items():
                icon = "✅" if info["completed"] else "⏳"
                ts = ""
                if info.get("completed_at"):
                    import time as _t
                    ts = f"  ({_t.strftime('%H:%M:%S', _t.localtime(info['completed_at']))})"
                print(f"  {icon} {name:20s} {info['tokens_used']:>6,} tokens  ${info['cost_usd']:.4f}{ts}")
        print()

    elif subcmd == "reset":
        if not agent_id:
            print("\n  ❌ Usage: nb-doctor checkpoint reset <agent_id>\n")
            return
        cp = Checkpoint(agent_id, store=store)
        if cp.reset():
            print(f"\n  ✅ Checkpoints cleared for '{agent_id}'\n")
        else:
            print(f"\n  ℹ️  No checkpoints found for '{agent_id}'\n")

    else:
        print("\n  Usage: nb-doctor checkpoint <list|status|reset>\n")


def main():
    parser = argparse.ArgumentParser(
        prog="nb-doctor",
        description="Correctover — Self-healing engine for LLM API calls",
    )
    sub = parser.add_subparsers(dest="command")

    scan_parser = sub.add_parser("scan", help="Scan environment for API keys + generate fix scripts")
    scan_parser.add_argument("--fix", action="store_true", help="Generate fix script for detected issues")
    scan_parser.add_argument("--json", dest="json_output", action="store_true", help="Output JSON")
    run_parser = sub.add_parser("run", help="Start engine and run interactive test")
    run_parser.add_argument("--quick", action="store_true", help="Quick single-test mode")

    sub.add_parser("version", help="Show version")
    sub.add_parser("status", help="License status & plan info")
    sub.add_parser("upgrade", help="Upgrade to Pro")

    auth_parser = sub.add_parser("auth", help="Activate license key")
    auth_parser.add_argument("key", nargs="?", help="License key (e.g. NB-PRO-xxxxx)")

    # Provider management
    provider_parser = sub.add_parser("provider", help="Provider management")
    provider_parser.add_argument("provider_subcmd", nargs="?", choices=["list", "status"], help="list or status")

    # Route test
    route_parser = sub.add_parser("route", help="Test routing for a prompt")
    route_parser.add_argument("prompt", nargs="?", help="Prompt to route")
    route_parser.add_argument("--strategy", "-s", default="cost", choices=["cost", "latency", "quality"], help="Routing strategy")

    # Setup (BYOK)
    setup_parser = sub.add_parser("setup", help="BYOK: configure your own API key")
    setup_parser.add_argument("--provider", "-p", required=True, help="Provider name (deepseek/agnes/openai/anthropic)")
    setup_parser.add_argument("--key", "-k", required=True, help="Your API key")

    # Checkpoint management
    cp_parser = sub.add_parser("checkpoint", help="Agent checkpoint management")
    cp_parser.add_argument("checkpoint_subcmd", nargs="?", choices=["list", "status", "reset"], help="list, status, or reset")
    cp_parser.add_argument("agent_id", nargs="?", help="Agent ID for status/reset")

    # Diagnose
    diag_parser = sub.add_parser("diagnose", help="Deep diagnostic — module health, providers, license, flywheel")
    diag_parser.add_argument("--json", action="store_true", help="Output JSON")
    diag_parser.add_argument("--fix", action="store_true", help="Generate fix script after diagnosis")


    args = parser.parse_args()

    commands = {
        "scan": cmd_scan,
        "run": cmd_run,
        "version": cmd_version,
        "status": cmd_status,
        "upgrade": cmd_upgrade,
        "auth": cmd_auth,
        "setup": cmd_setup,
        "provider": cmd_provider,
        "route": cmd_route,
        "checkpoint": cmd_checkpoint,
        "diagnose": cmd_diagnose,
    }

    if args.command in commands:
        commands[args.command](args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
