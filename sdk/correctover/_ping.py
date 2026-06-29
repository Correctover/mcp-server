#!/usr/bin/env python3
"""Correctover Telemetry Ping — 谁在用我们的软件.

设计原则:
  - 极轻量: 单次 POST, <1KB, 不阻塞主流程
  - 非侵入: 异步发送, 失败静默, 不影响用户体验
  - 可追踪: 设备指纹 + 版本 + 平台 + plan → 唯一用户画像
  - 可运营: 后台看到谁在用, 用多久, 什么版本, 什么plan

数据存储: OSS ping-db/ 目录, 按日期分文件
  - ping-db/daily/2026-06-02.jsonl  — 当日心跳日志(append)
  - ping-db/users/{device_id}.json  — 用户档案(最新状态)

心跳触发时机:
  1. SDK import 时自动发一次 (首次/每天一次)
  2. activate() 激活时发一次
  3. consume_repair() 修复时累计计数

本地节流: ~/.correctover/last_ping 记录上次发送时间, 24小时内不重复发
"""

import json
import os
import time
import threading
import platform
import sys

# ── Config ───────────────────────────────────────────────────────

_PING_URL = "https://api.correctover.cn/api/v1/ping"
_PING_URL_FALLBACK = "https://license-api-correctover-hk.oss-cn-hongkong.aliyuncs.com/api/v1/ping"
_TELEMETRY_URL = "https://license-api-correctover-hk.oss-cn-hongkong.aliyuncs.com/api/v1/telemetry"
_TELEMETRY_URL_FALLBACK = "https://license-api-correctover-edouhcvhbo.cn-hangzhou.fcapp.run/api/v1/telemetry"
_PING_TIMEOUT = 3  # 秒, 极短超时

_LOCAL_DIR = os.path.join(os.path.expanduser("~"), ".correctover")
_LAST_PING_FILE = os.path.join(_LOCAL_DIR, "last_ping")
_PING_INTERVAL = 86400  # 24小时节流


# ── Public API ───────────────────────────────────────────────────

def ping(extra=None):
    """发送心跳到后台（异步, 非阻塞）.

    24小时内只发一次, 节省带宽。
    失败静默, 绝不影响主流程。
    同时发送本地积攒的遥测事件。
    """
    try:
        # Check opt-in (default OFF)
        if os.environ.get("CORRECTOVER_TELEMETRY", "0") != "1":
            return

        # 节流检查
        if _should_throttle():
            return

        data = _build_ping_data(extra)

        # 异步发送心跳
        t = threading.Thread(target=_send_ping, args=(data,), daemon=True)
        t.start()

        # 异步发送遥测事件（如果有）
        t2 = threading.Thread(target=_flush_local_telemetry, daemon=True)
        t2.start()

        # 记录发送时间
        _record_ping_time()

    except Exception:
        pass  # 绝不阻塞主流程


def ping_sync(extra=None):
    """同步发送心跳（仅在 activate 时调用）."""
    try:
        data = _build_ping_data(extra)
        _send_ping(data)
        _record_ping_time()
    except Exception:
        pass


# ── Internal ─────────────────────────────────────────────────────

def _should_throttle():
    """24小时内只发一次心跳."""
    try:
        if os.path.exists(_LAST_PING_FILE):
            last = float(open(_LAST_PING_FILE).read().strip())
            if time.time() - last < _PING_INTERVAL:
                return True
    except Exception:
        pass
    return False


def _record_ping_time():
    """记录本次心跳时间."""
    try:
        os.makedirs(_LOCAL_DIR, exist_ok=True)
        with open(_LAST_PING_FILE, "w") as f:
            f.write(str(int(time.time())))
    except Exception:
        pass


def _sdk_version():
    """Get SDK version from package metadata."""
    try:
        from correctover import __version__
        return __version__
    except Exception:
        return "unknown"


