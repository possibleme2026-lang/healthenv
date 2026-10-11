"""Structural parity guard for README.md and README.zh-CN.md."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EN = ROOT / "README.md"
ZH = ROOT / "README.zh-CN.md"

_HEADING = re.compile(r"^(#{1,6})\s+", re.MULTILINE)
_FENCE = re.compile(r"^```", re.MULTILINE)
_LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
_TABLE = re.compile(r"^\|.*\|\s*$", re.MULTILINE)
_BASH = re.compile(r"```bash\n(.*?)\n```", re.DOTALL)


def _heading_shape(text: str) -> list[int]:
    return [len(match.group(1)) for match in _HEADING.finditer(text)]


def _commands(text: str) -> list[str]:
    commands: list[str] = []
    for block in _BASH.findall(text):
        for line in block.splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                commands.append(stripped)
    return commands


def _relative_links(text: str) -> Counter[str]:
    links: Counter[str] = Counter()
    for target in _LINK.findall(text):
        clean = target.split("#", 1)[0]
        if not clean or "://" in clean or clean.startswith("mailto:"):
            continue
        if clean in {"README.md", "README.zh-CN.md"}:
            continue
        links[clean] += 1
    return links


def validate_texts(en: str, zh: str) -> list[str]:
    errors: list[str] = []
    if _heading_shape(en) != _heading_shape(zh):
        errors.append("heading level structure differs")
    if len(_FENCE.findall(en)) != len(_FENCE.findall(zh)):
        errors.append("code fence count differs")
    if len(_TABLE.findall(en)) != len(_TABLE.findall(zh)):
        errors.append("table row count differs")
    if _commands(en) != _commands(zh):
        errors.append("bash command blocks differ")
    if _relative_links(en) != _relative_links(zh):
        errors.append("relative link counts differ")
    if "README.zh-CN.md" not in en or "README.md" not in zh:
        errors.append("language switch links are missing")
    if "\ufffd" in en or "\ufffd" in zh:
        errors.append("replacement character U+FFFD detected")
    return errors


def validate_files() -> list[str]:
    en = EN.read_text(encoding="utf-8")
    zh = ZH.read_text(encoding="utf-8")
    errors = validate_texts(en, zh)
    for text, label in ((en, "README.md"), (zh, "README.zh-CN.md")):
        for target in _relative_links(text):
            path = ROOT / target
            if not path.exists():
                errors.append(f"{label}: dead relative link {target}")
    return errors


def main() -> int:
    errors = validate_files()
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("README i18n parity: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
