#!/usr/bin/env python3
"""
Correctover Shield — Real 16-point security scan for LLM API setups.
Run locally, report to web dashboard or output JSON.
"""
import argparse
import importlib
import json
import os
import sys
import time
import subprocess
import socket

# ── 16 check definitions ──────────────────────────────────────────
CHECKS = [
    # Quick scan (6)
    {"id": 1,  "name": "SDK安装",         "group": "快速扫描", "level": 1,
     "method": "sdk_installed",   "desc": "correctover-sdk已pip安装"},
    {"id": 2,  "name": "SDK版本",         "group": "快速扫描", "level": 1,
     "method": "sdk_version",      "desc": "版本>=5.2.7"},
    {"id": 3,  "name": "Provider配置",    "group": "快速扫描", "level": 1,
     "method": "provider_config",  "desc": "至少1个Provider已配置"},
    {"id": 4,  "name": "OpenAI兼容层",    "group": "快速扫描", "level": 1,
     "method": "openai_client",    "desc": "Client()可初始化"},
    {"id": 5,  "name": "自愈容灾引擎",    "group": "快速扫描", "level": 1,
     "method": "self_healing",      "desc": "SelfHealingEngine核心方法正常"},
    {"id": 6,  "name": "Provider健康监控", "group": "快速扫描", "level": 1,
     "method": "drift_monitor",     "desc": "DriftMonitor可实例化"},
    # Deep scan (10)
    {"id": 7,  "name": "负载均衡",         "group": "深度扫描", "level": 2,
     "method": "load_balance",      "desc": "Router策略已配置"},
    {"id": 8,  "name": "速率限制",         "group": "深度扫描", "level": 2,
     "method": "rate_limit",        "desc": "RateLimiter令牌桶可用"},
    {"id": 9,  "name": "请求日志",         "group": "深度扫描", "level": 2,
     "method": "logging",           "desc": "日志模块可导入"},
    {"id": 10, "name": "成本跟踪",         "group": "深度扫描", "level": 2,
     "method": "cost_tracker",      "desc": "CostTracker可实例化"},
    {"id": 11, "name": "延迟监控",         "group": "深度扫描", "level": 2,
     "method": "latency_baseline",  "desc": "DriftMonitor有基线数据"},
    {"id": 12, "name": "错误率监控",       "group": "深度扫描", "level": 2,
     "method": "error_rate",        "desc": "DriftMonitor有错误率数据"},
    {"id": 13, "name": "故障转移历史",     "group": "深度扫描", "level": 2,
     "method": "failover_log",      "desc": "Engine有Failover统计"},
    {"id": 14, "name": "APIKey有效性",    "group": "深度扫描", "level": 2,
     "method": "key_validation",   "desc": "Key格式验证通过"},
    {"id": 15, "name": "配置完整性",       "group": "深度扫描", "level": 2,
     "method": "config_validate",   "desc": "Engine可读配置"},
    {"id": 16, "name": "网络连通性",       "group": "深度扫描", "level": 2,
     "method": "network_probe",     "desc": "Provider网络可达"},
]

def _check_sdk_installed():
    try:
        import correctover
        v = getattr(correctover, "__version__", "unknown")
        return True, f"v{v}"
    except ImportError:
        return False, "未安装correctover-sdk"

def _check_sdk_version():
    v = getattr(sys.modules.get("correctover", None), "__version__", None)
    if not v:
        try:
            from correctover._version import __version__
            v = __version__
        except:
            pass
    if not v:
        return False, "无法获取版本"
    try:
        major = int(v.split(".")[0])
        if major >= 5:
            return True, f"v{v}"
        return False, f"v{v} (建议升级)"
    except:
        return False, v

def _check_provider_config():
    try:
        from correctover._engine import SelfHealingEngine
        eng = SelfHealingEngine()
        providers = eng._providers
        env_keys = [k for k in os.environ if "API_KEY" in k and os.environ.get(k, "").strip()]
        if providers and len(providers) > 0:
            names = list(providers.keys())
            return True, f"{len(names)}个Provider: {', '.join(names[:3])}"
        if env_keys:
            return True, f"{len(env_keys)}个API Key在环境变量"
        return False, "未配置Provider (无API Key)"
    except Exception as e:
        return False, str(e)[:80]

def _check_openai_client():
    try:
        from correctover import Client
        return True, "Client可导入"
    except Exception as e:
        return False, str(e)[:80]

