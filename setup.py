from setuptools import setup, find_packages

setup(
    name="lspcmd",
    version="0.1.0",
    description="Command-line wrapper around LSP language servers",
    packages=find_packages(),
    python_requires=">=3.11",
    install_requires=[
        "click>=8.0",
        "pydantic>=2.0",
        "tomli>=2.0",
        "tomli-w>=1.0",
    ],
    extras_require={
        "test": [
            "pytest>=7.0",
            "pytest-asyncio>=0.21",
            "pytest-xdist>=3.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "lspcmd=lspcmd.cli:cli",
            "lspcmd-daemon=lspcmd.daemon_cli:main",
        ],
    },
)
