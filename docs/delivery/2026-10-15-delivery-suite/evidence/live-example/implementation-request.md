# 实施演练请求与授权来源

本隔离样例复制自 /private/tmp/delivery-suite-independent-audit/standalone-plan，承接同一 label 前缀目标及原计划，不代表修改原规划样本。原 request.md 的仅规划授权保持不变。

2026-10-15 父任务另行明确授权：在 /private/tmp/delivery-suite-live-example 使用最终 delivery-implement 真正实施和自检，沿用已生成计划，保留原始基线、实际改动、原始命令输出与规范实施报告；不默认提交、不创建 runtime 或 .workflow。完成后交独立审查者用 delivery-review 和 delivery-verify 继续。实际样例与证据复制到 skills 项目 docs/delivery/2026-10-15-delivery-suite/evidence/live-example/。

执行目标为 docs/delivery/2026-10-15-label-prefix/plan.md 的 T-01：label 增加 keyword-only 参数 prefix: str = ""，结果为 prefix + text.strip()；prefix 原样保留，无自动分隔符；旧调用行为不变；调用者保证 str，不新增 I/O、UI 或依赖。完成正式测试和实际自检，验收 AC-01 至 AC-05 不变。

执行者为 capability_docs 子 agent，也是 delivery-implement 的作者；本次是作者执行的真实工作样本，不是独立盲测。后续 independent_audit 未参与产品实现，独立评估审查与验证结果。
