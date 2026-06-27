#!/usr/bin/env python3
# PYTHONIOENCODING=utf-8
"""Build correctover SDK v1.0.2 wheel from copied sources."""
import os, sys, shutil, py_compile, subprocess, glob

HERE = r"C:\d\workspace\correctover-sdk"
OUT_DIR = os.path.join(HERE, "correctover")

def main():
    # Step 1: Create metadata
    print("[1/4] Creating metadata...")
    with open(os.path.join(HERE, "pyproject.toml"), "w", encoding="utf-8") as f:
        f.write('[build-system]\n')
        f.write('requires = ["setuptools>=64,<75"]\n')
        f.write('build-backend = "setuptools.build_meta"\n')
        f.write('\n[project]\n')
        f.write('name = "correctover"\n')
        f.write('version = "1.1.0"\n')
        f.write('description = "Correctover \\u2014 Protocol-level contract validation with automatic verified failover for LLM APIs."\n')
        f.write('readme = "README.md"\n')
        f.write('requires-python = ">=3.8"\n')
        f.write('license = {text = "Proprietary Commercial License"}\n')
        f.write('keywords = ["llm","self-healing","failover","circuit-breaker","api-resilience"]\n')
        f.write('authors = [{name = "Correctover Team", email = "team@correctover.com"}]\n')
        f.write('classifiers = ["Development Status :: 5 - Production/Stable","Intended Audience :: Developers","License :: Other/Proprietary License","Operating System :: OS Independent","Programming Language :: Python :: 3","Programming Language :: Python :: 3.8"]\n')
        f.write('dependencies = ["httpx>=0.24.0","aiohttp>=3.8.0"]\n')
        f.write('\n[tool.setuptools.packages.find]\n')
        f.write('include = ["correctover*"]\n')
        f.write('\n[tool.setuptools.package-data]\n')
        f.write('correctover = ["*.pyc"]\n')

    with open(os.path.join(HERE, "LICENSE"), "w", encoding="utf-8") as f:
        f.write("PROPRIETARY COMMERCIAL LICENSE\nCopyright (c) 2024-2026 Correctover Team. All rights reserved.\nThis software is NOT open source.\n")

    with open(os.path.join(HERE, "README.md"), "w", encoding="utf-8") as f:
        f.write("# Correctover SDK v1.0.2\n\nClosed-source compiled package. See https://correctover.com\n")

    print("  Metadata OK")

    # Step 2: Compile .py -> .pyc
    print("\n[2/4] Compiling .py -> .pyc...")
    all_py = []
    for root, dirs, fnames in os.walk(OUT_DIR):
        for fn in fnames:
            if fn.endswith(".py"):
                all_py.append(os.path.join(root, fn))

    ok, fail = 0, 0
    for py_path in all_py:
        try:
            py_compile.compile(py_path, doraise=True)
            ok += 1
        except py_compile.PyCompileError as e:
            fail += 1
            print(f"  FAIL: {os.path.basename(py_path)}: {e}")
    print(f"  Compiled: {ok}/{len(all_py)}")
    if fail:
        return False

    # Move .pyc from __pycache__ to module dir
    for root, dirs, fnames in os.walk(OUT_DIR):
        pycache = os.path.join(root, "__pycache__")
        if os.path.isdir(pycache):
            for fn in os.listdir(pycache):
                if fn.endswith(".pyc"):
                    dst_name = fn.split(".")[0] + ".pyc"
                    shutil.copy2(os.path.join(pycache, fn), os.path.join(root, dst_name))

    # Step 3: Remove .py sources (keep __init__.py)
    print("\n[3/4] Removing .py sources...")
    removed = 0
    for root, dirs, fnames in os.walk(OUT_DIR):
        for fn in fnames:
            if fn.endswith(".py") and fn != "__init__.py":
                os.remove(os.path.join(root, fn))
                removed += 1

    # Remove __pycache__
    for root, dirs, fnames in os.walk(OUT_DIR):
        for d in dirs:
            if d == "__pycache__":
                shutil.rmtree(os.path.join(root, d))

    print(f"  Removed {removed} .py files")

    # Show packages
    for root, dirs, fnames in os.walk(OUT_DIR):
        for fn in fnames:
            if fn == "__init__.py" or fn.endswith(".pyc"):
                rel = os.path.relpath(os.path.join(root, fn), OUT_DIR)
                print(f"  {rel}")

    # Step 4: Build wheel
    print("\n[4/4] Building wheel...")
    dist = os.path.join(HERE, "dist")
    if os.path.exists(dist):
        shutil.rmtree(dist)

    result = subprocess.run(
        [sys.executable, "-m", "build", "--wheel"],
        cwd=HERE, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=120
    )
    if result.returncode != 0:
        print(f"  FAIL (stderr): {(result.stderr or '')[:1000]}")
        print(f"  FAIL (stdout): {(result.stdout or '')[:500]}")
        return False

    for line in (result.stdout or "").splitlines():
        print(f"  {line}")

    whls = sorted(glob.glob(os.path.join(dist, "*.whl")))
    for w in whls:
        kb = os.path.getsize(w) / 1024
        print(f"  OUT: {os.path.basename(w)} ({kb:.0f} KB)")

    if whls:
        print("\nBUILD SUCCESS!")
        # Register as the output for this task
        output_file = os.environ.get("TASK_OUTPUT")
        if output_file:
            with open(output_file, "w") as f:
                f.write(f"Wheel: {os.path.basename(whls[0])} ({os.path.getsize(whls[0]) / 1024:.0f} KB)\n")
                f.write(f"Path: {whls[0]}\n")
        return True
    return False

if __name__ == "__main__":
    sys.exit(0 if main() else 1)
