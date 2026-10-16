# IR-001 定向复审

**IR-001 已按客观关闭条件解决。** 本次仍只检查机械验证运行器，不替代独立 agent 行为、运行时核心或全局实现审查。

审查者 `/root/independent_delivery_review`，2026-10-16；非该脚本作者，未修改产品或正式测试。原问题见 [002-professional.md](002-professional.md)，旧版摘要保留在其 manifest；本次修复版 validate_suite.py 的 SHA-256 为 `b16da837ff328ca43e82222aca52fccb8d8f75b8d49a24ad9cd3fb4f111131d5`。

实际重新读取修复代码，并在隔离目录运行三个可控异常探针：[003-validator-probes.json](003-validator-probes.json)。

| 触发 | 实际结果 |
| --- | --- |
| TimeoutExpired，携带 byte stdout/stderr | 保存原部分输出，当前项 timeout，后续三项 not-run，JSON 与 Markdown 同时存在，ok=false |
| FileNotFoundError，进程启动失败 | 保存错误文本，当前及后续项 not-run，明确原因，JSON 与 Markdown 存在，ok=false |
| 所有子进程退出 0，但 unittest 为 Ran 0 tests | 三项 unittest 均 failed，ok=false；不再仅据退出码通过 |

正常非零返回仍形成 failed，并继续其他独立检查；这与超时/启动失败停止后续项的区别可由代码和上述状态派生确认。原失败、旧版报告和问题 ID 保留。本次没有重复跑完整回归，没有将 mock 异常探针计入实际模型测试数量。
