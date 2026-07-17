# Copyright 2024-2026 Correctover Team
# Licensed under the Apache License, Version 2.0 (the "License")
# Correctover™ — Proprietary MAPE-K Adaptive Loop Architecture

#
"""Correctover License System v4.0 — 验证码门控，到期自动停.

核心流程:
  1. 客户联系管理员 → 管理员生成验证码 → 邮件发送
  2. 客户在 SDK 输入验证码 → 激活绑定设备 → 开始使用
  3. 到期 → 自动停止修复功能（诊断仍免费）

4档验证码:
  - trial3:   3天试用（测试用）
  - monthly:  30天月付
  - annual:   365天年付 (Pro ¥699/年)
  - lifetime: 永久买断

一key一机: 验证码激活后绑定设备指纹，同一验证码其他设备无法使用。
检测免费，修复付费: Free plan 只能看诊断，修复动作报 RepairLockedError。

Usage:
    from correctover.license import verify, activate, get_plan, consume_repair

    # 方式1: 用验证码激活（推荐）
    info = activate("NB-TRL3-aB3kX9mP")  # 自动激活+绑定设备

    # 方式2: 用已有 license key
    info = verify("NB-PRO-xxxxx")

    # 检查修复权限
    consume_repair("auto_retry")  # Free → RepairLockedError, Pro → True
"""
import base64
import hashlib
import hmac
import json
import os
import time
import threading
from dataclasses import dataclass
from typing import Optional, Dict


# ── HMAC Secret (compiled into .so in production) ────────────────
_HMAC_SECRET: bytes = b""

def _get_hmac_secret() -> bytes:
    """Get HMAC secret from env var or FC API. Never hardcoded in source."""
    global _HMAC_SECRET
    if _HMAC_SECRET:
        return _HMAC_SECRET
    env_val = os.environ.get("CORRECTOVER_HMAC_SECRET", "")
    if env_val:
        _HMAC_SECRET = env_val.encode("utf-8")
        return _HMAC_SECRET
    try:
        import httpx
        base = os.environ.get("CORRECTOVER_FC_URL", _API_BASE_FALLBACK)
        resp = httpx.get(f"{base.rsplit('/license', 1)[0]}/secrets/hmac", timeout=3)
        if resp.status_code == 200:
            _HMAC_SECRET = resp.json().get("secret", "").encode("utf-8")
            return _HMAC_SECRET
    except Exception:
        pass
    return _HMAC_SECRET

# ── Online verification endpoints (HK region, Let's Encrypt SSL) ─
_API_BASE = "https://api.correctover.cn/api/v1/license"
_API_BASE_FALLBACK = "https://license-api-correctover-hk.oss-cn-hongkong.aliyuncs.com/api/v1/license"
_VERIFY_URL = f"{_API_BASE}/verify"
_ACTIVATE_URL = f"{_API_BASE}/activate"
_VERIFY_URL_FALLBACK = f"{_API_BASE_FALLBACK}/verify"
_ACTIVATE_URL_FALLBACK = f"{_API_BASE_FALLBACK}/activate"
_ONLINE_TIMEOUT = 5

# ── Plan constants ───────────────────────────────────────────────
PLAN_FREE = "free"
PLAN_PRO = "pro"
PLAN_ENTERPRISE = "enterprise"

# v4.0 验证码 plan 名
PLAN_TRIAL = "trial"       # trial3 验证码激活后的 SDK plan
PLAN_MONTHLY = "monthly"
PLAN_LIFETIME = "lifetime"

# All plans that unlock repair capability
_PRO_PLANS = {PLAN_PRO, PLAN_ENTERPRISE, PLAN_TRIAL, PLAN_MONTHLY, PLAN_LIFETIME, "annual"}

