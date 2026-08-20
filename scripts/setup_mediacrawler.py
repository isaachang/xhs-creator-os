#!/usr/bin/env python3
"""Install or inspect the optional local MediaCrawler adapter for Creator OS.

The script intentionally never reads API keys or browser cookies.  ``--install``
is explicit because it downloads third-party code and Python/browser
dependencies.  A successful install still requires the user to complete one
Xiaohongshu/Rednote QR login when prompted by ``xhs_provider.py media-auth``.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


SKILL_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = SKILL_ROOT.parent
DEFAULT_MEDIA_ROOT = WORKSPACE_ROOT / "MediaCrawler"
UPSTREAM_REPOSITORY = "https://github.com/NanmiCoder/MediaCrawler.git"
UPSTREAM_BASE_COMMIT = "d6f7c5bb906b6dac40ddf343ef9e26438a3de092"
ADAPTER_PATCH = SKILL_ROOT / "third_party" / "mediacrawler" / "creator-os-adapter.patch"
REQUIRED_ADAPTER_FILES = (
    "media_platform/xhs/creator_os_output.py",
    "media_platform/xhs/site.py",
)


class SetupError(RuntimeError):
    pass


def configured_media_root(value: str | None) -> Path:
    raw = (value or os.environ.get("MEDIA_CRAWLER_ROOT", "")).strip()
    return Path(raw).expanduser() if raw else DEFAULT_MEDIA_ROOT


def media_python(root: Path) -> Path:
    return root / ".venv" / "bin" / "python"


def adapter_ready(root: Path) -> bool:
    return all((root / relative).is_file() for relative in REQUIRED_ADAPTER_FILES)


def run(command: list[str], *, cwd: Path | None = None) -> None:
    result = subprocess.run(command, cwd=cwd, text=True, check=False)
    if result.returncode:
        joined = " ".join(command[:3])
        raise SetupError(f"命令执行失败：{joined}")


def git_head(root: Path) -> str:
    if not root.is_dir():
        return ""
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True, capture_output=True, check=False
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def check(root: Path) -> dict[str, Any]:
    python_ready = sys.version_info >= (3, 11)
    node_ready = shutil.which("node") is not None
    return {
        "skill_root": str(SKILL_ROOT),
        "media_root": str(root),
        "python": {"version": sys.version.split()[0], "supported": python_ready},
        "git": {"installed": shutil.which("git") is not None},
        "node": {"installed": node_ready, "note": "MediaCrawler 的 XHS 运行环境建议 Node.js 16+"},
        "media": {
            "source_present": (root / "main.py").is_file(),
            "environment_present": media_python(root).is_file(),
            "creator_os_adapter_present": adapter_ready(root),
            "git_head": git_head(root),
        },
        "next_action": (
            "运行 setup_mediacrawler.py --install；完成后由 Codex 执行 media-auth 并展示二维码。"
            if not ((root / "main.py").is_file() and media_python(root).is_file() and adapter_ready(root))
            else "Media 已就绪；运行 xhs_provider.py media-auth 检查登录态。"
        ),
    }


def ensure_python() -> None:
    if sys.version_info < (3, 11):
        raise SetupError("MediaCrawler 需要 Python 3.11 或更新版本；请先让 Codex 安装或选择合适的 Python。")
    if not shutil.which("git"):
        raise SetupError("未找到 git；请先安装 Git 后重试。")


def clone_if_missing(root: Path) -> None:
    if root.exists():
        if not (root / "main.py").is_file():
            raise SetupError(f"MediaCrawler 路径已存在但不是有效目录：{root}")
        return
    root.parent.mkdir(parents=True, exist_ok=True)
    run(["git", "clone", UPSTREAM_REPOSITORY, str(root)])
    run(["git", "checkout", UPSTREAM_BASE_COMMIT], cwd=root)


def apply_adapter(root: Path) -> None:
    if adapter_ready(root):
        return
    if not ADAPTER_PATCH.is_file():
        raise SetupError("缺少 MediaCrawler 适配补丁；请重新下载完整 Creator OS 仓库。")
    if git_head(root) != UPSTREAM_BASE_COMMIT:
        raise SetupError(
            "当前 MediaCrawler 版本与首测适配补丁不匹配。请使用初始化脚本新建目录，"
            "或将 MEDIA_CRAWLER_ROOT 指向一个干净的兼容副本。"
        )
    run(["git", "apply", "--check", str(ADAPTER_PATCH)], cwd=root)
    run(["git", "apply", str(ADAPTER_PATCH)], cwd=root)


def install_environment(root: Path) -> None:
    executable = media_python(root)
    if not executable.is_file():
        run([sys.executable, "-m", "venv", ".venv"], cwd=root)
    run([str(executable), "-m", "pip", "install", "--upgrade", "pip"], cwd=root)
    run([str(executable), "-m", "pip", "install", "-e", "."], cwd=root)
    run([str(executable), "-m", "playwright", "install", "chromium"], cwd=root)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="只输出当前配置状态，不下载或修改文件")
    parser.add_argument("--install", action="store_true", help="下载上游 MediaCrawler、应用适配补丁并安装本机依赖")
    parser.add_argument("--media-root", help="可选：MediaCrawler 目录；默认与 Creator OS 同级")
    args = parser.parse_args()
    root = configured_media_root(args.media_root)

    try:
        if args.check or not args.install:
            print(json.dumps(check(root), ensure_ascii=False, indent=2))
            return 0

        ensure_python()
        clone_if_missing(root)
        apply_adapter(root)
        install_environment(root)
        print(json.dumps(check(root), ensure_ascii=False, indent=2))
        print("\n下一步：运行 python3 scripts/xhs_provider.py media-auth --qr-output runs/latest/media-login-qr.png")
        return 0
    except SetupError as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
