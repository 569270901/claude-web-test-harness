# -*- coding: utf-8 -*-
"""pytest 插件：按回归清单 YAML 在收集阶段给用例自动打标记（`-m <清单名>` 一条命令跑完一个版本 / 一组特性）。

为什么要有它：一个版本的回归范围往往横跨十几个测试文件、只取其中部分用例。到处手写
`@pytest.mark.xxx` 既容易漏也难核对；清单即真相——增删回归范围只改 YAML，不碰测试代码。

清单格式（结构示例见 data/regression/example.yaml）：
    suite: release_2_3          # 标记名；省略时用 version 字段，再省略用文件名（小写，非字母数字转 _）
    features:
      - id: FEAT-LOGIN
        name: 一句话说明这个特性
        entries:
          - file: tests/test_login.py                       # 整个文件都算
          - file: tests/test_profile.py
            tests: [test_profile_edit, test_avatar_]        # 只算函数名以这些前缀开头的（参数化后缀不影响）

匹配口径：`file` 是相对 rootdir 的路径，与用例所在文件完全相同；带 `tests` 时函数原名以任一前缀开头。
命中的用例额外带 `user_properties` 里的 ("suite_feature", <特性 id>)，便于报表按特性汇总。

清单目录：ini 项 `suite_manifest_dir`（相对 rootdir），默认 `data/regression`；目录不存在 = 插件不做任何事。

核对圈了多少条：
    python -m pytest --collect-only -q -m <清单名>

清单写了却一条都没命中（文件被改名 / 函数前缀写错）是"覆盖悄悄消失"，收集结束时会打印提示。
只打标记，不改变任何用例的执行结果。
"""
import re
from pathlib import Path

import pytest
import yaml

_DEFAULT_DIR = "data/regression"


def pytest_addoption(parser):
    parser.addini("suite_manifest_dir", "回归清单 YAML 所在目录（相对 rootdir）", default=_DEFAULT_DIR)


def _marker_name(raw: str) -> str:
    name = re.sub(r"[^0-9a-zA-Z_]", "_", str(raw).strip()).lower()
    if not name or name[0].isdigit():
        name = f"suite_{name}"
    return name


def _load(config) -> list[tuple[str, str, list | None, str, str]]:
    """返回 [(marker, 相对路径, 前缀列表或 None, 特性 id, 清单文件名)]。"""
    cached = getattr(config, "_suite_manifest_rules", None)
    if cached is not None:
        return cached
    root = Path(config.rootpath)
    mdir = root / (config.getini("suite_manifest_dir") or _DEFAULT_DIR)
    rules = []
    for f in sorted(mdir.glob("*.y*ml")) if mdir.is_dir() else []:
        try:
            doc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as e:
            raise pytest.UsageError(f"回归清单 {f} 解析失败：{e}") from e
        marker = _marker_name(doc.get("suite") or doc.get("version") or f.stem)
        for feat in doc.get("features") or []:
            for e in feat.get("entries") or []:
                prefixes = e.get("tests")
                if isinstance(prefixes, str):
                    prefixes = [prefixes]
                rules.append((marker, str(e["file"]).strip("/"), prefixes or None, str(feat.get("id", "")), f.name))
    config._suite_manifest_rules = rules
    return rules


def pytest_configure(config):
    for marker in sorted({r[0] for r in _load(config)}):
        config.addinivalue_line("markers", f"{marker}: 回归清单 {marker}（由 tools/pytest_suite_manifest.py 按清单自动打标）")


def pytest_collection_modifyitems(config, items):
    rules = _load(config)
    if not rules:
        return
    root = Path(config.rootpath).resolve()
    hit = [0] * len(rules)
    collected_files = set()
    for it in items:
        try:
            rel = Path(str(it.path)).resolve().relative_to(root).as_posix()
        except ValueError:
            continue
        collected_files.add(rel)
        name = getattr(it, "originalname", None) or it.name
        for i, (marker, path, prefixes, feat, _src) in enumerate(rules):
            if rel != path:
                continue
            if prefixes and not any(name.startswith(p) for p in prefixes):
                continue
            it.add_marker(getattr(pytest.mark, marker))
            it.user_properties.append(("suite_feature", feat))
            hit[i] += 1

    # 提示：清单条目对应的文件这次被收集了，却一条用例都没命中 → 多半是前缀写错 / 用例改了名
    tr = config.pluginmanager.get_plugin("terminalreporter")
    for i, (marker, path, prefixes, feat, src) in enumerate(rules):
        missing_file = not (root / path).exists()
        if missing_file or (path in collected_files and hit[i] == 0):
            why = "文件不存在" if missing_file else f"前缀 {prefixes} 一条都没命中"
            msg = f"[suite-manifest] {src} / {feat}: {path} {why}"
            if tr is not None:
                tr.write_line(msg, yellow=True)
