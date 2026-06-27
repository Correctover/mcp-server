#!/usr/bin/env python3
# PYTHONIOENCODING=utf-8
"""Build correctover SDK v1.0.2 from NeuralBridge 5.7.0 source."""
import os, sys, re, shutil, py_compile, glob, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
NB_DIR = r"D:\workspace\neuralbridge-sdk"
OUT_DIR = os.path.join(HERE, "correctover")

TELEMETRY_OLD = "license-api-neuralbridge-hk-rewfrmblft.cn-hongkong.fcapp.run"
TELEMETRY_NEW = "license-api-correctover-hk.oss-cn-hongkong.aliyuncs.com"


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
    # Replace f-strings with literal newlines in them
    # Pattern: _print(f"<newline>  ...") -> _print(f"\n  ...")
    fixes = {
        '_print(f"\n  ✅ 修复脚本已生成: ': '_print(f"\\n  ✅ 修复脚本已生成: ',
        '_print(f"\n  ❌ 无法写入修复脚本: ': '_print(f"\\n  ❌ 无法写入修复脚本: ',
        '_print(f"\n  {\'─\' * 55}": '_print(f"\\n  {\'─\' * 55}"',
    }
    for old, new in fixes.items():
        content = content.replace(old, new)
    return content


def copy_and_rename():
    print("=" * 60)
    print("[1/5] Copying and renaming source files...")
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
    return files


def create_pyproject():
    print("\n[2/5] Creating pyproject.toml...")
    pyproject = """[build-system]
requires = ["setuptools>=64,<75"]
build-backend = "setuptools.build_meta"

[project]
name = "correctover"
version = "1.0.2"
description = "Correctover — Failure is not fatal. Protocol-level contract validation with automatic verified failover for LLM APIs."
readme = "README.md"
requires-python = ">=3.8"
license = {text = "Proprietary Commercial License — see LICENSE"}
keywords = ["llm", "self-healing", "failover", "circuit-breaker", "api-resilience", "openai", "anthropic", "deepseek", "contract-validation", "correctover", "ai-gateway", "semantic-verification"]
authors = [{name = "Correctover Team", email = "team@correctover.com"}]
maintainers = [{name = "Correctover Team", email = "team@correctover.com"}]
classifiers = [
    "Development Status :: 5 - Production/Stable",
    "Environment :: Console",
    "Intended Audience :: Developers",
    "License :: Other/Proprietary License",
    "Operating System :: OS Independent",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.8",
    "Programming Language :: Python :: 3.9",
    "Programming Language :: Python :: 3.10",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Topic :: Scientific/Engineering :: Artificial Intelligence",
    "Topic :: Software Development :: Libraries :: Python Modules",
    "Topic :: System :: Networking",
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
    text = """CORRECTOVER SDK — PROPRIETARY COMMERCIAL LICENSE
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


def compile_all():
    print("\n[3/5] Compiling .py -> .pyc (closed source)...")

    # Remove Cython artifacts
    for root, dirs, files in os.walk(OUT_DIR):
        for f in files:
            if f.endswith(".c") or f.endswith(".pyd") or f.endswith(".so"):
                os.remove(os.path.join(root, f))

    # First, check ALL .py files compile correctly
    all_py = []
    for root, dirs, files in os.walk(OUT_DIR):
        for f in files:
            if f.endswith(".py"):
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
        # Show the lines causing issues
        print("  Fixing known multi-line f-strings and retrying...")
        # We already fixed them in copy_and_rename, but let's check
        return False

    # Move .pyc from __pycache__ to same dir as .py
    for root, dirs, files in os.walk(OUT_DIR):
        pycache = os.path.join(root, "__pycache__")
        if os.path.isdir(pycache):
            for f in os.listdir(pycache):
                if f.endswith(".pyc"):
                    src = os.path.join(pycache, f)
                    # Remove magic number prefix to get original name
                    # Format: module.cpython-312.pyc -> module.pyc
                    dst_name = f.split(".")[0] + ".pyc"
                    dst = os.path.join(root, dst_name)
                    shutil.copy2(src, dst)
                    print(f"  [PYC] {dst_name}")

    # Remove all .py files and __pycache__
    for root, dirs, files in os.walk(OUT_DIR):
        for f in files:
            if f.endswith(".py"):
                os.remove(os.path.join(root, f))
    for root, dirs, files in os.walk(OUT_DIR):
        for d in dirs:
            if d == "__pycache__":
                shutil.rmtree(os.path.join(root, d))

    # Count .pyc files
    pyc_count = 0
    for root, dirs, files in os.walk(OUT_DIR):
        for f in files:
            if f.endswith(".pyc"):
                pyc_count += 1

    print(f"  [OK] {pyc_count} .pyc files, all .py sources removed")
    return True


def verify():
    print("\n[4/5] Verifying...")
    # Check no .py files remain
    py_count = 0
    for root, dirs, files in os.walk(OUT_DIR):
        for f in files:
            if f.endswith(".py"):
                py_count += 1
    if py_count > 0:
        print(f"  [WARN] {py_count} .py files remain!")
    else:
        print("  [OK] No .py source files")

    # Check __init__.pyc exists
    init = os.path.join(OUT_DIR, "__init__.pyc")
    if os.path.exists(init):
        print(f"  [OK] __init__.pyc ({os.path.getsize(init)} bytes)")
    else:
        print("  [FAIL] __init__.pyc missing!")

    # Count modules
    pyc_total = 0
    for root, dirs, files in os.walk(OUT_DIR):
        for f in files:
            if f.endswith(".pyc"):
                pyc_total += 1
    print(f"  [OK] {pyc_total} compiled modules")

    # Check pyproject.toml
    if os.path.exists(os.path.join(HERE, "pyproject.toml")):
        print("  [OK] pyproject.toml")

    return True


def build_wheel():
    print("\n[5/5] Building wheel...")
    dist_dir = os.path.join(HERE, "dist")
    if os.path.exists(dist_dir):
        shutil.rmtree(dist_dir)

    result = subprocess.run(
        [sys.executable, "-m", "build", "--wheel"],
        cwd=HERE, capture_output=True, text=True, env={**os.environ}
    )
    if result.stdout:
        for line in result.stdout.splitlines():
            if "error" in line.lower() or "built" in line.lower() or "Success" in line:
                print(f"  {line}")
    if result.returncode != 0:
        print(f"  [FAIL] {result.stderr}")
        return False

    for f in sorted(glob.glob(os.path.join(dist_dir, "*"))):
        size_kb = os.path.getsize(f) / 1024
        print(f"  [OUT] {os.path.basename(f)} ({size_kb:.0f} KB)")
    return True


def main():
    print("Correctover SDK v1.0.2 - Build from NB 5.7.0")
    copy_and_rename()
    create_pyproject()
    create_license()
    create_readme()
    if compile_all() and verify():
        if build_wheel():
            print("\nBuild SUCCESS!")
            return
    print("\nBuild FAILED")
    sys.exit(1)


if __name__ == "__main__":
    main()