# Key prefix → plan mapping (支持新旧格式 + Correctover CV- 格式)
_PREFIX_MAP = {
    # Correctover (CV-) 格式 — 新签发 Key
    "CV-TRL-": PLAN_TRIAL,
    "CV-PRO-": PLAN_PRO,
    "CV-ENT-": PLAN_ENTERPRISE,
    # Legacy NeuralBridge (NB-) 格式 — 向后兼容
    "NB-TRL3-": PLAN_TRIAL,     # v4.0 试用3天
    "NB-MON-": PLAN_MONTHLY,    # v4.0 月付
    "NB-ANN-": PLAN_PRO,        # v4.0 年付 (SDK 内部 = pro)
    "NB-LTM-": PLAN_LIFETIME,   # v4.0 永久
    "NB-PRO-": PLAN_PRO,        # v3.x 兼容
    "NB-ENT-": PLAN_ENTERPRISE, # v3.x 兼容
    "NB-TRL-": PLAN_TRIAL,      # v3.x 兼容
}

# Plan → default validity days
PLAN_DAYS = {
    PLAN_TRIAL: 3,
    PLAN_MONTHLY: 30,
    PLAN_PRO: 365,
    PLAN_ENTERPRISE: 365,
    PLAN_LIFETIME: 36500,
}

# Plan → display label
PLAN_LABELS: Dict[str, str] = {
    PLAN_FREE: "免费版",
    PLAN_TRIAL: "试用版(3天)",
    PLAN_MONTHLY: "月度版(30天)",
    PLAN_PRO: "Pro专业版",
    PLAN_ENTERPRISE: "Enterprise企业版",
    PLAN_LIFETIME: "永久授权",
}

# Plan → annual price (CNY)
PLAN_PRICES: Dict[str, int] = {
    PLAN_FREE: 0,
    PLAN_TRIAL: 0,
    PLAN_MONTHLY: 0,
    PLAN_PRO: 699,
    PLAN_ENTERPRISE: 2999,
    PLAN_LIFETIME: 0,
}

# Plan → max devices
PLAN_MAX_DEVICES: Dict[str, int] = {
    PLAN_FREE: 0,
    PLAN_TRIAL: 1,
    PLAN_MONTHLY: 1,
    PLAN_PRO: 1,
    PLAN_ENTERPRISE: 10,
    PLAN_LIFETIME: 1,
}

# Repair action costs — 标记哪些动作是"修复"类
REPAIR_ACTIONS = {
    "diagnosis":       False,  # 诊断 — 永远免费
    "auto_retry":      True,   # L1 重试 — 修复
    "model_fallback":  True,   # L2 降级切换 — 修复
    "failover":        True,   # L3 Failover — 修复
    "cache_hit":       False,  # 缓存命中 — 免费
}


# ── Data ─────────────────────────────────────────────────────────

@dataclass
class LicenseInfo:
    plan: str          # "free" | "pro" | "enterprise" | "trial" | "monthly" | "lifetime"
    valid: bool
    customer: str
    expires_at: int    # unix timestamp; 0 = lifetime; very large = lifetime
    message: str
    device_bound: bool = False


class LicenseError(Exception):
    """Raised when a Pro feature is used without a valid license."""
    pass


class DeviceMismatchError(LicenseError):
    """Raised when license is bound to a different device."""
    pass


class RepairLockedError(LicenseError):
    """Raised when repair is attempted on Free plan (diagnosis free, repair paid)."""
    pass


class LicenseExpiredError(LicenseError):
    """Raised when license has expired — auto-stop repair."""
    pass


# Global state
_lock = threading.Lock()
_current: Optional[LicenseInfo] = None


# ── Local counters — 心跳数据源 ────────────────────────────────

_LOCAL_DIR = os.path.join(os.path.expanduser("~"), ".correctover")
_COUNTERS_FILE = os.path.join(_LOCAL_DIR, "stats.json")

def _increment_local_counter(key: str, amount: int = 1):
    """写入本地计数器，心跳会读这个文件上报数据."""
    try:
        os.makedirs(_LOCAL_DIR, exist_ok=True)
        data = {}
        if os.path.exists(_COUNTERS_FILE):
            with open(_COUNTERS_FILE, "r") as f:
                data = json.load(f)
        data[key] = data.get(key, 0) + amount
        with open(_COUNTERS_FILE, "w") as f:
            json.dump(data, f)
    except Exception:
        pass

