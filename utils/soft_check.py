# -*- coding: utf-8 -*-
"""软断言收集器 —— 一次跑批把一条用例里的**所有**期望值偏差全暴露出来。

为什么需要：新提测的功能，cases.md 的期望值来自 PRD + 设计图，尚未与实现逐字对齐。
若一条用例里 10 个文案期望用 10 条硬断言串行写，第 1 条挂掉后面 9 条就再也跑不到，
要凑齐偏差清单得跑 10 轮。SoftChecks 让每条期望都被检查、失败被记录，**用例最终仍然失败**
（assert_all 抛 AssertionError 并列出全部差异），断言强度不打折，只是把"发现"批量化。

⚠️ 不是用来弱化断言的：
- 不允许用它把断言变成"记录一下就算了" —— 必须在用例结尾调 assert_all()。
- 顺序有依赖的步骤（点了 A 才能看 B）仍用硬断言 / 正常流程控制。
"""


class SoftChecks:
    """收集若干次比较，最后一次性断言。

    用法：
        c = SoftChecks("TC-HOME-005")
        c.eq(actual_title, "Add item", "弹窗标题")
        c.true(btn.is_visible(), "Add 按钮可见")
        c.assert_all()
    """

    def __init__(self, case_id: str = ""):
        self.case_id = case_id
        self.failures: list[str] = []
        self.checked = 0

    def eq(self, actual, expected, desc: str, actual_hint: str = ""):
        """相等断言（逐字，不做 strip / 规整 —— 文案字面值就是期望的一部分）。
        actual_hint：可选补充信息，与 true / false 的同名参数一致。"""
        self.checked += 1
        if actual != expected:
            hint = f"（{actual_hint}）" if actual_hint else ""
            self.failures.append(f"{desc}: 期望 {expected!r}，实际 {actual!r}{hint}")
        return actual == expected

    def contains(self, haystack, needle, desc: str):
        self.checked += 1
        ok = needle in (haystack or "")
        if not ok:
            self.failures.append(f"{desc}: 期望包含 {needle!r}，实际 {haystack!r}")
        return ok

    def true(self, condition, desc: str, actual_hint: str = ""):
        self.checked += 1
        if not condition:
            hint = f"（实际：{actual_hint}）" if actual_hint else ""
            self.failures.append(f"{desc}: 期望成立，实际不成立{hint}")
        return bool(condition)

    def false(self, condition, desc: str, actual_hint: str = ""):
        return self.true(not condition, desc, actual_hint)

    def assert_all(self):
        if self.failures:
            head = f"[{self.case_id}] {len(self.failures)}/{self.checked} 项期望不符：\n"
            raise AssertionError(head + "\n".join(f"  - {f}" for f in self.failures))
