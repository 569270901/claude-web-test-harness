# -*- coding: utf-8 -*-
"""测试执行层通用 helper（与具体站点 / 业务无关）。

- interaction：消费 page_map 交互动力学字段（async / gates / flows.steps），等证据不赌时间
- soft_check：软断言收集器，一条用例里的期望偏差一次性全报出来
- auth_state：按角色缓存登录态（storage_state），登录动作由调用方传入
"""
