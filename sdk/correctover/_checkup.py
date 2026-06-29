# Copyright 2024-2026 Correctover Team
# Licensed under the Apache License, Version 2.0 (the "License")
# Correctover™ — Proprietary MAPE-K Adaptive Loop Architecture

#
"""Correctover First-Run Checkup — 让0调用变成"第一次装就看到价值".

核心逻辑:
  325下载 0调用 → 因为装了没动
  体检让用户装完立刻看到: 你有几个key、有没有backup、在不在裸奔

设计原则:
  - 只跑一次: ~/.correctover/checkup_done 标记 (版本升级重跑)
  - 极速: 并行检测, <3秒完成
  - 非阻塞: 失败静默, 绝不卡住 import
  - 制造焦虑: "1个provider, 没backup = 裸奔"
  - CI/CD 静默: 检测 CI 环境变量, 不输出体检结果

触发时机:
  import correctover → __init__.py 调用 _checkup.run()
  只在首次安装或版本升级时跑一次

Output example:
  ✅ Correctover v4.4.2 installed
  🔍 Quick health check...
     ✅ OpenAI: key valid (234ms)
     🔑 DeepSeek: key detected (skipped connectivity test)
     ⚠️  No backup provider — one failure = total outage
     💡 Add a 2nd provider for auto-failover → correctover.cn/docs
  ℹ️  Plan: Free (diagnosis free, repair paid)
     💡 Pro: ¥699/年 | 全功能自愈 | 一key一机
     📧 wangguigui@correctover.cn
"""

import json
import os
import sys
import time
import threading

_LOCAL_DIR = os.path.join(os.path.expanduser("~"), ".correctover")
_CHECKUP_FLAG = os.path.join(_LOCAL_DIR, "checkup_done")

# ── Provider key detection map ────────────────────────────────────

_PROVIDER_KEYS = {
    "openai": {
        "env": ["OPENAI_API_KEY"],
        "test_url": "https://api.openai.com/v1/models",
        "test_header": "bearer",   # Bearer token auth
        "label": "OpenAI",
    },
    "anthropic": {
        "env": ["ANTHROPIC_API_KEY"],
        "test_url": None,  # No simple validation endpoint
        "test_header": None,
        "label": "Anthropic",
    },
    "deepseek": {
        "env": ["DEEPSEEK_API_KEY"],
        "test_url": "https://api.deepseek.com/models",
        "test_header": "bearer",
        "label": "DeepSeek",
    },
    "google": {
        "env": ["GOOGLE_API_KEY", "GEMINI_API_KEY"],
        "test_url": None,  # Gemini uses query param auth
        "test_header": None,
        "label": "Google/Gemini",
    },
    "mistral": {
        "env": ["MISTRAL_API_KEY"],
        "test_url": "https://api.mistral.ai/v1/models",
        "test_header": "bearer",
        "label": "Mistral",
    },
    "qwen": {
        "env": ["DASHSCOPE_API_KEY", "ALIBABA_CLOUD_ACCESS_KEY"],
        "test_url": None,  # DashScope uses different auth
        "test_header": None,
        "label": "Qwen/通义",
    },
    "zhipu": {
        "env": ["ZHIPU_API_KEY"],
        "test_url": None,
        "test_header": None,
        "label": "GLM/智谱",
    },
    "moonshot": {
        "env": ["MOONSHOT_API_KEY"],
        "test_url": "https://api.moonshot.cn/v1/models",
        "test_header": "bearer",
        "label": "Moonshot/月之暗面",
    },
}

# ── CI environment detection ──────────────────────────────────────

_CI_ENV_VARS = [
    "CI", "JENKINS_URL", "GITHUB_ACTIONS", "GITLAB_CI",
    "TRAVIS", "CIRCLECI", "BUILDKITE", "TF_BUILD",
    "PYTEST_CURRENT_TEST", "__PYTEST_PLAT",  # pytest
]


# ── Public API ────────────────────────────────────────────────────

def run():
    """首次运行自动体检。只跑一次, CI环境静默。"""
    # CI/CD 环境不输出体检
    if _is_ci():
        _mark_done()
        return

    # 已跑过且版本没变
    if _already_done():
        return

    try:
        _do_checkup()
        _mark_done()
    except Exception:
        pass  # 绝不卡住 import


def force_run():
    """强制重新跑体检 (用于 CLI 或测试)."""
    try:
        if os.path.exists(_CHECKUP_FLAG):
            os.remove(_CHECKUP_FLAG)
    except Exception:
        pass
    _do_checkup()


# ── Internal ─────────────────────────────────────────────────────

def _is_ci():
    """检测是否在 CI/CD 环境运行."""
    for var in _CI_ENV_VARS:
        if os.environ.get(var, "").strip():
            return True
    # 用户主动关闭
    if os.environ.get("CORRECTOVER_NO_CHECKUP", "").strip().lower() in ("1", "true", "yes"):
        return True
    return False


def _already_done():
    """检查是否已体检过, 版本升级则重跑."""
    try:
        if not os.path.exists(_CHECKUP_FLAG):
            return False
        with open(_CHECKUP_FLAG) as f:
            data = json.load(f)
        return data.get("version") == _sdk_version()
    except Exception:
        return False


def _mark_done():
    """标记体检已完成."""
    try:
        os.makedirs(_LOCAL_DIR, exist_ok=True)
        with open(_CHECKUP_FLAG, "w") as f:
            json.dump({"version": _sdk_version(), "ts": int(time.time())}, f)
    except Exception:
        pass


