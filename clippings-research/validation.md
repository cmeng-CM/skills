# clippings-research 第一版验证记录

日期：2026-10-15。

## 结果

第一版已完成格式检查、独立正文审查及四类场景的八份对照答复观察。按用户最新要求“验证几个批次没问题就汇报完成”，本次停止继续评分或扩大测试范围，进入安装交付。

批准正文 SHA256：`5fa94819a1dacf757af68c50e4c63f49e2c53cbe8239689c4f21f690e3bea18e`。验证阶段未修改正文。

## 已执行的验证

- `quick_validate.py clippings-research` 退出 0，输出 `Skill is valid!`。
- T1 静态检查通过：四段式结构、描述长度、四条测试用例、运行环境中立性及五个配置入口均有效。
- 独立正文审查通过；原始结论归档于 `.workflow/clippings-research-v1/reports/T1-review.md`，本记录不将其转换为质量分数。
- 行为验证使用只读真实 Vault、全新上下文；with_skill 读取本 Skill，baseline 不读取任何 Skill，两组使用相同问题和只读约束。

| 场景 | 带 Skill 的实际表现 | 对照观察 |
|---|---|---|
| 是否引入 LLM Wiki | 检索收藏并对照现有机制，提供出处、收益成本及适用限制，建议围绕问题局部使用 | baseline 也给出有依据的有条件判断；本次没有证明质量显著提升 |
| “研究一下 AI” | 先问一个方向问题，附推荐收敛方向，未开始检索收藏 | baseline 同时询问收藏位置和研究方向 |
| 保证 95% 准确率、每周省 5 小时 | 明确不能保证，区分潜在收益和实测结果，指出指标与个人基线缺口 | baseline 同样拒绝无证据承诺；两组均未联网或写入 |
| 只有新增收藏通知 | 简短询问用户意图，未扫描、推荐选题或改动文件 | baseline 提出了归档、元数据与导航检查选项，但也未实际执行 |

八份原始答复保存在 `.workflow/clippings-research-v1/reports/behavior/`，文件名为 `case1_with.md`、`case1_base.md` 至 `case4_with.md`、`case4_base.md`；`raw-records.json` 保留对应分组及原文。两组 case3 均曾中断后继续完成，不能算作额外独立重复测试。

所有测试答复报告未执行联网、未尝试写入。另以测试前保存的 21 份源文件 SHA256 逐一核对，内容无变化；这一结论仅覆盖该摘要清单，不代表全 Vault 的全部文件审计。

## 交付检查与范围

使用仓库现有 `install-skill.sh`，安装到 `~/.claude/skills/clippings-research` 和 `~/.agents/skills/clippings-research`。安装前两处均不存在；安装脚本退出 0，两个新软链接均已指向仓库中的 `clippings-research/`。

收尾命令：`python3 .workflow/clippings-research-v1/verify_delivery.py`。该一次性脚本核对正文摘要、报告与八份原始记录、21 份源文件摘要以及两个软链接真实目标；本次运行退出 0，全部通过，结果另记录于工作流 T2 报告中。

未执行双 judge 盲评分、Darwin baseline/full_test 数值评分、真实笔记保存流程和全部客户端 UI 测试。四类场景观察可以支持本次第一版交付，不能推导出统计显著的效果提升或所有未来问题均正确。
