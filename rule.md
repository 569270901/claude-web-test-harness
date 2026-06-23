# 编码规则与技术避坑

> agent（尤其 page-map-sync / test-writing）写代码、探索页面前先读本文件。
> 踩到新的坑（selector 写法、等待时机、组件行为）→ 主动回写这里。

## Selector 优先级（从高到低）

1. **语义 ID / role**：`page.get_by_role("button", name="Save")`、`#firstName`
2. **稳定属性**：`[placeholder="..."]`、`[aria-label="..."]`、`[data-testid="..."]`、`[href*="/topics/"]`
3. **文本定位**：`page.get_by_text(...)`、`button:has-text("提交")`
4. **避免**：hash class（随构建变化的 `.css-1a2b3c`）、`:nth-child(n)`、xpath 位置索引

## 等待时机

- 导航后用 `page.wait_for_load_state("networkidle")` 再采集元素，别靠固定 sleep
- 断言用 Playwright 的 `expect(...)`（自带自动重试），不要 `assert locator.is_visible()`
- 浮层（下拉/菜单/弹窗）出现后再操作，必要时 `expect(locator).to_be_visible()` 卡一下

## 组件行为（通用）

- 三点菜单 / hover 菜单：先 hover 行，再点触发图标，菜单才渲染
- 某些按钮在 headless 下点击不切换视图 → 加 hover 再 click，或退化为 URL 直达
- popconfirm / tooltip 经常没有 `role=dialog`，按文本或就近容器定位

## 测试设计

- 所有字段都填（含非必填），所有有意义的字段都断言
- `expected` 用有语义的值，不要用 `"0"` / `"-"` / 空字符串
- 文本型断言用「包含子串」而非精确相等，避免格式漂移
- 注释用中文