def _sdk_version():
    """安全获取 SDK 版本."""
    try:
        from correctover import __version__
        return __version__
    except Exception:
        return "unknown"


def _detect_keys():
    """扫描环境变量, 检测已配置的 API keys."""
    detected = []
    for name, cfg in _PROVIDER_KEYS.items():
        for env_var in cfg["env"]:
            key = os.environ.get(env_var, "").strip()
            if key:
                detected.append({
                    "name": name,
                    "env_var": env_var,
                    "key_masked": key[:6] + "..." + key[-4:] if len(key) > 12 else key[:4] + "...",
                    "label": cfg["label"],
                    "test_url": cfg.get("test_url"),
                    "test_header": cfg.get("test_header"),
                    "full_key": key,
                })
                break
    return detected


def _test_provider(prov, results):
    """测试单个 provider 连通性 (在线校验 key)."""
    name = prov["name"]
    url = prov.get("test_url")
    header_type = prov.get("test_header")
    key = prov.get("full_key", "")

    # 没有 test_url 的 provider, 只标记 detected
    if not url or not header_type:
        results[name] = {"status": "detected"}
        return

    try:
        import httpx

        if header_type == "bearer":
            headers = {"Authorization": f"Bearer {key}"}
        else:
            headers = {}

        start = time.time()
        resp = httpx.get(url, headers=headers, timeout=3.0)
        latency_ms = (time.time() - start) * 1000

        if resp.status_code == 200:
            results[name] = {"status": "valid", "latency_ms": latency_ms}
        elif resp.status_code == 401:
            results[name] = {"status": "invalid", "latency_ms": latency_ms}
        elif resp.status_code == 403:
            results[name] = {"status": "invalid", "latency_ms": latency_ms}
        elif resp.status_code == 429:
            # Rate limited but key IS valid
            results[name] = {"status": "valid", "latency_ms": latency_ms}
        else:
            # Other status — might be valid, just unusual
            results[name] = {"status": "valid", "latency_ms": latency_ms}
    except Exception:
        # Timeout, connection error, etc. — key might be valid, just unreachable
        results[name] = {"status": "unreachable"}


def _do_checkup():
    """执行体检并输出结果."""
    version = _sdk_version()

    print()
    print(f"  ✅ Correctover v{version} installed")
    print(f"  🔍 Quick health check...")

    # 1. 检测 API keys
    detected = _detect_keys()

    # 2. 并行测试连通性
    results = {}
    if detected:
        threads = []
        for prov in detected:
            t = threading.Thread(
                target=_test_provider, args=(prov, results), daemon=True
            )
            t.start()
            threads.append(t)

        for t in threads:
            t.join(timeout=4.0)

    # 3. 输出每个 provider 的状态
    if not detected:
        print(f"     ⚠️  No API keys configured")
        print(f"     💡 export OPENAI_API_KEY=sk-... → then import correctover")
    else:
        for prov in detected:
            r = results.get(prov["name"], {})
            status = r.get("status", "unknown")
            latency = r.get("latency_ms")

            if status == "valid":
                lat_str = f" ({latency:.0f}ms)" if latency else ""
                print(f"     ✅ {prov['label']}: key valid{lat_str}")
            elif status == "invalid":
                print(f"     ❌ {prov['label']}: key invalid (check {prov['env_var']})")
            elif status == "detected":
                print(f"     🔑 {prov['label']}: key found ({prov['key_masked']})")
            elif status == "unreachable":
                print(f"     🌐 {prov['label']}: key found, but endpoint unreachable")
            else:
                print(f"     ❓ {prov['label']}: {status}")

    # 4. 风险评估 — 裸奔检测
    provider_count = len(detected)
    valid_count = sum(
        1 for r in results.values()
        if r.get("status") in ("valid", "detected", "unreachable")
    )
    invalid_count = sum(
        1 for r in results.values()
        if r.get("status") == "invalid"
    )

    print()
    if provider_count == 0:
        print(f"     ⚠️  No API keys → Correctover needs at least one provider")
        print(f"     💡 export OPENAI_API_KEY=sk-... → https://correctover.cn/docs")
    elif provider_count == 1:
        print(f"     ⚠️  Only 1 provider — one failure = total outage (裸奔!)")
        print(f"     💡 Add a 2nd provider → auto-failover protection")
    elif invalid_count > 0:
        print(f"     ⚠️  {invalid_count} invalid key(s) → fix or remove them")
    elif valid_count >= 2:
        print(f"     ✅ {valid_count} providers ready → multi-provider failover armed")

    # 5. Plan 状态
    try:
        from correctover.license import get_plan, days_remaining, is_pro
        plan = get_plan()
        if plan == "free":
            print()
            print(f"     ℹ️  Plan: Free — 检测免费·修复付费")
            print(f"     💡 Pro: ¥699/年 | 全功能自愈 | 一key一机")
            print(f"     📧 Contact: wangguigui@correctover.cn")
        else:
            days = days_remaining()
            label = "永久" if days >= 99999 else f"{days}天"
            print(f"     🔑 Plan: {plan} | {label} remaining")
    except Exception:
        pass

    # 6. Next step
    print()
    if provider_count == 0:
        print(f"     📖 Setup guide → correctover.cn/docs")
    elif provider_count == 1:
        print(f"     📖 Multi-provider setup → correctover.cn/docs")
    else:
        print(f"     📖 Full docs → correctover.cn/docs")
    print()
