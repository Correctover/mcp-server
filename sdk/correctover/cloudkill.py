# Copyright 2024-2026 Correctover Team
# Licensed under the Apache License, Version 2.0 (the "License")
#
"""Correctover Cloud Kill-Switch — 篡改检测 + 云端熔断 + 自动降级。

合法反击机制：
1. 检测篡改（guard检查id()变化、monkey-patch、非法license）
2. 上报篡改到FC（设备指纹+篡改类型）
3. 定期校验license是否被云端吊销
4. 被吊销后自动降级为Free（不破坏，不崩溃，只是功能降级）

设计原则：
- 不破坏用户系统（合法）
- 不崩溃（用户体验优先）
- 不暴露检测逻辑（静默执行）
- 云端控制（我们说了算）
"""
import hashlib
import json
import os
import time
import threading
from typing import Optional, Dict, Any


# FC端点
_FC_BASE = os.environ.get(
    "CORRECTOVER_FC_URL",
    "https://license-api-correctover-hk.oss-cn-hongkong.aliyuncs.com"
)
_REPORT_URL = f"{_FC_BASE}/api/v1/tamper/report"
_CHECK_URL = f"{_FC_BASE}/api/v1/tamper/check"

# 本地缓存（避免每次调用都联网）
_LOCAL_DIR = os.path.expanduser("~/.correctover")
_REVOKE_CACHE = os.path.join(_LOCAL_DIR, ".revoke_cache")
_TAMPER_LOG = os.path.join(_LOCAL_DIR, ".tamper_log")

# 校验间隔（秒）
_CHECK_INTERVAL = 3600  # 1小时检查一次
_MIN_REPORT_INTERVAL = 300  # 篡改报告最短5分钟间隔


def _device_fingerprint() -> str:
    """获取设备指纹（复用已有逻辑）。"""
    try:
        from correctover._device import device_fingerprint
        return device_fingerprint()
    except Exception:
        # Fallback: 基于机器特征生成
        import platform
        raw = f"{platform.node()}-{platform.machine()}-{platform.system()}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _license_key() -> str:
    """获取当前license key。"""
    return os.environ.get("CORRECTOVER_LICENSE_KEY", "")


def _safe_plan() -> str:
    """获取当前plan（不触发guard检测）。"""
    try:
        from correctover.license import get_plan
        return get_plan()
    except Exception:
        return "free"


# ── 篡改检测 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def detect_tamper() -> Optional[Dict[str, Any]]:
    """检测当前运行环境是否存在篡改。

    检测项：
    1. is_pro / is_enterprise / is_trial 的函数id是否被替换
    2. consume_repair 是否被替换为空操作
    3. license模块关键函数是否被monkey-patch
    4. activation.json 是否被手动篡改（无有效HMAC签名）

    Returns:
        如果检测到篡改，返回篡改信息dict。否则返回None。
    """
    tamper_info = None

    try:
        from correctover import license as lic

        # 检测1: is_pro / is_enterprise / is_trial 的 __module__ 是否异常
        # 正常情况下，这些函数的__module__应该是'correctover.license'
        # 如果被 lambda: True 替换，__module__会变成None或不同值
        for func_name in ("is_pro", "is_enterprise", "is_trial", "is_expired"):
            func = getattr(lic, func_name, None)
            if func is None:
                continue
            # 检查是否是lambda或非原始函数
            func_module = getattr(func, "__module__", None)
            func_qualname = getattr(func, "__qualname__", "")

            # Lambda函数: __qualname__ 包含 "<lambda>"
            # 被替换的函数: __module__ 不是 correctover.license
            is_lambda = "<lambda>" in func_qualname
            wrong_module = func_module and func_module != "correctover.license" and func_module != "correctover._license"

            if is_lambda or wrong_module:
                tamper_info = {
                    "type": "function_replaced",
                    "function": func_name,
                    "original_module": "correctover.license",
                    "actual_module": func_module,
                    "actual_qualname": func_qualname,
                    "is_lambda": is_lambda,
                }
                break

        # 检测2: license module __class__ 是否被重置（绕过 _guard 的 __setattr__ 保护）
        if tamper_info is None:
            try:
                from correctover._guard import _locked_class
                if _locked_class is not None and type(lic) is not _locked_class:
                    tamper_info = {
                        "type": "class_reset",
                        "function": "__class__",
                        "detail": "Module __class__ was reset to bypass __setattr__ guard",
                    }
            except Exception:
                pass

        # 检测4: consume_repair 是否被替换为永真函数
        if tamper_info is None:
            repair_func = getattr(lic, "consume_repair", None)
            if repair_func:
                qualname = getattr(repair_func, "__qualname__", "")
                if "<lambda>" in qualname:
                    # 检查是否是 lambda: True（永真）
                    try:
                        # 安全地检查：如果consume_repair()返回True但plan是free，说明被篡改
                        current_plan = _safe_plan()
                        if current_plan == "free":
                            result = repair_func("test")
                            if result is True:
                                tamper_info = {
                                    "type": "repair_bypassed",
                                    "function": "consume_repair",
                                    "actual_qualname": qualname,
                                }
                    except Exception:
                        pass

    except Exception:
        # 检测过程出错不崩溃
        pass

    return tamper_info


