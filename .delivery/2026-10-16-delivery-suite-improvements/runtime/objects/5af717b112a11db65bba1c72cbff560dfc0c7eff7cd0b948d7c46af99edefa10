# 独立覆盖审查后的定向案例补充

记录 E-013；2026-10-16；版本 1。范围 T-10，承接 E-011。案例作者 `/root/behavior_harness`，协调整理 `/root`。生成依据 delivery-implement 契约 1、专业内容提交 `197b989`；执行授权及任务/验收仍为原 plan.md v1.1，没有扩大交付功能。

## 依据与边界

独立报告 `review/016-coverage-gap.md` 指出，原正常生成案例和四项假绿反例不能直接证明既有计划审阅、等价修复复审、正文到控制映射语义遗漏及重复失败后的新诊断。本次补最小真实输入；没有把 54 条维护定义全部变成强制模型调用，也没有修改五专业包或编排核心。

## 产物与决定

| 公开案例 | 真实构造及准备 | 证明范围与限制 |
| --- | --- | --- |
| delivery-plan-existing-review.json | 七章既有计划、完整公开需求及实际授权；机检真实 ok=true、无 finding | 结构合法仍须专业审阅覆盖和授权语义，模型成绩另记 |
| delivery-review-existing-fix.json | 旧问题、旧 float 实物、当前整数分实现及真实4项测试 | 复审以原客观关闭条件判断替代修复，不能强制原建议补丁 |
| delivery-mapping-existing-review.json | 可信准备器真实 init/configure，正文完整而候选控制内容自洽；必要 gate 均 pending | schema 接受不等于映射正确；不预置独立通过，不改业务或伪造身份 |
| delivery-implement-repeated-failure.json | 维护脚本实际两次同版本/同命令失败，原始 stdout/stderr、时间及源码摘要留存 | 评价接手者能否基于失败事实作新诊断；不冒称此前是同一模型自己的两次失败 |

私有构造及评分文件均独立放在维护目录，不复制进普通项目或提示词。正式准备只复制声明技能；准备器不向正式映射案例写入预检机械探测活动。

## 实际检查

两专业案例的17项冻结清单和两次实物检查、单包隔离预检在 `evidence/behavior/focused-case-assets/`。映射案例9项冻结清单、真实 configure/check/status 成功及门禁 pending 见 `mapping-case-preflight-002/`；第一次依赖字段错误遭真实拒绝，保留在 `mapping-case-preflight/`。重复失败交接的12项冻结清单和真实两次 exit=1 见 `repeated-failure-case-preflight/`；同源码摘要及隔离预检均实际核对。

这些检查只证明资产可用。新增案例尚待隔离修正后的真实模型运行和非作者评价，未登记 V-06 通过。

## 交接与遗留

使用同一原生 CLI、模型配置和显式外部沙箱执行，按实际版本绑定评审。环境独立审查发现的历史 metadata 可访问问题属于 T-09，修补和重验单独留据；旧运行、旧错误和原专业成果全部保留。本次没有提交、push 或改写评测判据。