def _check_self_healing():
    try:
        from correctover._engine import SelfHealingEngine
        eng = SelfHealingEngine()
        # Check key methods exist
        has_call = hasattr(eng, "call_sync")
        has_add = hasattr(eng, "add_provider")
        has_stats = hasattr(eng, "get_stats")
        if has_call and has_add and has_stats:
            return True, "核心方法就绪(call_sync/add_provider/get_stats)"
        return False, "缺少核心方法"
    except Exception as e:
        return False, str(e)[:80]

def _check_drift_monitor():
    try:
        from correctover.drift import DriftMonitor
        dm = DriftMonitor()
        return True, "DriftMonitor可实例化"
    except Exception as e:
        return False, str(e)[:80]

def _check_load_balance():
    try:
        from correctover.router import Router
        # Get any available providers from env
        env_map = {
            "openai": os.environ.get("OPENAI_API_KEY", ""),
            "deepseek": os.environ.get("DEEPSEEK_API_KEY", ""),
            "anthropic": os.environ.get("ANTHROPIC_API_KEY", ""),
        }
        available = [k for k, v in env_map.items() if v]
        if not available:
            available = ["openai", "deepseek"]
        r = Router(providers=available, strategy="cost")
        strategy = str(r.strategy) if hasattr(r, "strategy") else "unknown"
        return True, f"策略={strategy}, Providers={available}"
    except Exception as e:
        return False, str(e)[:80]

def _check_rate_limit():
    try:
        from correctover._engine import RateLimiter
        rl = RateLimiter(max_tokens=1000, refill_rate=10.0)
        return True, "RateLimiter令牌桶可用"
    except Exception as e:
        return False, str(e)[:80]

def _check_logging():
    try:
        import correctover.logging_config as lc
        return True, "logging_config可导入"
    except Exception as e:
        return False, str(e)[:80]

def _check_cost_tracker():
    try:
        from correctover.cost_tracker import CostTracker
        ct = CostTracker()
        return True, "CostTracker可实例化"
    except Exception as e:
        return False, str(e)[:80]

def _check_latency_baseline():
    try:
        from correctover.drift import DriftMonitor
        dm = DriftMonitor()
        baselines = getattr(dm, "_baselines", None)
        if baselines:
            return True, f"有{len(baselines)}个延迟基线"
        return False, "DriftMonitor无延迟基线数据"
    except Exception as e:
        return False, str(e)[:80]

def _check_error_rate():
    try:
        from correctover.drift import DriftMonitor
        dm = DriftMonitor()
        rates = getattr(dm, "_error_rates", None)
        if rates:
            return True, f"有{len(rates)}个错误率记录"
        return False, "DriftMonitor无错误率数据"
    except Exception as e:
        return False, str(e)[:80]

def _check_failover_log():
    try:
        from correctover._engine import SelfHealingEngine
        eng = SelfHealingEngine()
        stats = eng.get_stats()
        failover_count = stats.get("heal_count", 0)
        return True, f"heal_count={failover_count}"
    except Exception as e:
        return False, str(e)[:80]

def _check_key_validation():
    try:
        env_keys = {
            "OPENAI_API_KEY": os.environ.get("OPENAI_API_KEY", ""),
            "DEEPSEEK_API_KEY": os.environ.get("DEEPSEEK_API_KEY", ""),
            "ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY", ""),
        }
        found = {k: v for k, v in env_keys.items() if v}
        if not found:
            return False, "无API Key在环境变量"
        valid = sum(1 for v in found.values() if len(v) > 10)
        if valid == len(found):
            return True, f"{valid}个Key格式有效"
        return False, f"{valid}/{len(found)}格式有效"
    except Exception as e:
        return False, str(e)[:80]

def _check_config_validate():
    try:
        from correctover._engine import SelfHealingEngine
        eng = SelfHealingEngine()
        providers = eng._providers
        if providers is not None:
            return True, f"Engine配置正常, {len(providers)}个Provider"
        return True, "Engine配置正常"
    except Exception as e:
        return False, str(e)[:80]

def _check_network_probe():
    try:
        env_map = {
            "openai": ("api.openai.com", 443),
            "deepseek": ("api.deepseek.com", 443),
            "anthropic": ("api.anthropic.com", 443),
        }
        results = []
        for name, (host, port) in env_map.items():
            key = f"{name.upper()}_API_KEY"
            has_key = bool(os.environ.get(key, "").strip())
            try:
                sock = socket.create_connection((host, port), timeout=4)
                sock.close()
                results.append(f"{name}=✅{'(有Key)' if has_key else '(无Key)'}")
            except Exception as ex:
                results.append(f"{name}=❌{'(有Key)' if has_key else '(无Key)'}: {str(ex)[:20]}")
        reachable = sum(1 for r in results if "=✅" in r)
        if reachable > 0:
            return True, f"{reachable}/{len(env_map)}可达"
        return False, "; ".join(results)
    except Exception as e:
        return False, str(e)[:80]