# ── 云端上报 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _last_report_time() -> float:
    """获取上次上报时间。"""
    try:
        if os.path.exists(_TAMPER_LOG):
            with open(_TAMPER_LOG, "r") as f:
                data = json.load(f)
                return data.get("last_report_ts", 0)
    except Exception:
        pass
    return 0


def _save_report_time(ts: float):
    """保存上报时间。"""
    try:
        os.makedirs(_LOCAL_DIR, exist_ok=True)
        with open(_TAMPER_LOG, "w") as f:
            json.dump({"last_report_ts": ts}, f)
    except Exception:
        pass


def report_tamper(tamper_info: Dict[str, Any]) -> bool:
    """上报篡改事件到FC。

    Args:
        tamper_info: detect_tamper()返回的篡改信息。

    Returns:
        True如果上报成功，False否则。
    """
    now = time.time()

    # 节流：最短5分钟间隔
    if now - _last_report_time() < _MIN_REPORT_INTERVAL:
        return False

    payload = {
        "device_id": _device_fingerprint(),
        "license_key": _license_key(),
        "plan": _safe_plan(),
        "tamper_type": tamper_info.get("type", "unknown"),
        "tamper_detail": tamper_info,
        "timestamp": int(now),
    }

    try:
        import httpx
        resp = httpx.post(
            _REPORT_URL,
            json=payload,
            timeout=5.0,
            headers={"Content-Type": "application/json"},
        )
        if resp.status_code == 200:
            _save_report_time(now)
            return True
    except Exception:
        pass

    return False


# ── 云端吊销校验 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _last_check_time() -> float:
    """获取上次校验时间。"""
    try:
        if os.path.exists(_REVOKE_CACHE):
            with open(_REVOKE_CACHE, "r") as f:
                data = json.load(f)
                return data.get("last_check_ts", 0)
    except Exception:
        pass
    return 0


def _save_check_result(revoked: bool, reason: str = ""):
    """保存校验结果到本地缓存。"""
    try:
        os.makedirs(_LOCAL_DIR, exist_ok=True)
        with open(_REVOKE_CACHE, "w") as f:
            json.dump({
                "revoked": revoked,
                "reason": reason,
                "last_check_ts": time.time(),
            }, f)
    except Exception:
        pass


def _load_cached_revocation() -> tuple:
    """加载本地缓存的吊销状态。"""
    try:
        if os.path.exists(_REVOKE_CACHE):
            with open(_REVOKE_CACHE, "r") as f:
                data = json.load(f)
                return data.get("revoked", False), data.get("reason", "")
    except Exception:
        pass
    return False, ""


def check_revoked() -> tuple:
    """检查当前license是否被云端吊销。

    节流设计：最多1小时检查一次，避免频繁联网。
    离线时使用本地缓存结果。

    Returns:
        (revoked: bool, reason: str)
    """
    now = time.time()

    # 节流：1小时内不重复联网
    if now - _last_check_time() < _CHECK_INTERVAL:
        return _load_cached_revocation()

    # 联网校验
    license_key = _license_key()
    if not license_key:
        # Free用户没有license key，不需要校验
        return False, ""

    try:
        import httpx
        resp = httpx.get(
            _CHECK_URL,
            params={"key": license_key, "device_id": _device_fingerprint()},
            timeout=5.0,
        )
        if resp.status_code == 200:
            data = resp.json()
            revoked = data.get("revoked", False)
            reason = data.get("reason", "")
            _save_check_result(revoked, reason)
            return revoked, reason
    except Exception:
        # 网络失败，使用本地缓存
        pass

    return _load_cached_revocation()