def _record_fault(fault_type: str, action: str):
    """记录最近一次故障 — 心跳带上故障分类."""
    try:
        os.makedirs(_LOCAL_DIR, exist_ok=True)
        data = {}
        if os.path.exists(_COUNTERS_FILE):
            with open(_COUNTERS_FILE, "r") as f:
                data = json.load(f)
        data["last_fault"] = fault_type
        data["last_fault_action"] = action
        data["last_fault_time"] = int(time.time())
        faults = data.get("fault_counts", {})
        faults[fault_type] = faults.get(fault_type, 0) + 1
        data["fault_counts"] = faults
        with open(_COUNTERS_FILE, "w") as f:
            json.dump(data, f)
    except Exception:
        pass


# ── Public API ───────────────────────────────────────────────────

def activate(code: str, *, online: bool = True) -> LicenseInfo:
    """用验证码激活 Correctover（推荐方式）.

    流程:
    1. 发送验证码 + 设备指纹到服务器
    2. 服务器验证码有效 → 绑定设备 → 返回 license key
    3. 本地缓存 license info + activation

    Args:
        code:  验证码, 如 "NB-TRL3-aB3kX9mP"
        online: 是否在线激活

    Returns:
        LicenseInfo
    """
    global _current

    if not code or not isinstance(code, str) or not code.strip():
        info = LicenseInfo(PLAN_FREE, False, "", 0, "No activation code provided")
        with _lock:
            _current = info
        return info

    code = code.strip()

    from correctover._device import device_fingerprint, device_info, save_activation

    device_id = device_fingerprint()
    dev_info = device_info()

    # 尝试在线激活
    activated = False
    license_key = None
    result = None

    for url in (_ACTIVATE_URL, _ACTIVATE_URL_FALLBACK):
        try:
            import httpx
            resp = httpx.post(
                url,
                json={
                    "code": code,
                    "device_id": device_id,
                    "device_info": dev_info,
                },
                timeout=_ONLINE_TIMEOUT,
            )
            if resp.status_code == 200:
                result = resp.json()
                if result.get("activated"):
                    license_key = result.get("key", code)
                    activated = True
                    break
                else:
                    # 激活失败
                    info = LicenseInfo(
                        PLAN_FREE, False, "", 0,
                        result.get("error", "Activation failed")
                    )
                    with _lock:
                        _current = info
                    return info
            elif resp.status_code == 410:
                # 验证码过期
                result = resp.json()
                info = LicenseInfo(
                    PLAN_FREE, False, "", 0,
                    result.get("error", "验证码已过期，请联系获取新验证码")
                )
                with _lock:
                    _current = info
                return info
            # Non-200 from primary → try fallback
            if url == _ACTIVATE_URL:
                result = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
                continue
        except Exception:
            if url == _ACTIVATE_URL:
                continue

    if activated and license_key:
        # 验证返回的 license key
        info = _verify_offline(license_key)
        if info.valid:
            info.device_bound = True
            # 保存本地激活缓存
            key_prefix = _get_key_prefix(license_key)
            save_activation(key_prefix, device_id, info.plan, info.expires_at, info.customer)
            # 同步心跳 — 激活成功立即通知后台
            try:
                from correctover._ping import ping_sync
                ping_sync({"event": "activate", "plan": info.plan})
            except Exception:
                pass
            with _lock:
                _current = info
            return info

    # 在线激活失败 — 检查本地缓存是否有效（可能是网络问题）
    key_prefix = _get_key_prefix(code)
    from correctover._device import check_local_activation, load_activation
    if check_local_activation(key_prefix):
        record = load_activation()
        if record:
            info = LicenseInfo(
                plan=record.get("plan", PLAN_FREE),
                valid=True,
                customer=record.get("customer", ""),
                expires_at=record.get("expires_at", 0),
                message="Offline activation (cached)",
                device_bound=True,
            )
            # 检查过期
            if info.expires_at > 0 and time.time() > info.expires_at:
                info.valid = False
                info.message = "License expired — 验证码已过期，请联系获取新验证码"
            with _lock:
                _current = info
            return info

    # 完全失败
    error_msg = result.get("error", "Activation failed") if result else "Network error during activation"
    info = LicenseInfo(PLAN_FREE, False, "", 0, error_msg)
    with _lock:
        _current = info
    return info


