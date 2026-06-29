# Copyright 2024-2025 Correctover Team
# Licensed under the Apache License, Version 2.0 (the "License")
# Correctover™ — Proprietary MAPE-K Adaptive Loop Architecture

#
"""Correctover Device Fingerprint — 一key一机，防共享.

Generates a unique, stable device fingerprint from hardware identifiers.
Used to bind a license key to a single physical machine.

Fingerprint composition:
  - MAC address (primary NIC)
  - Hostname
  - Disk serial number (root partition)
  - CPU info
  - Machine ID (/etc/machine-id on Linux)

Combined → SHA256 hash → 16-char device ID (e.g. "DEV-a3b4c5d6e7f8g9h0")
"""

import hashlib
import os
import platform
import subprocess
import uuid
from typing import Optional


# ── Device ID Cache ──────────────────────────────────────────────

_cached_device_id: Optional[str] = None


# ── Hardware collectors ──────────────────────────────────────────

def _get_mac_address() -> str:
    """Get MAC address of the primary network interface."""
    try:
        mac = uuid.getnode()
        return ":".join(f"{(mac >> (8 * i)) & 0xff:02x}" for i in range(5, -1, -1))
    except Exception:
        return "unknown-mac"


def _get_hostname() -> str:
    """Get system hostname."""
    try:
        return platform.node() or "unknown-host"
    except Exception:
        return "unknown-host"


def _get_disk_serial() -> str:
    """Get disk serial number of root partition."""
    try:
        if platform.system() == "Linux":
            # Try /dev/disk/by-id first
            by_id = "/dev/disk/by-id"
            if os.path.isdir(by_id):
                for entry in os.listdir(by_id):
                    # Skip partition entries, want the disk
                    if not entry.startswith("part") and "ata" in entry.lower():
                        return entry
            # Fallback: lsblk
            try:
                result = subprocess.run(
                    ["lsblk", "-n", "-o", "SERIAL", "/dev/sda"],
                    capture_output=True, text=True, timeout=3
                )
                serial = result.stdout.strip()
                if serial:
                    return serial
            except Exception:
                pass
        elif platform.system() == "Darwin":
            result = subprocess.run(
                ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
                capture_output=True, text=True, timeout=3
            )
            for line in result.stdout.split("\n"):
                if "IOPlatformSerialNumber" in line:
                    return line.split("=")[-1].strip().strip('"')
        elif platform.system() == "Windows":
            result = subprocess.run(
                ["wmic", "diskdrive", "get", "serialnumber"],
                capture_output=True, text=True, timeout=3
            )
            lines = [l.strip() for l in result.stdout.strip().split("\n") if l.strip()]
            if len(lines) > 1:
                return lines[1]
    except Exception:
        pass
    return "unknown-disk"


def _get_cpu_info() -> str:
    """Get CPU identifier."""
    try:
        if platform.system() == "Linux":
            with open("/proc/cpuinfo", "r") as f:
                for line in f:
                    if line.startswith("model name"):
                        return line.split(":")[1].strip()
        elif platform.system() == "Darwin":
            result = subprocess.run(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                capture_output=True, text=True, timeout=3
            )
            return result.stdout.strip()
        elif platform.system() == "Windows":
            return platform.processor() or "unknown-cpu"
    except Exception:
        pass
    return "unknown-cpu"


def _get_machine_id() -> str:
    """Get Linux machine-id or equivalent."""
    try:
        if platform.system() == "Linux":
            # /etc/machine-id is stable across reboots
            for path in ["/etc/machine-id", "/var/lib/dbus/machine-id"]:
                if os.path.exists(path):
                    with open(path, "r") as f:
                        return f.read().strip()
        elif platform.system() == "Darwin":
            result = subprocess.run(
                ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
                capture_output=True, text=True, timeout=3
            )
            for line in result.stdout.split("\n"):
                if "IOPlatformUUID" in line:
                    return line.split("=")[-1].strip().strip('"')
        elif platform.system() == "Windows":
            result = subprocess.run(
                ["wmic", "csproduct", "get", "UUID"],
                capture_output=True, text=True, timeout=3
            )
            lines = [l.strip() for l in result.stdout.strip().split("\n") if l.strip()]
            if len(lines) > 1:
                return lines[1]
    except Exception:
        pass
    return "unknown-machine"


