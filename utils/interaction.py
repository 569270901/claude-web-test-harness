# -*- coding: utf-8 -*-
"""交互 helper —— 消费 page_map 的交互动力学字段（elements.*.async / gates、flows.steps）。

背景（"提交后翻页卡死"类问题的通用复盘）：
- 文件上传是异步的：set_input_files 后接口没落地就点 Continue / Save，表单校验判必填文件为空
  → 静默拦截、零提示，页面停在原 step。
- 多步表单各 step 的 DOM 常常共存、只切可见性：字段 count>0 不代表在当前步；
  固定 sleep 赌时间必然偶发翻车。

本模块把这两类等待统一为「等证据，不赌时间」。配置不写死在代码里，从 page_map/*.yaml 的
动力学字段读，页面对象只负责传入是哪个元素 / 哪条流——地图是唯一事实源。字段名与
artifacts/agents/page-map-sync.md「yaml 输出规范」一致：

    elements:
      upload_xxx:
        selector: 'input#file'
        kind: upload
        async:
          request: 'POST /api/upload'        # URL 子串匹配，可带 HTTP 方法前缀
          settled: '.upload-item-success'    # "真正完成"的 DOM 证据
        gates: btn_continue                  # 未 settled 时会静默拦截哪个动作（可为列表）
    flows:
      steps:
        indicator: 'text=/Step \\d of 3/'
        dom: coexist-hidden
        advance:
          trigger: 'button:has-text("Continue")'
          success_evidence: indicator-text-change
          failure_probe: '.form-error-message'

组件库相关的 selector（日期面板等）集中在 COMPONENT_DEFAULTS，默认值按 Ant Design 写
（组件库特有，换组件库时用 configure_components() 覆盖或直接改默认值）。
"""
import functools
import os
import time
from pathlib import Path

import yaml

_DEFAULT_PAGE_MAP_ROOT = Path(__file__).resolve().parent.parent / "page_map"

# 组件库特有的默认 selector（Ant Design）。换组件库时覆盖：
#   configure_components(date_panel=".el-picker-panel:visible", date_today_link="text=Today")
COMPONENT_DEFAULTS = {
    # 已关闭的浮层不会从 DOM 移除、只加 hidden class，必须排除 hidden 态，否则命中残留旧面板
    "date_panel": ".ant-picker-dropdown:not(.ant-picker-dropdown-hidden)",
    "date_today_link": 'a:text-is("Today")',
}


def configure_components(**overrides) -> dict:
    """覆盖组件库默认 selector，返回生效后的配置。未知键直接报错，防止拼错静默不生效。"""
    unknown = set(overrides) - set(COMPONENT_DEFAULTS)
    if unknown:
        raise KeyError(f"未知的组件配置项：{sorted(unknown)}，可选：{sorted(COMPONENT_DEFAULTS)}")
    COMPONENT_DEFAULTS.update(overrides)
    return dict(COMPONENT_DEFAULTS)


def _page_map_root() -> Path:
    env = os.environ.get("PAGE_MAP_ROOT")
    return Path(env) if env else _DEFAULT_PAGE_MAP_ROOT