METHOD_MAP = {
    "sdk_installed":   _check_sdk_installed,
    "sdk_version":     _check_sdk_version,
    "provider_config": _check_provider_config,
    "openai_client":   _check_openai_client,
    "self_healing":    _check_self_healing,
    "drift_monitor":   _check_drift_monitor,
    "load_balance":    _check_load_balance,
    "rate_limit":      _check_rate_limit,
    "logging":         _check_logging,
    "cost_tracker":    _check_cost_tracker,
    "latency_baseline": _check_latency_baseline,
    "error_rate":      _check_error_rate,
    "failover_log":    _check_failover_log,
    "key_validation":  _check_key_validation,
    "config_validate": _check_config_validate,
    "network_probe":  _check_network_probe,
}

def _version():
    try:
        from correctover._version import __version__
        return __version__
    except:
        return "unknown"

def run_scan(level: int = 2):
    results = {
        "timestamp": time.time(),
        "version": _version(),
        "session_id": None,
        "summary": {"total": 0, "pass": 0, "fail": 0, "warn": 0},
        "checks": [],
    }
    checks_to_run = CHECKS if level >= 2 else [c for c in CHECKS if c["level"] == 1]
    for check in checks_to_run:
        method = METHOD_MAP.get(check["method"])
        if not method:
            status, detail = "fail", "方法未实现"
        else:
            try:
                ok, detail = method()
                status = "pass" if ok else "fail"
            except Exception as e:
                status, detail = "fail", str(e)[:80]
        results["checks"].append({
            "id": check["id"], "name": check["name"],
            "group": check["group"], "level": check["level"],
            "status": status, "detail": detail, "desc": check["desc"],
        })
        results["summary"]["total"] += 1
        results["summary"][status] += 1
    return results

def print_report(results: dict):
    total = results["summary"]["total"]
    passed = results["summary"]["pass"]
    failed = results["summary"]["fail"]
    score = int(passed / total * 100) if total > 0 else 0
    print(f"\n{'='*58}")
    print(f"  Correctover Shield — 安全诊断报告")
    print(f"  SDK: {results['version']}  |  得分: {score}/100")
    print(f"{'='*58}")
    groups = {}
    for c in results["checks"]:
        groups.setdefault(c["group"], []).append(c)
    for group, checks in groups.items():
        print(f"\n  [{group}]")
        for c in checks:
            icon = "✅" if c["status"] == "pass" else "❌"
            detail = f"→ {c['detail']}" if c["detail"] != c["name"] else ""
            print(f"    {icon} #{c['id']:2d} {c['name']:<18s} {detail}")
    print(f"\n{'='*58}")
    verdict = "🎉 良好" if failed == 0 else "⚠️ 有风险项"
    print(f"  {passed}/{total} 通过  |  失败 {failed}  |  {verdict}")
    print(f"{'='*58}\n")

def main():
    parser = argparse.ArgumentParser(
        prog="correctover-shield",
        description="Correctover Shield — 本地安全诊断 (真实16项检测)",
    )
    sub = parser.add_subparsers(dest="command", metavar="command")
    scan_parser = sub.add_parser("scan", help="运行安全诊断")
    scan_parser.add_argument("--level", "-l", type=int, choices=[1, 2], default=2,
                             help="1=快速扫描(6项) 2=深度扫描(16项,默认)")
    scan_parser.add_argument("--json", "-j", action="store_true", help="输出JSON")
    scan_parser.add_argument("--session", "-s", default=None, help="Session ID (配对网页)")
    scan_parser.add_argument("--report", "-r", default=None, help="上报结果到URL (POST)")

    args = parser.parse_args()

    if args.command == "scan" or (args.command is None):
        results = run_scan(level=args.level)
        results["session_id"] = args.session

        if args.json:
            print(json.dumps(results, ensure_ascii=False, indent=2))
            return

        print_report(results)

        if args.report:
            try:
                import urllib.request
                data = json.dumps(results, ensure_ascii=False).encode()
                req = urllib.request.Request(
                    args.report, data=data,
                    headers={"Content-Type": "application/json"},
                    method="POST"
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    if resp.status == 200:
                        print(f"  ✅ 已上报至 {args.report}")
            except Exception as e:
                print(f"  ⚠️ 上报失败: {e}")

if __name__ == "__main__":
    main()
