#!/usr/bin/env bash
# 一键安装 git hooks（每个 dev 新克隆仓库后跑一次）。
#
# 用法：bash scripts/install_hooks.sh
set -e

REPO_ROOT="$(git rev-parse --show-toplevel)"
HOOK_DIR="$REPO_ROOT/.git/hooks"
SRC_DIR="$REPO_ROOT/hooks"

if [ ! -d "$SRC_DIR" ]; then
  echo "❌ 没找到 hooks/ 目录"
  exit 1
fi

mkdir -p "$HOOK_DIR"

for src in "$SRC_DIR"/*; do
  name=$(basename "$src")
  target="$HOOK_DIR/$name"
  cp "$src" "$target"
  chmod +x "$target"
  echo "  installed: $target"
done

echo ""
echo "✅ git hooks 已安装"
echo "   pre-commit 会在每次 git commit 前跑 scripts/check_compliance.py --staged"
