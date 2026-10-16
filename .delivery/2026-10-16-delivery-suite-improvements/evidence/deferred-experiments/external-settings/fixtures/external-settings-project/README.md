# 外部运行配置乘法命令

运行 `python3 -B app.py`，实际读取同目录 `settings.json` 的 `factor`，将固定输入2乘以factor，stdout输出单个JSON对象 `{"result": 数值}`。factor必须是JSON整数（不接受bool），可为正、零或负数；当前样例factor=2。factor是可变外部运行配置，必须每次实际读取，不得硬编码样例值。

文件缺失、JSON错误、非对象、缺factor或类型不合法时非零退出，stderr提供诊断，stdout不得留部分结果。命令不得修改配置；仅Python标准库，不增加网络、数据库或持久副作用。正常退出0。

T-01仅拥有app.py和tests/。settings.json由外部配置所有者维护，不属于本任务产物；代码读取它这一依赖已公开。当前机制有意不把它加入任何context_scope，保留在全树monitor初始基线，由后续活动先观察真实外部变化，再根据实际消费者判断影响。不得把未列context解释为无依赖或允许忽略配置。

设计、计划和当前实现交接均在本目录；专业记录和真实控制账本使用 `.delivery/external-settings/`。初始源码和配置来自资产维护者，待独立核验及真实接纳；没有预先的审阅通过或整体验收事实。测试为 `python3 -B -m unittest discover -s tests -v`。不push，不联系他人。