def verify(key: str, *, online: bool = True) -> LicenseInfo:
    """Verify a license key and check device binding.

    Args:
        key:    License key like "NB-PRO-xxxxx"
        online: If True, check server for revocation + device binding

    Returns:
        LicenseInfo with device_bound flag
    """
    global _current

    if not key or not isinstance(key, str) or not key.strip():
        info = LicenseInfo(PLAN_FREE, False, "", 0, "No license key provided")
        with _lock:
            _current = info
        return info

    key = key.strip()

    # Step 1: Offline verification
    info = _verify_offline(key)
    if not info.valid:
        with _lock:
            _current = info
        return info

    # Step 2: Check local activation cache
    from correctover._device import (
        device_fingerprint, check_local_activation, save_activation
    )

    key_prefix = _get_key_prefix(key)
    local_ok = check_local_activation(key_prefix)

    # Step 3: Online verification (device binding check)
    if online:
        online_result = _verify_online(key)
        if online_result is not None:
            if not online_result.get("valid", False):
                info = LicenseInfo(
                    PLAN_FREE, False, info.customer, info.expires_at,
                    online_result.get("message", "Key revoked or invalid")
                )
                with _lock:
                    _current = info
                return info

            # Check device binding from server response
            bound_device = online_result.get("device_id", "")
            current_device = device_fingerprint()

            if bound_device and bound_device != current_device:
                info = LicenseInfo(
                    info.plan, False, info.customer, info.expires_at,
                    f"此Key已绑定其他设备。请联系管理员解绑。",
                    device_bound=False,
                )
                with _lock:
                    _current = info
                return info

            info.device_bound = True

    # Step 4: Save local cache if not yet cached
    if not local_ok and info.valid:
        save_activation(
            key_prefix, device_fingerprint(),
            info.plan, info.expires_at, info.customer
        )
        info.device_bound = True

    with _lock:
        _current = info
    return info


def get_plan() -> str:
    """Current plan name. Checks expiry first."""
    _check_expiry()
    with _lock:
        if _current and _current.valid and _current.plan in _PRO_PLANS:
            return _current.plan
    return PLAN_FREE


def get_info() -> Optional[LicenseInfo]:
    """Full license info."""
    _check_expiry()
    with _lock:
        return _current


def is_pro() -> bool:
    """Has repair capability? (any paid plan)"""
    return get_plan() in _PRO_PLANS


def is_trial() -> bool:
    """Is current license a trial?"""
    return get_plan() == PLAN_TRIAL


def is_enterprise() -> bool:
    """Is current license Enterprise tier?"""
    return get_plan() == PLAN_ENTERPRISE


def is_device_bound() -> bool:
    """Is the license bound to this device?"""
    with _lock:
        return _current.device_bound if _current else False


def require_pro(feature: str = ""):
    """Raise LicenseError if not Pro tier."""
    if not is_pro():
        feat = f" ('{feature}')" if feature else ""
        raise LicenseError(
            f"Pro feature{feat} requires a paid license. "
            f"Current: {get_plan()}. "
            f"联系获取验证码: wangguigui@correctover.cn"
        )


def days_remaining() -> int:
    """Days until license expires."""
    with _lock:
        if not _current or not _current.valid:
            return -1
        if _current.plan == PLAN_LIFETIME:
            return 99999
        if _current.expires_at == 0:
            return 99999
        remaining = (_current.expires_at - int(time.time())) // 86400
        return max(0, remaining)


def is_expired() -> bool:
    """Check if a previously valid license has expired.

    Returns True ONLY if user had a license that expired.
    Free plan (never activated) returns False — not expired, just free.
    """
    with _lock:
        if not _current:
            # Never activated — not expired, just free
            return False
        if not _current.valid and _current.expires_at > 0:
            # Was valid but now invalid — likely expired
            return True
        if not _current.valid:
            # Invalid for other reasons (bad key etc.) — not "expired"
            return False
        if _current.expires_at == 0 or _current.plan == PLAN_LIFETIME:
            return False
        return time.time() > _current.expires_at


