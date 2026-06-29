# Copyright 2024-2026 Correctover Team
# Licensed under the Apache License, Version 2.0 (the "License")
#
"""Free provider setup — zero-cost onboarding with Agnes AI.

Provides a one-shot setup flow that checks for an existing Agnes API key,
guides the user through obtaining one, configures it locally, and tests
connectivity — all without leaving the terminal.

Usage:
    from correctover.free_provider import setup_free_provider
    ok, msg = setup_free_provider()
"""

import json
import os
import sys
import subprocess
from typing import Optional

_AGNES_URL = "https://apihub.agnes-ai.com/v1"
_AGNES_ENV = "AGNES_API_KEY"
_AGNES_MODEL = "agnes-2.0-flash"
_AGNES_SIGNUP = "https://apihub.agnes-ai.com/register"

_CONFIG_DIR = os.path.expanduser("~/.correctover")
_CONFIG_FILE = os.path.join(_CONFIG_DIR, "config.json")


def _load_config() -> dict:
    """Load ~/.correctover/config.json, returning {} on any failure."""
    try:
        with open(_CONFIG_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_config(config: dict) -> None:
    """Atomically write config to ~/.correctover/config.json."""
    os.makedirs(_CONFIG_DIR, exist_ok=True)
    tmp = _CONFIG_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(config, f, indent=2)
    os.replace(tmp, _CONFIG_FILE)


def _set_env_var(name: str, value: str) -> None:
    """Persist an environment variable for this user (Windows or POSIX)."""
    os.environ[name] = value  # current session
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 f'[System.Environment]::SetEnvironmentVariable("{name}", "{value}", "User")'],
                capture_output=True, timeout=10,
            )
        else:
            # POSIX: write to shell profile if not already there
            rc_file = os.path.expanduser("~/.bashrc")
            marker = f"# Correctover: {name}"
            with open(rc_file) as f:
                if marker not in f.read():
                    with open(rc_file, "a") as f2:
                        f2.write(f"\n{marker}\nexport {name}=\"{value}\"\n")
    except Exception:
        pass  # non-critical


def _test_connectivity(api_key: str) -> Optional[str]:
    """Test Agnes AI connectivity. Returns error message on failure, None on success."""
    try:
        from correctover._engine import SelfHealingEngine, ProviderConfig
        engine = SelfHealingEngine()
        engine.add_provider(ProviderConfig(
            name="agnes",
            base_url=_AGNES_URL,
            api_key=api_key,
            models=[_AGNES_MODEL],
        ))
        result = engine.call_sync("Say exactly: ok", model=_AGNES_MODEL, timeout=15)
        if hasattr(result, "latency_ms"):
            return None  # success
        text = str(result)
        if text and len(text) > 0:
            return None
        return "Empty response"
    except Exception as e:
        return str(e)


def _prompt_input(prompt_text: str) -> str:
    """Read a line from stdin with a prompt."""
    try:
        return input(prompt_text).strip()
    except (EOFError, KeyboardInterrupt):
        return ""


def setup_free_provider(api_key: str = "", interactive: bool = True, verbose: bool = True) -> tuple:
    """One-shot free provider setup.

    Args:
        api_key: Pre-supplied API key. If empty, tries env var then interactive prompt.
        interactive: Whether to prompt the user interactively when no key is found.
        verbose: Whether to print status messages.

    Returns:
        (success: bool, message: str)
    """
    def _log(msg):
        if verbose:
            try:
                _print(msg)
            except Exception:
                print(msg)

    # ── Step 1: Resolve API key ──
    key = api_key or os.environ.get(_AGNES_ENV, "")

    if key:
        _log(f"  ✅ Found Agnes API key in environment")
    elif interactive:
        _log(f"\n  🌟 Correctover Free Provider — Agnes AI")
        _log(f"  {'─' * 50}")
        _log(f"  Agnes AI provides free multimodal AI models ($0/mo).")
        _log(f"  To get your free API key:")
        _log(f"    1. Visit: {_AGNES_SIGNUP}")
        _log(f"    2. Register (free, no credit card)")
        _log(f"    3. Copy your API key from the dashboard")
        _log()
        key = _prompt_input("  Paste your Agnes API key (or press Enter to open browser): ")

        if not key:
            _log(f"  Opening browser...")
            import webbrowser
            try:
                webbrowser.open(_AGNES_SIGNUP)
            except Exception:
                _log(f"  Please visit: {_AGNES_SIGNUP}")
            key = _prompt_input("\n  After registering, paste your API key: ")
            if not key:
                return False, "No API key provided. Run 'nb-doctor free-provider' when ready."

    if not key:
        return False, f"No Agnes API key found. Set {_AGNES_ENV} or run 'nb-doctor free-provider'."

    # ── Step 2: Save to config ──
    config = _load_config()
    config.setdefault("providers", {})["agnes"] = {
        "api_key": key,
        "base_url": _AGNES_URL,
        "default_model": _AGNES_MODEL,
    }
    config["default_provider"] = "agnes"
    _save_config(config)
    _log(f"  ✅ Config saved to {_CONFIG_FILE}")

    # ── Step 3: Set environment variable ──
    _set_env_var(_AGNES_ENV, key)
    _log(f"  ✅ Environment variable {_AGNES_ENV} set")

    # ── Step 4: Test connectivity ──
    _log(f"  🔄 Testing connectivity...")
    err = _test_connectivity(key)
    if err:
        _log(f"  ⚠️  Connectivity test failed: {err}")
        _log(f"  ℹ️  Your key is saved; the API may need a moment. Try:")
        _log(f"     nb-doctor run")
        return True, f"Key saved but connectivity test failed: {err}"
    else:
        _log(f"  ✅ Agnes AI connected successfully!")
        _log(f"\n  🎉 You're ready to go! Try:")
        _log(f"     nb-doctor run")
        _log(f"     nb.run('hello')  # in Python")
        return True, "Agnes AI configured and verified successfully."


def _print(*args, **kwargs):
    """Print with emoji-safe fallback for Windows."""
    try:
        print(*args, **kwargs)
    except UnicodeEncodeError:
        for a in args:
            s = str(a)
            print(s.encode("utf-8", errors="replace").decode("utf-8", errors="replace"), **kwargs)