@functools.lru_cache(maxsize=None)
def _load(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_page_map(rel_path: str, root: str | os.PathLike | None = None) -> dict:
    """读 page_map yaml（如 "my_module/form.yaml"），进程内缓存。

    root 默认是仓库根下的 page_map/，可用参数或环境变量 PAGE_MAP_ROOT 覆盖。
    """
    base = Path(root) if root is not None else _page_map_root()
    return _load(str((base / rel_path).resolve()))


_NESTED_KEYS = ("modals", "tabs", "sub_pages")


def _walk_nodes(node):
    """深度优先遍历页面节点：自身 + modals / tabs / sub_pages 里的子节点。"""
    if not isinstance(node, dict):
        return
    yield node
    for key in _NESTED_KEYS:
        children = node.get(key)
        if isinstance(children, dict):
            for sub in children.values():
                yield from _walk_nodes(sub)


def find_element(page_map_data: dict, name: str) -> dict:
    """按元素名在 elements（含 modals / tabs / sub_pages 嵌套）里查找，找不到直接报错。"""
    for node in _walk_nodes(page_map_data):
        els = node.get("elements")
        if isinstance(els, dict) and name in els:
            return els[name]
    raise KeyError(f"page_map 里找不到元素 {name}")


def get_flow(page_map_data: dict, name: str = "steps") -> dict:
    """取 flows.<name>（默认 flows.steps），缺失直接报错让 page-map-sync 补图。"""
    flow = (page_map_data.get("flows") or {}).get(name)
    if not isinstance(flow, dict):
        raise KeyError(f"page_map 缺 flows.{name}（多步表单必填），先让 page-map-sync 补图")
    return flow


def gating_elements(page_map_data: dict, action: str) -> dict:
    """返回所有 gates 指向 action 的元素 {name: element}。gates 可写成字符串或列表。"""
    hits = {}
    for node in _walk_nodes(page_map_data):
        for el_name, el in (node.get("elements") or {}).items():
            if not isinstance(el, dict):
                continue
            gates = el.get("gates")
            gates = [gates] if isinstance(gates, str) else (gates or [])
            if action in gates:
                hits[el_name] = el
    return hits


def assert_gates_settled(page, page_map_data: dict, action: str, timeout: int = 8000):
    """点 action 之前，确认所有会静默拦截它的异步元素都已出现 settled 证据。

    没 settled 就指名报错（哪个元素、缺哪个证据），而不是点下去让表单静默卡住。
    """
    for el_name, el in gating_elements(page_map_data, action).items():
        settled = (el.get("async") or {}).get("settled")
        if not settled:
            raise AssertionError(f"{el_name} 声明了 gates={action} 但缺 async.settled，先让 page-map-sync 补图")
        try:
            page.locator(settled).first.wait_for(state="attached", timeout=timeout)
        except Exception as e:
            raise AssertionError(
                f"{action} 被 {el_name} 拦截：未见完成证据 {settled}（{type(e).__name__}）") from e


def upload_and_wait(page, element: dict, file_path: str, scope=None,
                    timeout: int = 15000, settle_timeout: int = 8000):
    """按地图动力学字段执行文件上传，并等到「真正完成」的证据。

    element 需含 async.request（URL 子串，可写 'POST /path' 或纯 '/path'）与 async.settled。
    缺字段直接报错（让 page-map-sync 补图），不许退回固定 sleep。
    """
    async_cfg = element.get("async") or {}
    request_cfg = async_cfg.get("request")
    settled_sel = async_cfg.get("settled")
    if not (request_cfg and settled_sel):
        raise AssertionError(
            "元素缺 async.request / async.settled 动力学字段，先让 page-map-sync 补图，"
            f"不要退回固定 sleep：{element.get('selector')}"
        )
    parts = request_cfg.split()
    req_substr = parts[-1]
    method = parts[0].upper() if len(parts) > 1 else None
    root = scope if scope is not None else page
    n_before = page.locator(settled_sel).count()

    def _match(r):
        return req_substr in r.url and (method is None or r.request.method.upper() == method)

    with page.expect_response(_match, timeout=timeout) as resp_info:
        root.locator(element["selector"]).set_input_files(file_path)  # rules-allow: no_raw_set_input_files (统一 upload helper 本体)
    resp = resp_info.value
    if not resp.ok:
        raise AssertionError(f"上传接口 {resp.url} 返回 {resp.status}，文件未挂上")

    # 接口 2xx 后前端渲染仍是异步的，等证据节点数量增加
    page.wait_for_function(
        "([sel, before]) => document.querySelectorAll(sel).length > before",
        arg=[settled_sel, n_before],
        timeout=settle_timeout,
    )


def advance_step(page, flow: dict, timeout_ms: int = 8000):
    """多步表单翻页：等证据推进；被校验静默拦截时指名报错，绝不静默兜底。

    flow = page_map 的 flows.steps（可用 get_flow() 取），需含 indicator 与 advance.trigger；
    advance.failure_probe 可选（没翻过去时用来读校验错误）。目前支持的
    success_evidence 只有 indicator-text-change（缺省即此）。
    """
    adv = flow["advance"]
    evidence = adv.get("success_evidence", "indicator-text-change")
    if evidence != "indicator-text-change":
        raise NotImplementedError(f"advance_step 暂不支持 success_evidence={evidence!r}")

    def _indicator_text():
        loc = page.locator(flow["indicator"]).first
        return loc.text_content().strip() if loc.count() else None

    def _click_and_wait(wait_ms) -> bool:
        page.locator(adv["trigger"]).first.click()
        if before is None:
            # 当前页没有步骤指示器（常见于最后一步），无证据可等，只留渲染缓冲
            page.wait_for_timeout(1000)
            return True
        deadline = time.monotonic() + wait_ms / 1000
        while time.monotonic() < deadline:
            if _indicator_text() != before:
                return True
            time.sleep(0.25)
        return False

    before = _indicator_text()
    if _click_and_wait(timeout_ms):
        page.wait_for_timeout(300)  # 新 step 渲染缓冲
        return

    # 没翻过去 → 当场诊断（不要 except: pass 假装成功，让真因和报错隔一层）
    probe = adv.get("failure_probe")
    if probe:
        errors = [t.strip() for t in page.locator(probe).all_text_contents() if t.strip()]
        if errors:
            raise AssertionError(f"翻页被表单校验静默拦截（仍在 {before}），校验错误：{errors}")

    # 无可见校验错误 → 可能是点击时机竞态，重试一次
    if _click_and_wait(5000):
        page.wait_for_timeout(300)
        return
    raise AssertionError(
        f"点击 {adv['trigger']} 两次后仍停在 {before}，且 {probe} 无可见校验错误，需人工排查"
    )


def pick_date_today(page, input_selector: str, panel_selector: str | None = None,
                    today_selector: str | None = None):
    """日期选择器：打开面板等可见后点 "Today" 链接（selector 默认取 COMPONENT_DEFAULTS）。

    直接点"今天"格子会因面板被视口裁切误判不可见；面板开 / 关都等状态证据，不用固定 sleep。
    """
    panel_sel = panel_selector or COMPONENT_DEFAULTS["date_panel"]
    today_sel = today_selector or COMPONENT_DEFAULTS["date_today_link"]
    page.locator(input_selector).click()
    panel = page.locator(panel_sel).first
    panel.wait_for(state="visible", timeout=5000)
    panel.locator(today_sel).first.click()
    panel.wait_for(state="hidden", timeout=5000)  # 选完面板收起（加 hidden class 后不再匹配）