# ── Expiry Gate ──────────────────────────────────────────────────

def _check_expiry():
    """Internal: check if current license has expired, auto-downgrade if so."""
    with _lock:
        if not _current or not _current.valid:
            return
        if _current.expires_at == 0 or _current.plan == PLAN_LIFETIME:
            return
        if time.time() > _current.expires_at:
            exp_str = time.strftime("%Y-%m-%d", time.gmtime(_current.expires_at))
            _current.valid = False
            _current.message = f"验证码已过期({exp_str})，修复功能已停止。请联系获取新验证码。"


# ── Repair Control ───────────────────────────────────────────────

def consume_repair(action: str) -> bool:
    """Check if a repair action is allowed.

    Free/Expired: diagnosis only, repair locked → raises RepairLockedError
    Paid: all repairs allowed → returns True
    """
    is_repair = REPAIR_ACTIONS.get(action, True)

    if not is_repair:
        return True  # Diagnosis/cache hit — always free

    # This is a repair action
    _check_expiry()
    plan = get_plan()

    if plan == PLAN_FREE:
        action_cn = {
            "auto_retry": "L1重试",
            "model_fallback": "L2降级切换",
            "failover": "L3 Failover",
        }.get(action, action)

        if is_expired():
            raise RepairLockedError(
                f"⛔ 验证码已过期，修复功能已停止 — {action_cn}需要有效授权。\n"
                f"   联系获取新验证码: wangguigui@correctover.cn\n"
                f"   诊断功能仍免费使用"
            )
        else:
            raise RepairLockedError(
                f"🔒 检测免费，修复付费 — {action_cn}需要授权。\n"
                f"   当前: 免费版(仅诊断)\n"
                f"   Pro: ¥699/年 | 全功能自愈 | 一key一机\n"
                f"   联系获取验证码: wangguigui@correctover.cn"
            )

    # Check device binding
    if not is_device_bound():
        raise DeviceMismatchError(
            f"Key未绑定当前设备，请先激活。"
            f"设备指纹: {device_fingerprint_safe()}"
        )

    # Record the event in stats
    try:
        from correctover._stats import record_protection
        record_protection(action)
    except Exception:
        pass

    # 更新本地计数器 — 心跳带上来的数据源
    _increment_local_counter("total_protections")

    # 记录故障分类 — 心跳上报 "碰到什么问题"
    _record_fault(action, action)

    return True


def can_repair(action: str) -> bool:
    """Check if a repair action would be allowed (without raising)."""
    is_repair_flag = REPAIR_ACTIONS.get(action, True)
    if not is_repair_flag:
        return True
    return is_pro() and not is_expired()


def diagnose_free(diagnosis_result: str) -> str:
    """Add Free-plan hint to diagnosis output — "看得到修不了"."""
    # 记录诊断次数
    _increment_local_counter("total_calls")

    if is_pro() and not is_expired():
        return diagnosis_result

    if is_expired():
        hint = (
            "\n\n"
            "━━━ ⛔ 验证码已过期 ━━━\n"
            "✅ 诊断完成 — 以上是故障分析\n"
            "⛔ 修复已停止 — 验证码已过期，请联系获取新验证码\n"
            "   📧 wangguigui@correctover.cn"
        )
    else:
        hint = (
            "\n\n"
            "━━━ Correctover 免费版 ━━━\n"
            "✅ 诊断完成 — 以上是故障分析\n"
            "🔒 修复已锁定 — 需要授权自动修复\n"
            "   Pro: ¥699/年 | 全功能自愈 | 一key一机\n"
            "   📧 联系获取验证码: wangguigui@correctover.cn"
        )

    if diagnosis_result and len(diagnosis_result) > 20:
        return diagnosis_result + hint
    return diagnosis_result


# ── Feature Gating ───────────────────────────────────────────────

def max_providers() -> int:
    return 999 if is_pro() else 1


def max_heal_level() -> str:
    return "L3" if is_pro() else "L0"


def watermark_enabled() -> bool:
    return not is_pro()


