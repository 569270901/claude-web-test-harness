# -*- coding: utf-8 -*-
"""测试执行层通用 helper（与具体站点 / 业务无关）。

- interaction：消费 page_map 交互动力学字段（async / gates / flows.steps），等证据不赌时间
- soft_check：软断言收集器，一条用例里的期望偏差一次性全报出来
- auth_state：按角色缓存登录态（storage_state），登录动作由调用方传入
- write_guard：只读用例的写请求保护（拦截写请求、可记录请求体），登录 / 刷新令牌类接口按规则放行
- response_capture：多页面接口抓包 + "没有接口报错"断言（HTTP ≥ 400，可选业务码钩子）
- footprint：数据足迹台账（建了 / 删了 / 删不掉），配合 tools/cleanup_footprint.py 按完整名字精确清理
"""
