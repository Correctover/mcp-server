#!/usr/bin/env python3
"""Setup for correctover SDK v1.0.2 (compiled .pyc distribution)."""
from setuptools import setup, find_packages

setup(
    name="correctover",
    version="1.2.0",
    description="Correctover - Protocol-level contract validation with automatic verified failover for LLM APIs.",
    long_description="Closed-source compiled package. See https://correctover.com",
    long_description_content_type="text/markdown",
    author="Correctover Team",
    author_email="team@correctover.com",
    url="https://correctover.com",
    packages=find_packages() + ["correctover.benchmark"],
    package_data={
        "correctover": ["*.pyc"],
        "correctover.benchmark": ["*.pyc"],
    },
    include_package_data=True,
    python_requires=">=3.12",
    install_requires=[
        "httpx>=0.24.0",
        "aiohttp>=3.8.0",
    ],
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Intended Audience :: Developers",
        "License :: Other/Proprietary License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.12",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
    ],
    entry_points={
        "console_scripts": [
            "correctover-shield=correctover.shield:main",
        ],
    },
    license="Proprietary Commercial License",
)
