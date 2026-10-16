# 评测环境修正独立复核

**结论：本次 TMPPREFIX 与公共独立上下文 header 修正可以接纳，未发现权限扩大、私有答案提示或必须丢弃旧轨迹的理由。** 这是环境适配结论；正式专业、完整组合和恢复案例的实际产物尚待独立语义评审，不能据此关闭 V-06 或宣告质量不下降。

记录 014；2026-10-16；实际复核者 `/root/independent_delivery_review`。复核者未编写被审产品、测试、案例或环境修正，只新增本报告及独立检查日志。源码与证据指纹见 [manifest](014-environment-manifest.json)；external_seatbelt.py 为 `d56ffded286a8834ed8d7c871ce287487880fe234ae3683f5f1d62e2465da783`，evaluate_suite.py 为 `6d9d6f60d89669a244db7d6913a0e6cd0f248e2ce1cf70436ca0280d9b5c9679`。检查前后这两文件及两套回归文件摘要相同。

## 1 环境与隔离边界

external adapter 从正常环境复制后，仅将 TMPDIR 路由到已有 fixture/.evaluation-tmp，将 TMPPREFIX 路由到该目录内 zsh 前缀；HOME/CODEX_HOME 不替换，OS profile、既有精确 installation_id 例外及保护校验不扩大。TMPPREFIX 是 zsh 临时文件前缀而非额外写目录。outcome、request.json、evaluation.json/Markdown 使用同一实际 temporary_environment 和 environment_keys_changed，避免元数据仍只声称 TMPDIR。

独立重跑 [external 19 项](014-test_external_seatbelt.py.log) 和 [harness 24 项](014-test_evaluate_suite.py.log)，全部通过。新增 fake RPC 子进程确实读到 TMPDIR/TMPPREFIX，同时 HOME/CODEX_HOME 与父进程一致；这些是适配回归，不计模型能力或真实 OS 隔离证明。

实际 OS 对照 [result.json](../evidence/behavior/zsh-tmpprefix-validation/result.json) 保存同 profile 下 zsh -f -c 与 -lc 两对结果：只有 TMPDIR 均因 heredoc 临时文件拒绝而 exit 1；加入 fixture 内 TMPPREFIX 均 exit 0 且输出 HEREDOC_INSIDE_FIXTURE。model_turn_started=false，被保护文件前后不变。原先大小写敏感摘要与修正说明均保留，未删除原始失败。该事实来自已保存真实 subprocess 证据，本复核没有另跑模型或冒称重新观察整个系统。

[process-audit](../evidence/behavior/zsh-tmpprefix-validation/process-audit.json) 在其记录时点只读检查到原生 evaluator 进程为零，明确没有发送信号、应用主进程不在目标范围。它不证明后续没有新进程，也不能代替某业务未知运行的副作用调查。

## 2 公共 header 与比较公平性

新 header 对 external-seatbelt 的三候选统一说明使用原生 multi_agent/spawn_agent；禁止 nested Codex CLI 的理由是其会重新加载全局配置/MCP 并尝试嵌套沙箱。它明确覆盖旧公开 prompt 中可选的 nested CLI 建议。原生接口不可用时只能保留待独立审查/外部调度，不可冒充新身份或绕过审批。

这些内容说明当前真实工具界面，不提供业务实现、缺陷标注、参考答案、预填门禁或账本写法。candidate-full-01/runs/002/prompt.txt 已实际包含相同 header；三份 infrastructure-resume.txt 的恢复段逐字相同，保留各自原任务，legacy 仍选择自己的 workflow 接口。必须在其余后续运行核对实际 prompt、接口、模型、effort、预算和隔离；不能只凭源码推断所有未来运行已经相同。

## 3 旧运行、恢复与重复观察

独立检查旧 9 个正式 root 的 run001，全部保存 execution-failed 及 usageLimitExceeded 原始事件，索引见 [quota interruptions](014-quota-interruptions.json)。基础设施中断不构成专业活动通过，也不能直接归咎 skill 质量。旧 prompt、工具、错误、部分产物、成本及当时 harness 来源应保留；新 header/环境不能追溯声称旧运行已具备新条件。

resource-check-013 的真实 root turn 完成、返回 0，elapsed 约 9.735 秒，证明该时点接口恢复，不保证未来额度、完整任务或新临时路由。其旧元数据没有新 temporary_environment/header，不能用它单独证明新环境下完整流程通过。

冻结 plan.md 第 5 章的要求是“代表性的完整流程和中断恢复案例每个候选初始至少重复两次”，没有“两条完整案例均不得外部中断”的附加条件。因此 full01 若从空白实际开始、事故原证据保留、全新上下文从磁盘续接、最终全链真实完成并通过独立评审，可以计一条完整流程观察；full02 在三候选同最新条件下从空白进行第二条合理。此接纳并不预判 full01 当前已完成或合格。

额度事故不能替代计划的阶段 partial-resume01/02，不能据恢复链声称单一环境空白执行效率更高，也不能挑最好一次或用平均分掩盖门禁失败。结果须区分计划中断和事故中断，并列实际总成本、重复工作、人工介入和环境差异。两条链若出现质量差异或可复现退化，仍须按原计划诊断增跑；目前没有依据额外强制 full03，也没有授权免除原案例覆盖。

## 4 后续门槛

环境修正不改变五专业内容、业务 fixture 或核心机制的要求。接下来仍需逐实际根/子 agent 轨迹核对真实独立性、来源读取和泄露边界、业务产物、问题及修复、验收、Git/no-push 和恢复证据。先前源码/回归通过不能替代这一步。本报告未修改产品、被测产物、控制配置或评测判定。