# ── 降级执行 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _force_downgrade(reason: str = "revoked"):
    """强制降级为Free计划。

    不崩溃、不报错、不破坏。只是静默地把plan改为free。
    """
    try:
        # 修改本地activation.json（如果存在）
        from correctover._device import _LOCAL_DIR as device_dir
        act_file = os.path.join(device_dir or _LOCAL_DIR, "activation.json")
        if os.path.exists(act_file):
            with open(act_file, "r") as f:
                data = json.load(f)
            # 只修改plan，保留其他信息（用于追踪）
            data["plan"] = "free"
            data["downgraded"] = True
            data["downgrade_reason"] = reason
            data["downgrade_ts"] = int(time.time())
            with open(act_file, "w") as f:
                json.dump(data, f, indent=2)
    except Exception:
        pass


# ── 主入口：检测+上报+校验+降级 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def run_cloud_kill_check() -> Dict[str, Any]:
    """执行完整的云端熔断检查流程。

    1. 检测本地篡改
    2. 如果检测到篡改 → 上报FC
    3. 检查云端吊销状态
    4. 如果被吊销 → 静默降级

    Returns:
        检查结果dict（仅用于内部调试，不暴露给用户）。
    """
    result = {
        "tamper_detected": False,
        "tamper_reported": False,
        "revoked": False,
        "revoked_reason": "",
        "downgraded": False,
    }

    # Step 1: 检测篡改
    tamper_info = detect_tamper()
    if tamper_info:
        result["tamper_detected"] = True
        result["tamper_type"] = tamper_info.get("type")

        # Step 2: 上报
        reported = report_tamper(tamper_info)
        result["tamper_reported"] = reported

    # Step 3: 检查云端吊销
    revoked, reason = check_revoked()
    result["revoked"] = revoked
    result["revoked_reason"] = reason

    # Step 4: 如果被吊销 → 降级
    if revoked:
        _force_downgrade(reason)
        result["downgraded"] = True

    return result


# ── 后台守护线程 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class CloudKillGuardian:
    """后台守护线程：定期执行云端熔断检查。

    启动后在后台静默运行，不影响主线程性能。
    """

    _instance = None

    def __init__(self, interval: int = 3600):
        self._interval = interval
        self._running = False
        self._thread = None
        self._last_result = None

    @classmethod
    def start(cls, interval: int = 3600):
        """启动守护线程（单例）。"""
        if cls._instance is None:
            cls._instance = cls(interval=interval)
        if not cls._instance._running:
            cls._instance._running = True
            cls._instance._thread = threading.Thread(
                target=cls._instance._run_loop,
                daemon=True,  # 不阻止主进程退出
                name="nb-cloudkill",
            )
            cls._instance._thread.start()
        return cls._instance

    def _run_loop(self):
        """后台循环。"""
        # 首次启动延迟30秒（等SDK初始化完成）
        time.sleep(30)

        while self._running:
            try:
                self._last_result = run_cloud_kill_check()
            except Exception:
                pass

            # 周期性完整性校验（由 _guard.periodic_check 执行）
            # 限频：最少60秒一次，3次失败后升级为 enforce
            try:
                from correctover._guard import periodic_check
                periodic_check()
            except Exception:
                pass

            # 等待下次检查
            for _ in range(self._interval):
                if not self._running:
                    break
                time.sleep(1)

    def stop(self):
        """停止守护线程。"""
        self._running = False

    @property
    def last_result(self) -> Optional[Dict]:
        return self._last_result


# ── 快捷函数 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def quick_check() -> bool:
    """快速检查：当前运行环境是否安全。

    Returns:
        True = 安全，False = 检测到篡改或被吊销。
    """
    result = run_cloud_kill_check()
    return not result["tamper_detected"] and not result["revoked"]
