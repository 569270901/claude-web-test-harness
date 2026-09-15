#!/usr/bin/env python3
"""项目红线静态扫描。

读 configs/compliance-rules.json 跑规则，扫违规打印到 stderr。
exit code: 0 = 全过 / 有 warn 无 error；1 = 有 error。

用法：
  python scripts/check_compliance.py                  # 扫全仓
  python scripts/check_compliance.py --staged         # 只扫 git staged 的文件（pre-commit hook 用）
  python scripts/check_compliance.py --no-warn        # 只显示 error，warn 静默
"""
import argparse
import json
import re
import subprocess
import sys
from fnmatch import fnmatch
from glob import glob
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_rules() -> dict:
    return json.loads((ROOT / "configs/compliance-rules.json").read_text())


def staged_files() -> set:
    """返回 git index 中已 staged 的文件（pre-commit hook 用）。"""
    try:
        out = subprocess.check_output(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
            cwd=str(ROOT),
        ).decode()
    except subprocess.CalledProcessError:
        return set()
    return {ROOT / f for f in out.strip().splitlines() if f}


def matches_any_glob(path: Path, globs: list) -> bool:
    rel = str(path.relative_to(ROOT))
    return any(fnmatch(rel, g) for g in globs)


def check_pattern_rule(rule: dict, only_paths: set | None) -> list:
    """通用正则规则。

    - rule.pattern: 必须包含的正则
    - rule.context (可选): 该行还必须包含此关键词，否则跳过（用于把规则限定在 xpath= 这种上下文）
    - rule.exempt_pattern (可选): 行内匹配则放过
    """
    pat = re.compile(rule["pattern"])
    exempt = re.compile(rule["exempt_pattern"]) if rule.get("exempt_pattern") else None
    ctx = rule.get("context")
    rule_name = rule["name"]
    violations = []

    candidates = []
    for g in rule["globs"]:
        candidates.extend(ROOT.glob(g))

    for path in candidates:
        if not path.is_file():
            continue
        if only_paths is not None and path not in only_paths:
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, line in enumerate(lines, 1):
            # 行内 noqa 豁免
            if f"rules-allow: {rule_name}" in line:
                continue
            if ctx and ctx not in line:
                continue
            if not pat.search(line):
                continue
            if exempt and exempt.search(line):
                continue
            violations.append({
                "rule": rule_name,
                "level": rule["level"],
                "file": str(path.relative_to(ROOT)),
                "line": lineno,
                "content": line.strip()[:140],
                "reason": rule["reason"],
            })
    return violations


def check_path_rule(rule: dict, only_paths: set | None) -> list:
    """路径检查（禁止某些路径出现文件）。"""
    rule_name = rule["name"]
    violations = []
    forbidden = rule.get("forbidden_glob", [])
    for g in forbidden:
        for path in ROOT.glob(g):
            if not path.is_file():
                continue
            if only_paths is not None and path not in only_paths:
                continue
            violations.append({
                "rule": rule_name,
                "level": rule["level"],
                "file": str(path.relative_to(ROOT)),
                "line": 0,
                "content": "(file path violation)",
                "reason": rule["reason"],
            })
    return violations


def render(violations: list, show_warn: bool) -> int:
    errors = [v for v in violations if v["level"] == "error"]
    warns = [v for v in violations if v["level"] == "warn"]

    if errors:
        print(f"\n❌ {len(errors)} ERROR(S):", file=sys.stderr)
        for v in errors:
            print(f"  {v['file']}:{v['line']} [{v['rule']}]", file=sys.stderr)
            if v["content"] and v["content"] != "(file path violation)":
                print(f"    >> {v['content']}", file=sys.stderr)
            print(f"    → {v['reason']}", file=sys.stderr)

    if warns and show_warn:
        print(f"\n⚠️  {len(warns)} WARNING(S):", file=sys.stderr)
        for v in warns:
            print(f"  {v['file']}:{v['line']} [{v['rule']}]", file=sys.stderr)
            if v["content"]:
                print(f"    >> {v['content']}", file=sys.stderr)
            print(f"    → {v['reason']}", file=sys.stderr)

    print(
        f"\n=== 合规检查: {len(errors)} error / {len(warns)} warn ===",
        file=sys.stderr,
    )

    if not errors and not warns:
        print("✅ All compliance checks passed.", file=sys.stderr)

    return 1 if errors else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--staged", action="store_true", help="只扫 git staged 文件")
    ap.add_argument("--no-warn", action="store_true", help="只显示 error")
    args = ap.parse_args()

    only_paths = staged_files() if args.staged else None
    if args.staged and not only_paths:
        print("(no staged files)", file=sys.stderr)
        return 0

    rules = load_rules()["rules"]
    all_violations = []
    for rule in rules:
        if rule.get("type") == "path_check":
            all_violations.extend(check_path_rule(rule, only_paths))
        else:
            all_violations.extend(check_pattern_rule(rule, only_paths))

    return render(all_violations, show_warn=not args.no_warn)


if __name__ == "__main__":
    sys.exit(main())
