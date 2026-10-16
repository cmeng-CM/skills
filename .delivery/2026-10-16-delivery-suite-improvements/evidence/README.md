# 证据留存

设计、计划、独立审查、实施记录、最终机械检查、三次来源冻结和稳定runtime随本目标纳入本地Git。原始模型会话、失败、临时诊断及采集产物完整保存在本机 `behavior/`，未删除或筛选；不把其历史SQLite元数据和大量重复协议载荷提交到Git。

`behavior-raw-manifest.json` 保存全部原始文件的相对路径、字节数与SHA-256，`../verification/behavior-observations.json` 保存每个案例及每次运行的实际状态。需要迁移完整证据时连同被忽略的behavior目录复制，再逐项核摘要；仅检出Git不能声称已取得这部分原始证据。

基线全树source-working-tree.patch含其他原有改动，仅本机留存，不纳入Git；摘要在local-only-files.json。本次提交不通过基线补丁夹带其他skill的既有修改。

prepared/执行成功/独立评价/正式接纳各自含义不同。旧环境限制、未执行与失败全部保留，不把测试绿或案例存在当全部验证完。最新收敛要求及边界见 `../verification/convergence.md`。
