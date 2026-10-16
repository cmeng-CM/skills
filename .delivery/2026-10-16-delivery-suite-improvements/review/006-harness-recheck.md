# IR-004 外部适配器定向复审

**IR-004 已按原关闭条件解决。** 当前结论是“线程与回合绑定及相关控制流通过定向复核”；尚未证明外部启动在本机正式模型环境可用，也未关闭真实组合评测或整体验收。

| 身份及版本 | 实际内容 |
| --- | --- |
| 审查者、日期、独立性 | `/root/independent_delivery_review`；2026-10-16；未参与修复、正式测试或真实评测实现 |
| 原问题 | review/004-harness.md 的 IR-004；原误通过探针保留为 review/004-thread-binding-probe.json，不改写旧 executed 事实 |
| 本次实际版本 | external_seatbelt.py SHA-256 `7b6618beb4ac36401c6a9a433b463d2c6073c8935289f4b27e64c57bfd7ae36c` |
| 本次方法 | 读取实际 consume/response/缓冲/终态逻辑；重跑原反例；实际运行 test_external_seatbelt.py 的 12 项控制流回归 |
| 新反例输出 | [006-harness-recheck-probe.json](006-harness-recheck-probe.json)；是隔离 JSON-RPC 对端，不是实际 Codex 或模型行为 |

## 原反例复现结果

与原失败使用同一消息结构：创建 root-thread/root-turn，只发 child-thread/child-turn 的 final 与 completed，不发根回合完成。新适配器实际得到 timeout，ignored_foreign_lifecycle_events=2；没有生成归一化根 turn.completed，没有生成 last-message.txt，原始 child 文本仍在 appserver.jsonl。原来错误的 executed 不再出现。

修复从真实 thread/start 和 turn/start 返回值获取根身份，item/final、token usage 和 turn terminal 都须同时匹配。turn/start 响应到达前的通知先留原始记录并缓冲，取得身份后回放过滤，避免过滤正确早到通知。其他线程通知保留原文，仅不影响本次根终态。commentary-only 不再作为 final 的兜底；phase=None 仍支持合法无 phase 消息。

## 修复影响与回归

实际运行 `python3 -B -m unittest discover -s delivery/delivery-orchestrate/tests -p test_external_seatbelt.py -v`，12 项通过。具体覆盖正确根完成、异线程 final/usage/completed 不污染根结果、同线程错误 turn 保持超时、根通知早于响应可正常回放、仅 commentary 不算 final、超时保留原始部分轨迹、进程崩溃及损坏 JSONL 不通过。另有 profile/三 canary 相关可控测试；后者只是边界构造与判断分支，不冒称新的真实 OS 探针。

当前版本同时将 SQLite/log 位置显式导向 fixture，OS profile 不再给真实用户 state/log 文件写入例外，使用 strict-config；这收窄写范围，与本问题的身份修复没有冲突。但实际 CLI 是否接受并在此边界内完成启动/工具/模型执行仍由后续真实原始证据证明，本报告没有将这些新增参数或 mock 成功当成环境可用。

IR-004 技术状态为复审确认解决。IR-002/IR-003 的旧复核继续见 review/004-harness.md；core IR-005—IR-007 仍待另行复核。正式 V-06 目前未进行，不能据此填写质量通过。