# ── Public API ───────────────────────────────────────────────────

def device_fingerprint() -> str:
    """Generate a stable device fingerprint.

    Returns a 16-char hex string prefixed with 'DEV-'.
    This fingerprint is deterministic — same hardware always produces same ID.
    Changing major hardware (NIC, disk, motherboard) will change the ID,
    requiring license re-activation.

    Returns:
        e.g. "DEV-a3b4c5d6e7f8g9h0"
    """
    global _cached_device_id
    if _cached_device_id:
        return _cached_device_id

    # Collect hardware identifiers
    components = [
        _get_mac_address(),
        _get_hostname(),
        _get_disk_serial(),
        _get_cpu_info(),
        _get_machine_id(),
    ]

    # Combine and hash
    raw = "|".join(components)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    device_id = f"DEV-{digest}"
    _cached_device_id = device_id
    return device_id


def device_info() -> dict:
    """Get detailed device information for diagnostics.

    Returns all components used in fingerprint + the final fingerprint.
    """
    return {
        "fingerprint": device_fingerprint(),
        "mac": _get_mac_address(),
        "hostname": _get_hostname(),
        "disk_serial": _get_disk_serial(),
        "cpu": _get_cpu_info(),
        "machine_id": _get_machine_id(),
        "platform": platform.system(),
        "platform_release": platform.release(),
    }


def is_same_device(stored_fingerprint: str) -> bool:
    """Check if the current device matches a stored fingerprint.

    Args:
        stored_fingerprint: Previously recorded device fingerprint

    Returns:
        True if current device matches
    """
    if not stored_fingerprint:
        return False
    return device_fingerprint() == stored_fingerprint


# ── Local activation cache ───────────────────────────────────────
# Stores the activation record locally for offline validation

_ACTIVATION_DIR = os.path.join(os.path.expanduser("~"), ".correctover")
_ACTIVATION_FILE = os.path.join(_ACTIVATION_DIR, "activation.json")


def save_activation(key_prefix: str, device_id: str, plan: str,
                    expires_at: int, customer: str) -> None:
    """Save activation record locally for offline validation.

    This is written once on first activation and checked on every startup.
    """
    try:
        os.makedirs(_ACTIVATION_DIR, exist_ok=True)
        data = {
            "key_prefix": key_prefix,
            "device_id": device_id,
            "plan": plan,
            "expires_at": expires_at,
            "customer": customer,
            "activated_at": int(__import__("time").time()),
            "version": 1,
        }
        with open(_ACTIVATION_FILE, "w") as f:
            __import__("json").dump(data, f, ensure_ascii=False)
    except Exception:
        pass  # Must not break main path


def load_activation() -> Optional[dict]:
    """Load local activation record. Returns None if not found."""
    try:
        if not os.path.exists(_ACTIVATION_FILE):
            return None
        with open(_ACTIVATION_FILE, "r") as f:
            return __import__("json").load(f)
    except Exception:
        return None


def clear_activation() -> None:
    """Clear local activation record (deactivation)."""
    try:
        if os.path.exists(_ACTIVATION_FILE):
            os.remove(_ACTIVATION_FILE)
    except Exception:
        pass


def check_local_activation(key_prefix: str) -> bool:
    """Check if the current key is activated on this device.

    Validates:
    1. Activation file exists
    2. Key prefix matches
    3. Device fingerprint matches
    4. License not expired

    Returns:
        True if locally activated and valid
    """
    import time as _time

    record = load_activation()
    if not record:
        return False

    # Key prefix must match
    if record.get("key_prefix") != key_prefix:
        return False

    # Device must match
    if record.get("device_id") != device_fingerprint():
        return False

    # Must not be expired
    expires = record.get("expires_at", 0)
    if expires > 0 and _time.time() > expires:
        return False

    return True
