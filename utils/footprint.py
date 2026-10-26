# -*- coding: utf-8 -*-
"""数据足迹台账 —— 记下用例在被测系统里"建了谁 / 删了谁 / 删不掉谁"，供精确清理和事后审计。

为什么要有它：在共享测试环境里跑会写数据的用例，用例一旦中途失败 / 被杀，teardown 来不及删，
自建数据就成了残留。常见的"省事"清理是按测试数据前缀（如 AUTO_）批量删——这很危险：
别人（或手工测试）恰好建了同前缀的数据、或者前缀和真实数据撞了，就会被误删，而且收不回来。

原则（写死在这里，接入方别绕开）：
1. **只清理自己登记过的对象**：用例每建一个对象就 `created()` 记一笔完整名字，删掉就 `deleted()`
2. **按完整名字精确匹配**：清理时只认台账里的完整名字，绝不按前缀 / 模糊匹配批量删
3. **删不掉就登记**：删除失败（服务端拒绝、被引用等）记 `stuck()`，不反复硬删、不扩大范围，
   留给人看；下次清理默认不再自动重试（`include_stuck=True` 才重试）
4. **只增不改**：台账是 jsonl，一行一事件，从不改写历史；"当前待清理"由事件回放得出

台账字段：event（created / deleted / renamed / stuck）、kind（对象类型，自定义，如 "item" / "user"）、
where（所在范围，自定义，如某个父对象 id；同名对象在不同范围下互不影响）、name（完整名字）、
ts（时间）、source（来源用例，自动取 PYTEST_CURRENT_TEST）以及调用方附加的任意字段。

用法：
    from utils.footprint import Footprint

    fp = Footprint(require_prefix="AUTO_")            # 默认台账 artifacts/_runs/footprint.jsonl（不入库）
    name = f"AUTO_ITEM_{int(time.time())}"
    ... 在页面上新建 name ...
    fp.created(name, kind="item", where="workspace-1")
    ... 用完删除 ...
    fp.deleted(name, kind="item", where="workspace-1")

    fp.pending()        # 建了还没删的：[{name, kind, where, ts, source, ...}]
清理残留见 tools/cleanup_footprint.py（真正的删除动作由调用方提供，台账本身不知道被测系统怎么删）。
"""
import json
import os
import time
from pathlib import Path

DEFAULT_LEDGER = Path(__file__).resolve().parent.parent / "artifacts" / "_runs" / "footprint.jsonl"


def _current_test() -> str:
    cur = os.environ.get("PYTEST_CURRENT_TEST", "")
    return cur.rsplit(" (", 1)[0] if cur else ""


class Footprint:
    """只增不改的 jsonl 足迹台账。

    Args:
        ledger: 台账文件路径，默认 artifacts/_runs/footprint.jsonl。不同任务想分开记就各传一个路径。
        require_prefix: 可选。登记 created 时名字必须以它开头，否则抛 ValueError——
            防止用例把环境里**原有**的对象误登记成"自己建的"，进而被清理工具删掉。
    """

    def __init__(self, ledger: str | Path | None = None, require_prefix: str | None = None):
        self.ledger = Path(ledger) if ledger else DEFAULT_LEDGER
        self.require_prefix = require_prefix

    # ── 写事件 ───────────────────────────────────────────
    def _append(self, rec: dict):
        if not rec.get("name"):
            raise ValueError("足迹台账必须记录完整名字（name 不能为空）")
        rec["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        rec.setdefault("source", _current_test())
        self.ledger.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(rec, ensure_ascii=False) + "\n"
        # 上次进程被杀时可能留下没有换行的半行：先补换行，否则这条新记录会和半行粘成一行一起作废
        if self.ledger.exists() and self.ledger.stat().st_size:
            with self.ledger.open("rb") as f:
                f.seek(-1, 2)
                if f.read(1) != b"\n":
                    line = "\n" + line
        with self.ledger.open("a", encoding="utf-8") as f:
            f.write(line)

    def _check_prefix(self, name: str):
        if self.require_prefix and not name.startswith(self.require_prefix):
            raise ValueError(f"{name!r} 不以测试数据前缀 {self.require_prefix!r} 开头——"
                             f"只能登记用例自己新建的对象，原有数据不能进台账")

    def created(self, name: str, kind: str = "object", where: str = "", **extra):
        self._check_prefix(name)
        self._append({"event": "created", "kind": kind, "where": where, "name": name, **extra})

    def deleted(self, name: str, kind: str = "object", where: str = "", **extra):
        self._append({"event": "deleted", "kind": kind, "where": where, "name": name, **extra})

    def renamed(self, old: str, new: str, kind: str = "object", where: str = "", **extra):
        self._check_prefix(new)
        self._append({"event": "renamed", "kind": kind, "where": where, "old": old, "name": new, **extra})

    def stuck(self, name: str, kind: str = "object", where: str = "", why: str = "", **extra):
        """删不掉的自建对象：从待清理里移出、单独列出，留给人处理。"""
        self._append({"event": "stuck", "kind": kind, "where": where, "name": name, "why": why, **extra})

    # ── 回放 ─────────────────────────────────────────────
    def events(self) -> list[dict]:
        if not self.ledger.exists():
            return []
        out = []
        for line in self.ledger.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                continue  # 半行（进程被杀时写了一半）跳过，不影响其余记录
        return out

    def _replay(self) -> tuple[dict, dict]:
        live, stuck = {}, {}
        for r in self.events():
            e = r.get("event")
            key = (r.get("kind", "object"), r.get("where", ""), r.get("name"))
            if e == "created":
                live[key] = r
                stuck.pop(key, None)
            elif e == "deleted":
                live.pop(key, None)
                stuck.pop(key, None)
            elif e == "stuck":
                if key in live:
                    stuck[key] = {**live.pop(key), "why": r.get("why", ""), "stuck_ts": r.get("ts")}
                else:
                    stuck[key] = r
            elif e == "renamed":
                old_key = (key[0], key[1], r.get("old"))
                for bucket in (live, stuck):
                    if old_key in bucket:
                        bucket[key] = {**bucket.pop(old_key), "name": r.get("name"), "renamed_from": r.get("old")}
        return live, stuck

    def pending(self, kind: str | None = None) -> list[dict]:
        """台账里"建了、还没见到删除、也没登记删不掉"的对象。"""
        return [r for (k, _, _), r in self._replay()[0].items() if kind is None or k == kind]

    def stuck_items(self, kind: str | None = None) -> list[dict]:
        return [r for (k, _, _), r in self._replay()[1].items() if kind is None or k == kind]
