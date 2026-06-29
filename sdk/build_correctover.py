#!/usr/bin/env python3
# PYTHONIOENCODING=utf-8
"""Build correctover SDK from its own source files.

Builds from sdk/correctover/ (already namespace-replaced, tracked in git)
using a temp directory to preserve the original source.

Usage:
  python build_correctover.py                              # default
  python build_correctover.py --python py -3.12            # custom Python path
  python build_correctover.py --version 1.3.0              # override version

Environment:
  CORRECTOVER_VERSION    Override version string
"""
import os, sys, shutil, py_compile, subprocess, glob, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))

# ── CLI ──────────────────────────────────────────────────────────────
import argparse
parser = argparse.ArgumentParser(description="Build correctover SDK")
parser.add_argument("--python", default=sys.executable,
                    help="Python interpreter to use for compilation & build")
parser.add_argument("--version", default=None,
                    help="SDK version string (default: 1.3.0, overrides CORRECTOVER_VERSION env)")
args = parser.parse_args()

VERSION = (args.version
           or os.environ.get("CORRECTOVER_VERSION")
           or "1.3.0")
PYTHON = args.python

SRC_PKG = os.path.join(HERE, "correctover")
TMPDIR = tempfile.mkdtemp(prefix="correctover-build-")
TMP_PKG = os.path.join(TMPDIR, "correctover")
DIST_DIR = os.path.join(HERE, "dist")

print(f"Correctover SDK v{VERSION}")
print(f"  Source: {SRC_PKG}")
print(f"  Temp:   {TMPDIR}")
print(f"  Python: {PYTHON}")
print()


def copy_source():
    print("[1/5] Copying source files...")
    if not os.path.isdir(SRC_PKG):
        print(f"  [FAIL] Source not found: {SRC_PKG}")
        sys.exit(1)

    os.makedirs(TMP_PKG, exist_ok=True)
    for item in os.listdir(SRC_PKG):
        src = os.path.join(SRC_PKG, item)
        dst = os.path.join(TMP_PKG, item)
        if item == "__pycache__":
            continue
        if os.path.isdir(src):
            shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__"))
        else:
            shutil.copy2(src, dst)
    print(f"  [COPY] Source copied to {TMP_PKG}")

    # Remove __pycache__ dirs from temp
    for root, dirs, files in os.walk(TMP_PKG):
        if "__pycache__" in root:
            shutil.rmtree(root)


def override_version():
    print("\n[2/5] Overriding _version.py...")
    ver_path = os.path.join(TMP_PKG, "_version.py")
    with open(ver_path, "w", encoding="utf-8") as f:
        f.write(f'# Copyright 2024-2026 Correctover Team\n'
                f'# Proprietary Commercial License\n'
                f'"""Version info for Correctover SDK."""\n'
                f'__version__ = "{VERSION}"\n'
                f'version = __version__\n')
    print(f"  [OVERRIDE] _version.py (v{VERSION})")


def compile_all():
    print("\n[3/5] Compiling .py -> .pyc...")
    compiled = failed = 0

    for root, dirs, files in os.walk(TMP_PKG):
        for f in files:
            if not f.endswith(".py") or f == "__init__.py":
                continue
            path = os.path.join(root, f)
            try:
                py_compile.compile(path, doraise=True)
                compiled += 1
            except py_compile.PyCompileError as e:
                print(f"  [FAIL] {f}: {e}")
                failed += 1

    print(f"  Compiled: {compiled}, Failed: {failed}")
    if failed > 0:
        return False

    # Move .pyc from __pycache__
    for root, dirs, files in os.walk(TMP_PKG):
        pycache = os.path.join(root, "__pycache__")
        if os.path.isdir(pycache):
            for f in os.listdir(pycache):
                if f.endswith(".pyc"):
                    name = f.split(".")[0] + ".pyc"
                    shutil.copy2(os.path.join(pycache, f), os.path.join(root, name))
            shutil.rmtree(pycache)
    print("  [OK]  .pyc files moved from __pycache__")

    # Strip absolute paths from .pyc
    print("  [STRIP] Removing absolute paths from .pyc...")
    import marshal, struct

    def _strip_code(obj, visited=None):
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
                c = _strip_code(c, visited)
            new_consts.append(c)
        if new_consts != list(obj.co_consts):
            obj = obj.replace(co_consts=tuple(new_consts))
        return obj

    for root, dirs, files in os.walk(TMP_PKG):
        for fn in files:
            if not fn.endswith(".pyc"):
                continue
            fpath = os.path.join(root, fn)
            with open(fpath, "rb") as fh:
                data = fh.read()
            flags = struct.unpack("<I", data[4:8])[0]
            header = 16
            try:
                code = marshal.loads(data[header:])
            except Exception:
                continue
            code = _strip_code(code)
            with open(fpath, "wb") as fh:
                fh.write(data[:header] + marshal.dumps(code))

    return True


def finalize():
    print("\n[4/5] Finalizing package (removing .py, keeping __init__.py)...")
    for root, dirs, files in os.walk(TMP_PKG):
        for f in files:
            if f.endswith(".py") and f != "__init__.py":
                os.remove(os.path.join(root, f))

    pyc_count = sum(1 for _, _, fs in os.walk(TMP_PKG) for f in fs if f.endswith(".pyc"))
    init_exists = os.path.exists(os.path.join(TMP_PKG, "__init__.py"))
    print(f"  [OK]  {pyc_count} compiled modules, __init__.py present: {init_exists}")


def build_wheel():
    print("\n[5/5] Building wheel...")
    if os.path.exists(DIST_DIR):
        shutil.rmtree(DIST_DIR)

    # Create build config files
    project = f"""[build-system]
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

    with open(os.path.join(TMPDIR, "pyproject.toml"), "w", encoding="utf-8") as f:
        f.write(project)
    with open(os.path.join(TMPDIR, "README.md"), "w") as f:
        f.write("# Correctover SDK\n\n**Failure is not fatal.** Protocol-level contract validation with automatic verified failover for LLM APIs.\n\n## Install\n\n```bash\npip install correctover\n```\n\n## License\n\nProprietary Commercial License. See LICENSE file.\n")
    with open(os.path.join(TMPDIR, "LICENSE"), "w") as f:
        f.write(f"CORRECTOVER SDK — PROPRIETARY COMMERCIAL LICENSE\nCopyright (c) 2024-2026 Correctover Team. All rights reserved.\n\nThis software is NOT open source. It is distributed as compiled bytecode only. Redistribution requires a valid commercial license.\n")

    result = subprocess.run(
        [PYTHON, "-m", "build", "--wheel", "--no-isolation"],
        cwd=TMPDIR, capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"  [FAIL] {result.stderr}")
        print(result.stdout)
        return False

    for line in result.stdout.splitlines():
        if any(kw in line.lower() for kw in ("error", "built", "copying")):
            print(f"  {line}")

    os.makedirs(DIST_DIR, exist_ok=True)
    build_dist = os.path.join(TMPDIR, "dist")
    for f in glob.glob(os.path.join(build_dist, "*.whl")):
        shutil.copy2(f, os.path.join(DIST_DIR, os.path.basename(f)))
        size_kb = os.path.getsize(f) / 1024
        print(f"  [OUT] {os.path.basename(f)} ({size_kb:.0f} KB)")
    return True


def main():
    copy_source()
    override_version()
    if compile_all():
        finalize()
        if build_wheel():
            print(f"\n=== BUILD SUCCESS v{VERSION} ===")
            return
    print("\n=== BUILD FAILED ===")
    sys.exit(1)


if __name__ == "__main__":
    main()
