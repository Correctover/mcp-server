# Copyright 2024-2026 Correctover Team
# Licensed under the Apache License, Version 2.0 (the "License")
# Correctover™ — Proprietary MAPE-K Adaptive Loop Architecture

#
"""Correctover v4.4.2 — 验证码门控，到期自动停.

核心流程:
  1. 客户联系管理员 → 管理员生成验证码 → 邮件发送
  2. 客户在 SDK 输入验证码 → 激活绑定设备 → 开始使用
  3. 到期 → 自动停止修复功能（诊断仍免费）

Usage:
    # 用验证码激活（推荐）
    from correctover import run
    engine = run(license_key="NB-TRL3-aB3kX9mP")

    # 无验证码 → 免费版（仅诊断）
    from correctover import run
    engine = run()
"""
from ._engine import run as _engine_run, SelfHealingEngine, ProviderConfig
from .license import activate, verify, get_plan, is_pro, is_expired, plan_summary


def run(api_keys=None, verbose=True, license_key=None):
    """Create a SelfHealingEngine with license & device binding.

    Args:
        api_keys:     Dict of {provider_name: api_key}
        verbose:      Print diagnostic info
        license_key:  验证码 (如 "NB-TRL3-xxxx") 或 license key (如 "NB-PRO-xxxx")

    Returns:
        SelfHealingEngine instance (feature-gated by license tier)
    """
    if license_key:
        # 自动判断是验证码还是 license key
        from .license import _looks_like_code
        if _looks_like_code(license_key):
            info = activate(license_key)
        else:
            info = verify(license_key)

        if verbose:
            if info.valid:
                print(plan_summary())
            else:
                print(f"  ⚠️  License无效: {info.message}")
                print(f"  ⚠️  以 免费版 运行（仅诊断，修复需授权）")
                print(f"  📧  联系获取验证码: wangguigui@correctover.cn")
    else:
        if verbose:
            print(plan_summary())

    # Pro 用户自动体检 — 首次 run 时显示连通性
    if verbose:
        try:
            from ._checkup import _detect_keys, _test_provider, _PROVIDER_KEYS
            detected = _detect_keys()
            if detected and len(detected) >= 1:
                results = {}
                import threading
                threads = []
                for prov in detected:
                    if prov.get("test_url"):
                        t = threading.Thread(target=_test_provider, args=(prov, results), daemon=True)
                        t.start()
                        threads.append(t)
                for t in threads:
                    t.join(timeout=3.0)
                valid = sum(1 for r in results.values() if r.get("status") == "valid")
                total = len(detected)
                if valid > 0:
                    print(f"  🌐 {valid}/{total} provider(s) connectivity OK")
        except Exception:
            pass

    engine = _engine_run(api_keys=api_keys, verbose=verbose)

    # 自动采集包装 — 每次 call/call_sync 自动记录统计
    _wrap_engine_with_stats(engine)

    return engine


def _wrap_engine_with_stats(engine):
    """给引擎实例的 call/call_sync 加统计采集钩子.

    因为 _engine.so 是编译的，不会调 _stats.py，
    所以在外层包装，确保每次调用都被记录。
    """
    try:
        original_call = engine.call
        original_call_sync = engine.call_sync

        async def _wrapped_call(*args, **kwargs):
            result = await original_call(*args, **kwargs)
            _record_call_result(result)
            return result

        def _wrapped_call_sync(*args, **kwargs):
            result = original_call_sync(*args, **kwargs)
            _record_call_result(result)
            return result

        engine.call = _wrapped_call
        engine.call_sync = _wrapped_call_sync
    except Exception:
        pass


def _record_call_result(result):
    """记录一次引擎调用的统计."""
    try:
        # 写入 _stats 引擎
        from ._stats import record_call
        record_call(result)
    except Exception:
        pass

    # 写入本地计数器 — 心跳上报用
    try:
        from .license import _increment_local_counter
        _increment_local_counter("total_calls")
        if getattr(result, 'heal_level', '') or getattr(result, 'downgraded', False):
            _increment_local_counter("total_protections")
    except Exception:
        pass


class Run:
    """v1.x compat: Run class wraps the run() function."""
    @staticmethod
    def start(api_keys=None, verbose=True, license_key=None) -> SelfHealingEngine:
        return run(api_keys=api_keys, verbose=verbose, license_key=license_key)


__all__ = ["run", "Run", "SelfHealingEngine", "ProviderConfig"]