def feature_gate(level: str = "L1"):
    """Decorator: block feature if license tier doesn't allow it."""
    def decorator(func):
        import functools
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            allowed = max_heal_level()
            levels = {"L0": 0, "L1": 1, "L2": 2, "L3": 3}
            if levels.get(level, 0) > levels.get(allowed, 0):
                raise LicenseError(
                    f"Self-healing level {level} requires paid license. "
                    f"Current: {get_plan()} (max {allowed}). "
                    f"联系获取验证码: wangguigui@correctover.cn"
                )
            return func(*args, **kwargs)
        return wrapper
    return decorator


def community_response_watermark(text: str) -> str:
    """Add subtle watermark to Free-plan responses."""
    if not watermark_enabled():
        return text
    if text and len(text) > 50:
        return text + "\n\n[Correctover 免费版 — 检测免费·修复付费 | 联系获取验证码: wangguigui@correctover.cn]"
    return text


def device_fingerprint_safe() -> str:
    """Get device fingerprint (safe, never raises)."""
    try:
        from correctover._device import device_fingerprint
        return device_fingerprint()
    except Exception:
        return "DEV-unknown"


def plan_summary() -> str:
    """Human-readable plan summary for console output."""
    _check_expiry()
    plan = get_plan()
    label = PLAN_LABELS.get(plan, plan)
    days = days_remaining()
    days_str = "永久" if days >= 99999 else f"{days}天"

    if plan == PLAN_FREE:
        if is_expired():
            return (
                f"  ⛔ 验证码已过期 — 修复功能已停止\n"
                f"  ⛔ 诊断仍免费 | 修复需新验证码\n"
                f"  📧 联系获取: wangguigui@correctover.cn"
            )
        return (
            f"  ℹ️  免费版 — 检测免费·修复付费\n"
            f"  ℹ️  诊断: 免费 | 修复: 需授权\n"
            f"  ℹ️  Pro: ¥699/年 | 全功能自愈 | 一key一机\n"
            f"  📧 联系获取验证码: wangguigui@correctover.cn"
        )
    elif plan in (PLAN_PRO, PLAN_ENTERPRISE):
        price = PLAN_PRICES.get(plan, 0)
        max_dev = PLAN_MAX_DEVICES.get(plan, 1)
        dev_str = f"最多{max_dev}台设备" if max_dev > 1 else "一key一机"
        bound = "✅已绑定" if is_device_bound() else "⚠️未绑定"
        return (
            f"  🔑 {label} — ¥{price}/年 | 剩余 {days_str} | {dev_str} | {bound}\n"
            f"  🔑 全功能自愈已启用: L1重试 + L2降级切换 + L3 Failover"
        )
    else:
        # trial / monthly / lifetime
        bound = "✅已绑定" if is_device_bound() else "⚠️未绑定"
        return (
            f"  🔑 {label} — 剩余 {days_str} | {bound}\n"
            f"  🔑 全功能自愈已启用"
        )


# ── Offline Verification ─────────────────────────────────────────

