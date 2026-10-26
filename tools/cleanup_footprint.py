# -*- coding: utf-8 -*-
"""按数据足迹台账精确清理用例残留（台账见 utils/footprint.py）。

原则：
- **只清理台账里登记过的对象**，按**完整名字精确匹配**；绝不按前缀 / 通配 / 模糊搜索批量删。
  被测系统里同前缀但名字不同的对象一律不碰——哪怕它看起来"也像测试数据"。
- **默认 dry-run**：只打印待清理清单，不做任何删除。
- **H 不知道被测系统怎么删**：真正的删除动作由调用方传入回调 `delete_fn(item) -> bool`。
  回调里定位对象时也要按完整名字精确匹配（可用 `find_exact()`），找到多个同名对象时宁可不删、
  返回 False 登记为 stuck，交给人看。
- 删除成功 → 台账记 deleted；回调返回 False / 抛异常 → 记 stuck（附原因），下次默认不再重试。

Python 用法（删除需要浏览器时，在自己的脚本里开浏览器、登录，然后调用 cleanup）：
    from utils.footprint import Footprint
    from tools.cleanup_footprint import cleanup, find_exact

    def delete_item(item):                 # item = {"name", "kind", "where", "ts", "source", ...}
        page.goto(f"{BASE}/items?search={...}")             # 搜索只是缩小范围，最终仍按完整名字比对
        rows = page.locator("tr.row").all_inner_texts()
        hits = find_exact([r.split("\\t")[0] for r in rows], item["name"])
        if len(hits) != 1:
            return False                   # 0 个 = 已不存在 / 1 个以上 = 有歧义，都不删
        ...点删除并确认...
        return True

    cleanup(Footprint(), delete_fn=delete_item, dry_run=False)

命令行：
    python tools/cleanup_footprint.py                         # dry-run，列出待清理对象
    python tools/cleanup_footprint.py --kind item --include-stuck
    python tools/cleanup_footprint.py --deleter mypkg.cleanup:delete_item --yes   # 真删（回调由你提供）
"""
import argparse
import importlib
import sys
from pathlib import Path
from typing import Callable, Iterable, Optional

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.footprint import Footprint  # noqa: E402

DeleteFn = Callable[[dict], Optional[bool]]


def find_exact(candidates: Iterable[str], name: str) -> list[str]:
    """从页面上读到的候选名字里，挑出与 name **完全相同**的（两端空白忽略，大小写敏感）。

    不做 startswith / in / 正则——"AUTO_X_1" 和 "AUTO_X_10" 是两个不同对象。
    """
    target = name.strip()
    return [c for c in candidates if c is not None and c.strip() == target]


def _fmt(item: dict) -> str:
    where = f" @ {item['where']}" if item.get("where") else ""
    src = f"  ← {item['source']}" if item.get("source") else ""
    why = f"  [删不掉：{item['why']}]" if item.get("why") else ""
    return f"  [{item.get('kind', 'object')}] {item['name']!r}{where}  建于 {item.get('ts', '?')}{src}{why}"


def cleanup(fp: Footprint, delete_fn: Optional[DeleteFn] = None, *, kind: Optional[str] = None,
            include_stuck: bool = False, dry_run: bool = True, out=print) -> dict:
    """列出 / 清理台账里的残留，返回 {"pending": [...], "deleted": [...], "stuck": [...]}。

    dry_run=True 或没给 delete_fn 时只打印，不调用任何删除。
    """
    items = fp.pending(kind)
    if include_stuck:
        items += fp.stuck_items(kind)
    result = {"pending": items, "deleted": [], "stuck": []}
    out(f"[cleanup] 台账 {fp.ledger}：待清理 {len(items)} 个（只按完整名字精确匹配）")
    for it in items:
        out(_fmt(it))
    if not items:
        return result
    if dry_run or delete_fn is None:
        out("[cleanup] dry-run：未执行任何删除。确认清单无误后由调用方传入删除回调并关闭 dry-run。")
        return result

    for it in items:
        name, k, where = it["name"], it.get("kind", "object"), it.get("where", "")
        try:
            ok = delete_fn(it)
            why = "" if ok else "删除回调返回 False（未找到唯一同名对象，或系统拒绝删除）"
        except Exception as e:  # noqa: BLE001 —— 单个对象失败不影响其余对象
            ok, why = False, f"{e.__class__.__name__}: {str(e)[:200]}"
        if ok:
            fp.deleted(name, kind=k, where=where, source="cleanup_footprint")
            result["deleted"].append(it)
            out(f"  ✓ 已删除 {name!r}")
        else:
            fp.stuck(name, kind=k, where=where, why=why, source="cleanup_footprint")
            result["stuck"].append(it)
            out(f"  ✗ 未删除 {name!r}：{why}")
    out(f"[cleanup] 完成：删除 {len(result['deleted'])} / 删不掉 {len(result['stuck'])}")
    return result


def _load_callable(spec: str) -> DeleteFn:
    mod, _, attr = spec.partition(":")
    if not attr:
        raise SystemExit(f"--deleter 格式应为 module.path:function，收到 {spec!r}")
    return getattr(importlib.import_module(mod), attr)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="按足迹台账精确清理用例残留（默认 dry-run）")
    ap.add_argument("--ledger", default=None, help="台账路径，默认 artifacts/_runs/footprint.jsonl")
    ap.add_argument("--kind", default=None, help="只处理这一类对象")
    ap.add_argument("--include-stuck", action="store_true", help="把之前删不掉的也再试一遍")
    ap.add_argument("--deleter", default=None, help="删除回调 module.path:function，签名 fn(item: dict) -> bool")
    ap.add_argument("--yes", action="store_true", help="真的执行删除（不加则始终 dry-run）")
    args = ap.parse_args(argv)

    fp = Footprint(args.ledger)
    delete_fn = _load_callable(args.deleter) if args.deleter else None
    cleanup(fp, delete_fn, kind=args.kind, include_stuck=args.include_stuck,
            dry_run=not (args.yes and delete_fn))
    return 0


if __name__ == "__main__":
    sys.exit(main())
