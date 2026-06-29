#!/usr/bin/env python3
# PYTHONIOENCODING=utf-8
"""Build correctover SDK from NeuralBridge source.

Usage:
  python build_correctover.py                              # NB_DIR from env or default
  python build_correctover.py --python py -3.12            # custom Python path
  python build_correctover.py --version 1.3.0              # override version
  python build_correctover.py --nb-dir D:/path/to/sdk      # override source dir

Environment:
  NEURALBRIDGE_SRC_DIR   Override NB_DIR (highest precedence after CLI)
  CORRECTOVER_VERSION    Override version string
"""
import os, sys, re, shutil, py_compile, glob, subprocess, argparse

HERE = os.path.dirname(os.path.abspath(__file__))

# ── CLI ──────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser(description="Build correctover SDK from NeuralBridge source")
parser.add_argument("--nb-dir", default=None,
                    help="Path to neuralbridge-sdk checkout (overrides NEURALBRIDGE_SRC_DIR env)")
parser.add_argument("--python", default=sys.executable,
                    help="Python interpreter to use for compilation & build")
parser.add_argument("--version", default=None,
                    help="SDK version string (default: 1.3.0, overrides CORRECTOVER_VERSION env)")
args = parser.parse_args()

# Source directory: CLI > env > default
NB_DIR = (args.nb_dir
          or os.environ.get("NEURALBRIDGE_SRC_DIR")
          or r"D:\workspace\neuralbridge-sdk")

# Version: CLI > env > default
VERSION = (args.version
           or os.environ.get("CORRECTOVER_VERSION")
           or "1.3.0")

PYTHON = args.python

OUT_DIR = os.path.join(HERE, "correctover")

TELEMETRY_OLD = "license-api-neuralbridge-hk-rewfrmblft.cn-hongkong.fcapp.run"
TELEMETRY_NEW = "license-api-correctover-hk.oss-cn-hongkong.aliyuncs.com"

# Ensure we use forward slashes for path manipulation
NB_DIR = NB_DIR.replace("\\", "/")


def get_source_files():
    nb_pkg = os.path.join(NB_DIR, "neuralbridge")
    files = []
    for root, dirs, fnames in os.walk(nb_pkg):
        if "__pycache__" in root:
            continue
        for f in fnames:
            if f.endswith(".py"):
                full = os.path.join(root, f)
                rel = os.path.relpath(full, nb_pkg)
                files.append((full, rel))
    return files


def replace_namespace(content):
    content = content.replace("neuralbridge", "correctover")
    content = content.replace("NeuralBridge", "Correctover")
    content = content.replace("NEURALBRIDGE", "CORRECTOVER")
    content = content.replace(TELEMETRY_OLD, TELEMETRY_NEW)
    return content


def fix_multi_line_fstrings(content):
    """Fix multi-line f-strings that are invalid Python syntax."""
    fixes = {
        '_print(f"\n  ✅ 修复脚本已生成: ': '_print(f"\\n  ✅ 修复脚本已生成: ',
        '_print(f"\n  ❌ 无法写入修复脚本: ': '_print(f"\\n  ❌ 无法写入修复脚本: ',
        '_print(f"\n  {\'─\' * 55}":': '_print(f"\\n  {\'─\' * 55}"',
    }
    for old, new in fixes.items():
        content = content.replace(old, new)
    return content


def copy_and_rename():
    print("=" * 60)
    print("[1/6] Copying and renaming source files...")
    print("=" * 60)
    if os.path.exists(OUT_DIR):
        shutil.rmtree(OUT_DIR)

    files = get_source_files()
    for src_full, rel_path in files:
        dest = os.path.join(OUT_DIR, rel_path)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(src_full, "r", encoding="utf-8") as f:
            content = f.read()
        content = replace_namespace(content)
        content = fix_multi_line_fstrings(content)
        with open(dest, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"  [COPY] {rel_path}")

    print(f"  Total: {len(files)} files copied")

    # ── Override correctover-specific files ──────────────────────
    # _version.py
    ver_path = os.path.join(OUT_DIR, "_version.py")
    with open(ver_path, "w", encoding="utf-8") as f:
        f.write(f'# Copyright 2024-2026 Correctover Team\n'
                f'# Proprietary Commercial License\n'
                f'"""Version info for Correctover SDK."""\n'
                f'__version__ = "{VERSION}"\n'
                f'version = __version__\n')
    print(f"  [OVERRIDE] _version.py (v{VERSION})")

    # _fixes2.py — use repo version if available (maintained separately from NB)
    fixes2_src = os.path.join(OUT_DIR, "_fixes2.py")
    fixes2_repo = os.path.join(HERE, "_fixes2_repo.py")
    if os.path.exists(fixes2_repo):
        shutil.copy2(fixes2_repo, fixes2_src)
        print(f"  [OVERRIDE] _fixes2.py (from repo)")
    else:
        print(f"  [WARN] _fixes2.py not found in repo, keeping NB version")

    # __init__.py — use repo version which has the _apply_patches calls
    init_src = os.path.join(OUT_DIR, "__init__.py")
    init_repo = os.path.join(HERE, "correctover", "__init__.py")
    if os.path.exists(init_repo) and os.path.realpath(init_repo) != os.path.realpath(init_src):
        shutil.copy2(init_repo, init_src)
        print(f"  [OVERRIDE] __init__.py (from repo, with _apply_patches calls)")
    elif os.path.realpath(init_repo) == os.path.realpath(init_src):
        print(f"  [SKIP] __init__.py already in place (same file)")
    else:
        print(f"  [WARN] __init__.py not found in repo, keeping NB version")

    return files