def _verify_offline(key: str) -> LicenseInfo:
    """Parse and HMAC-verify the key locally."""
    declared_plan = None
    encoded = None
    for prefix, plan in _PREFIX_MAP.items():
        if key.startswith(prefix):
            declared_plan = plan
            encoded = key[len(prefix):]
            break

    if declared_plan is None:
        return LicenseInfo(PLAN_FREE, False, "", 0,
                           "Key must start with CV-TRL-/CV-PRO-/CV-ENT- or legacy NB- prefix")

    try:
        decoded = base64.urlsafe_b64decode(encoded + "==").decode("utf-8")
    except Exception:
        return LicenseInfo(PLAN_FREE, False, "", 0, "Key contains invalid data")

    if "." not in decoded:
        return LicenseInfo(PLAN_FREE, False, "", 0, "Key format invalid")

    payload_str, sig_hex = decoded.rsplit(".", 1)

    try:
        payload = json.loads(payload_str)
    except json.JSONDecodeError:
        return LicenseInfo(PLAN_FREE, False, "", 0, "Key payload corrupted")

    for f in ("p", "e", "c"):
        if f not in payload:
            return LicenseInfo(PLAN_FREE, False, "", 0, f"Key missing field '{f}'")

    expected_sig = _hmac_sign(payload_str)
    sig_ok = hmac.compare_digest(sig_hex, expected_sig)
    # Legacy NB- prefix keys may use empty HMAC secret — try fallback
    if not sig_ok and key.startswith("NB-"):
        legacy_sig = hmac.new(b"", payload_str.encode("utf-8"), hashlib.sha256).hexdigest()
        sig_ok = hmac.compare_digest(sig_hex, legacy_sig)
    if not sig_ok:
        return LicenseInfo(PLAN_FREE, False, "", 0, "Key signature invalid — forged or corrupted")

    if payload["e"] != 0:
        now = int(time.time())
        if now > payload["e"]:
            exp_str = time.strftime("%Y-%m-%d", time.gmtime(payload["e"]))
            return LicenseInfo(PLAN_FREE, False, payload.get("c", ""), payload["e"],
                               f"License expired on {exp_str} — 验证码已过期，请联系获取新验证码")

    customer = payload.get("c", "")
    plan = payload["p"]
    expires = payload["e"]

    if plan in (PLAN_LIFETIME,) or expires == 0:
        msg = f"Lifetime license for {customer}"
    else:
        exp_str = time.strftime("%Y-%m-%d", time.gmtime(expires)) if expires else "永久"
        msg = f"Valid {plan} license for {customer} (expires {exp_str})"

    return LicenseInfo(
        plan=plan,
        valid=True,
        customer=customer,
        expires_at=expires,
        message=msg,
    )


def _get_key_prefix(key: str) -> str:
    """Extract key prefix for activation tracking."""
    for prefix in _PREFIX_MAP:
        if key.startswith(prefix):
            return prefix
    return "NB-UNK-"


def _hmac_sign(payload_str: str) -> str:
    """Compute HMAC-SHA256 hex digest."""
    secret = _get_hmac_secret()
    return hmac.new(secret, payload_str.encode("utf-8"), hashlib.sha256).hexdigest()


# ── Online Verification ──────────────────────────────────────────

def _verify_online(key: str) -> Optional[dict]:
    """POST key to our API for revocation + device binding check."""
    for url in (_VERIFY_URL, _VERIFY_URL_FALLBACK):
        try:
            import httpx
            from correctover._device import device_fingerprint

            resp = httpx.post(
                url,
                json={"key": key, "device_id": device_fingerprint()},
                timeout=_ONLINE_TIMEOUT,
            )
            if resp.status_code == 200:
                return resp.json()
            if url == _VERIFY_URL:
                continue
            return {"valid": False, "message": f"Server returned {resp.status_code}"}
        except Exception:
            if url == _VERIFY_URL:
                continue
            return None
    return None


# ── Env var auto-init ────────────────────────────────────────────

def _auto_init():
    key = os.environ.get("CORRECTOVER_LICENSE_KEY", "").strip()
    if key:
        # 先尝试当验证码激活，如果失败则当 license key 验证
        # 验证码特征: NB-TRL3-/NB-MON-/NB-ANN-/NB-LTM- + 8位短码
        # License key 特征: 同样前缀 + base64 长码（含 . 分隔的 HMAC 签名）
        if _looks_like_code(key):
            activate(key)
        else:
            verify(key)

    # 启动心跳 — 知道谁在用
    try:
        from correctover._ping import ping
        ping()
    except Exception:
        pass

def _looks_like_code(key: str) -> bool:
    """判断 key 是验证码还是 license key.

    验证码: NB-TRL3-aB3kX9mP (前缀 + 8位字母数字)
    License key: NB-PRO-base64payload.hmac (包含 base64 编码的长字符串)
    """
    for prefix in _PREFIX_MAP:
        if key.startswith(prefix):
            suffix = key[len(prefix):]
            # 验证码: 8位字母数字
            if len(suffix) == 8 and suffix.isalnum():
                return True
            # License key: 更长的 base64 字符串
            return False
    return False

_auto_init()