def _build_ping_data(extra=None):
    """构建心跳数据包."""
    data = {
        "v": _sdk_version(),                       # SDK 版本（动态读取）
        "dev": _safe_device_id(),             # 设备指纹
        "py": f"{sys.version_info.major}.{sys.version_info.minor}",  # Python 版本
        "os": platform.system(),              # 操作系统
        "os_ver": platform.release(),         # OS 版本
        "ts": int(time.time()),               # 时间戳
        "plan": _safe_plan(),                 # 当前 plan
        "expire": _safe_expires(),            # 过期时间
    }

    # 读取本地统计
    try:
        stats_file = os.path.join(_LOCAL_DIR, "stats.json")
        if os.path.exists(stats_file):
            with open(stats_file) as f:
                stats = json.load(f)
            if isinstance(stats, dict):
                calls = stats.get("total_calls", 0)
                protections = stats.get("total_protections", 0)
                if calls:
                    data["calls"] = calls
                if protections:
                    data["protects"] = protections
                # 故障分类 — "碰到什么问题"
                last_fault = stats.get("last_fault", "")
                if last_fault:
                    data["last_fault"] = last_fault
                fault_counts = stats.get("fault_counts", {})
                if fault_counts:
                    data["faults"] = fault_counts
    except Exception:
        pass

    if extra:
        data.update(extra)

    return data


def _safe_device_id():
    """安全获取设备指纹."""
    try:
        from correctover._device import device_fingerprint
        return device_fingerprint()
    except Exception:
        return "unknown"


def _safe_plan():
    """安全获取当前 plan."""
    try:
        from correctover.license import get_plan
        return get_plan()
    except Exception:
        return "free"


def _safe_expires():
    """安全获取过期时间."""
    try:
        from correctover.license import get_info
        info = get_info()
        return info.expires_at if info else 0
    except Exception:
        return 0


def _send_ping(data):
    """发送心跳到服务器."""
    body = json.dumps(data, separators=(",", ":")).encode("utf-8")

    for url in (_PING_URL, _PING_URL_FALLBACK):
        try:
            import httpx
            resp = httpx.post(url, content=body, headers={"Content-Type": "application/json"}, timeout=_PING_TIMEOUT)
            if resp.status_code == 200:
                return
        except Exception:
            continue

        try:
            import urllib.request
            req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=_PING_TIMEOUT) as resp:
                if resp.status == 200:
                    return
        except Exception:
            continue


def _flush_local_telemetry():
    """读取本地遥测缓存并发送到服务器（异步, 静默失败）."""
    try:
        # 1. 先尝试从 TelemetryCollector 导出积攒的事件
        try:
            from correctover.telemetry import TelemetryCollector
            # 获取引擎的遥测收集器（如果存在）
            from correctover import _engine
            if hasattr(_engine, '_global_telemetry'):
                tc = _engine._global_telemetry
                if tc and hasattr(tc, 'inspect_queue'):
                    queue = tc.inspect_queue()
                    if queue:
                        _write_telemetry_events(queue)
                        tc.clear()
        except Exception:
            pass

        # 2. 读取本地遥测缓存文件
        tel_file = os.path.join(_LOCAL_DIR, "telemetry_queue.jsonl")
        if not os.path.exists(tel_file):
            return

        with open(tel_file) as f:
            lines = [l.strip() for l in f if l.strip()]
        if not lines:
            return

        events = []
        for line in lines:
            try:
                events.append(json.loads(line))
            except Exception:
                pass
        if not events:
            return

        # Add SDK language marker
        for evt in events:
            if "sdk_lang" not in evt:
                evt["sdk_lang"] = "python"

        body = json.dumps({"events": events}, separators=(",", ":")).encode("utf-8")

        for url in (_TELEMETRY_URL, _TELEMETRY_URL_FALLBACK):
            try:
                import httpx
                resp = httpx.post(url, content=body, headers={"Content-Type": "application/json"}, timeout=5)
                if resp.status_code == 200:
                    # 成功 — 清空本地缓存
                    try:
                        os.remove(tel_file)
                    except Exception:
                        pass
                    return
            except Exception:
                continue

            try:
                import urllib.request
                req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
                with urllib.request.urlopen(req, timeout=5) as resp:
                    if resp.status == 200:
                        try:
                            os.remove(tel_file)
                        except Exception:
                            pass
                        return
            except Exception:
                continue
    except Exception:
        pass  # 静默


def _write_telemetry_events(events):
    """将遥测事件写入本地缓存文件."""
    try:
        os.makedirs(_LOCAL_DIR, exist_ok=True)
        tel_file = os.path.join(_LOCAL_DIR, "telemetry_queue.jsonl")
        with open(tel_file, "a") as f:
            for evt in events:
                f.write(json.dumps(evt, separators=(",", ":"), ensure_ascii=False) + "\n")
    except Exception:
        pass