def create_pyproject():
    print("\n[2/6] Creating pyproject.toml...")
    pyproject = f"""[build-system]
requires = ["setuptools>=64,<75"]
build-backend = "setuptools.build_meta"

[project]
name = "correctover"
version = "{VERSION}"
description = "Correctover — Failure is not fatal. Protocol-level contract validation with automatic verified failover for LLM APIs."
readme = "README.md"
requires-python = ">=3.12"
license = {{text = "Proprietary Commercial License — see LICENSE"}}
keywords = ["llm", "self-healing", "failover", "circuit-breaker", "api-resilience", "openai", "anthropic", "deepseek", "contract-validation", "correctover", "ai-gateway", "semantic-verification"]
authors = [{{name = "Correctover Team", email = "team@correctover.com"}}]
maintainers = [{{name = "Correctover Team", email = "team@correctover.com"}}]
classifiers = [
    "Development Status :: 5 - Production/Stable",
    "Intended Audience :: Developers",
    "License :: Other/Proprietary License",
    "Operating System :: OS Independent",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.12",
    "Topic :: Scientific/Engineering :: Artificial Intelligence",
    "Topic :: Software Development :: Libraries :: Python Modules",
]
dependencies = ["httpx>=0.24.0", "aiohttp>=3.8.0"]

[project.urls]
Homepage = "https://correctover.com"
Documentation = "https://correctover.com/docs"
Changelog = "https://correctover.com/docs/changelog"
"Bug Tracker" = "https://correctover.com/support"

[project.scripts]
"correctover-shield" = "correctover.shield:main"

[tool.setuptools.packages.find]
include = ["correctover*"]

[tool.setuptools.package-data]
correctover = ["*.pyc"]
"""
    with open(os.path.join(HERE, "pyproject.toml"), "w", encoding="utf-8") as f:
        f.write(pyproject)
    print("  [OK] pyproject.toml")


def create_license():
    text = f"""CORRECTOVER SDK — PROPRIETARY COMMERCIAL LICENSE
Copyright (c) 2024-2026 Correctover Team. All rights reserved.

This software is NOT open source. It is distributed as compiled
bytecode only. Redistribution requires a valid commercial license.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND.
"""
    with open(os.path.join(HERE, "LICENSE"), "w", encoding="utf-8") as f:
        f.write(text)
    print("  [OK] LICENSE")


def create_readme():
    text = """# Correctover SDK

**Failure is not fatal.** Protocol-level contract validation with automatic verified failover for LLM APIs.

## Install

```bash
pip install correctover
```

## Quick Start

```python
import correctover
result = correctover.run("Hello!")
print(result)
```

## License

Proprietary Commercial License. See LICENSE file.
"""
    with open(os.path.join(HERE, "README.md"), "w", encoding="utf-8") as f:
        f.write(text)
    print("  [OK] README.md")


def strip_pyc_paths(pkg_dir):
    """Recursively strip absolute paths from .pyc co_filename attributes."""
    import marshal, struct

    for root, dirs, files in os.walk(pkg_dir):
        for fn in files:
            if not fn.endswith(".pyc"):
                continue
            fpath = os.path.join(root, fn)
            with open(fpath, "rb") as fh:
                data = fh.read()

            flags = struct.unpack("<I", data[4:8])[0]
            header = 16  # same header size for 3.11 and 3.12
            body = data[header:]

            try:
                code = marshal.loads(body)
            except Exception:
                continue

            def _strip(obj, visited=None):
                if visited is None:
                    visited = set()
                if id(obj) in visited:
                    return obj
                visited.add(id(obj))

                fname = os.path.basename(obj.co_filename)
                if obj.co_filename != fname:
                    obj = obj.replace(co_filename=fname)
                new_consts = []
                for c in obj.co_consts:
                    if hasattr(c, "co_code"):
                        c = _strip(c, visited)
                    new_consts.append(c)
                if new_consts != list(obj.co_consts):
                    obj = obj.replace(co_consts=tuple(new_consts))
                return obj

            code = _strip(code)
            new_body = marshal.dumps(code)
            with open(fpath, "wb") as fh:
                fh.write(data[:header] + new_body)
            print(f"  [STRIP] {fn}")


