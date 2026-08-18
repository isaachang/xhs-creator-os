#!/usr/bin/env python3
"""Persist the Apify token locally without echoing or exposing its value."""

from __future__ import annotations

import getpass
import os
import subprocess
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = SKILL_ROOT / ".env.local"
KEYCHAIN_SERVICE = "xhs-creator-os/apify-api-token"


def read_keychain() -> str:
    try:
        result = subprocess.run(
            ["/usr/bin/security", "find-generic-password", "-a", getpass.getuser(), "-s", KEYCHAIN_SERVICE, "-w"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def usable_secret(value: str) -> bool:
    lowered = value.strip().lower()
    return bool(lowered) and not any(char.isspace() for char in value) and not lowered.startswith(("security", "error", "warning"))


def main() -> int:
    token = read_keychain()
    if not usable_secret(token):
        token = getpass.getpass("Apify API key (hidden): ").strip()
    if not usable_secret(token):
        print("No valid API key supplied.")
        return 1

    ENV_FILE.write_text(
        "# Local secret. Do not commit or share this file.\n"
        f"APIFY_API_TOKEN={token}\n",
        encoding="utf-8",
    )
    os.chmod(ENV_FILE, 0o600)
    print("Apify API key saved to the local ignored secret file.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