def compile_all():
    print("\n[3/6] Compiling .py -> .pyc (closed source)...")

    # Ensure target dir exists
    pkg = OUT_DIR
    if not os.path.isdir(pkg):
        print(f"  [FAIL] Package directory not found: {pkg}")
        return False

    # Collect all .py files (exclude __init__.py which stays as source)
    all_py = []
    for root, dirs, files in os.walk(pkg):
        for f in files:
            if f.endswith(".py") and f != "__init__.py":
                all_py.append(os.path.join(root, f))

    # Compile each file
    compiled = 0
    failed = 0
    for py_path in all_py:
        try:
            py_compile.compile(py_path, doraise=True)
            compiled += 1
        except py_compile.PyCompileError as e:
            print(f"  [FAIL] {os.path.basename(py_path)}: {e}")
            failed += 1

    print(f"  Compiled: {compiled}, Failed: {failed}")

    if failed > 0:
        return False

    # Move .pyc from __pycache__ to same dir as .py
    for root, dirs, files in os.walk(pkg):
        pycache = os.path.join(root, "__pycache__")
        if os.path.isdir(pycache):
            for f in os.listdir(pycache):
                if f.endswith(".pyc"):
                    src = os.path.join(pycache, f)
                    # Format: module.cpython-312.pyc -> module.pyc
                    dst_name = f.split(".")[0] + ".pyc"
                    dst = os.path.join(root, dst_name)
                    shutil.copy2(src, dst)
                    print(f"  [PYC] {dst_name}")

    # Remove __pycache__ directories
    for root, dirs, files in os.walk(pkg):
        for d in list(dirs):
            if d == "__pycache__":
                shutil.rmtree(os.path.join(root, d))

    # Strip absolute paths from .pyc files
    print("  [STRIP] Removing absolute paths from .pyc headers...")
    strip_pyc_paths(pkg)

    # Remove .py source files (keep __init__.py)
    for root, dirs, files in os.walk(pkg):
        for f in files:
            if f.endswith(".py") and f != "__init__.py":
                os.remove(os.path.join(root, f))

    # Count .pyc files
    pyc_count = 0
    for root, dirs, files in os.walk(pkg):
        for f in files:
            if f.endswith(".pyc"):
                pyc_count += 1

    print(f"  [OK] {pyc_count} .pyc files, .py sources removed (except __init__.py)")
    return True


def verify():
    print("\n[4/6] Verifying...")
    # Check no .py files remain (except __init__.py)
    py_count = 0
    for root, dirs, files in os.walk(OUT_DIR):
        for f in files:
            if f.endswith(".py") and f != "__init__.py":
                py_count += 1
    if py_count > 0:
        print(f"  [WARN] {py_count} .py files remain (excluding __init__.py)!")
    else:
        print("  [OK] No .py source files (except __init__.py)")

    # Check __init__.py exists
    init = os.path.join(OUT_DIR, "__init__.py")
    if os.path.exists(init):
        print(f"  [OK] __init__.py ({os.path.getsize(init)} bytes)")
    else:
        print("  [FAIL] __init__.py missing!")

    # Count modules
    pyc_total = 0
    for root, dirs, files in os.walk(OUT_DIR):
        for f in files:
            if f.endswith(".pyc"):
                pyc_total += 1
    print(f"  [OK] {pyc_total} compiled modules")

    if os.path.exists(os.path.join(HERE, "pyproject.toml")):
        print("  [OK] pyproject.toml")

    return True


def build_wheel():
    print("\n[5/6] Building wheel...")
    dist_dir = os.path.join(HERE, "dist")
    if os.path.exists(dist_dir):
        shutil.rmtree(dist_dir)

    result = subprocess.run(
        [PYTHON, "-m", "build", "--wheel", "--no-isolation"],
        cwd=HERE, capture_output=True, text=True, env={**os.environ}
    )
    if result.stdout:
        for line in result.stdout.splitlines():
            if any(kw in line.lower() for kw in ("error", "built", "success")):
                print(f"  {line}")
    if result.returncode != 0:
        print(f"  [FAIL] {result.stderr}")
        return False

    for f in sorted(glob.glob(os.path.join(dist_dir, "*"))):
        size_kb = os.path.getsize(f) / 1024
        print(f"  [OUT] {os.path.basename(f)} ({size_kb:.0f} KB)")
    return True


def main():
    print(f"Correctover SDK v{VERSION} - Build from {NB_DIR}")
    print(f"  Python: {PYTHON}")
    print(f"  NB_DIR: {NB_DIR}")
    copy_and_rename()
    create_pyproject()
    create_license()
    create_readme()
    if compile_all() and verify():
        if build_wheel():
            print(f"\nBuild SUCCESS! (v{VERSION})")
            return
    print("\nBuild FAILED")
    sys.exit(1)


if __name__ == "__main__":
    main()
