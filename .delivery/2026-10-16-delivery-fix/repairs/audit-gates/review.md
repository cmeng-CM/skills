# FA-001 / FA-002 独立定向复审

结论：两项原确认 P2 在本次审阅范围内均已修复，未发现需要继续修改的阻断问题。该结论绑定下列实际文件内容，不代表全仓库、全部模型行为或用户验收无条件通过。

- 审阅者：独立 agent `/root/fix_fresh_audit`；未实施本轮产品修改，也未参与父协调者的修复编写。
- 时间：2026-10-16T15:30:47+08:00。
- 基线提交：`1dda827fd508730ff5fb8d0e10122d8f1d265f40`；受审对象是其上尚未提交的七项源码、规范和测试改动。
- 操作范围：只读代码、diff 和既有定向验证证据；仅新增本复审报告，未改产品、正式测试或规范，未提交、安装、启动子 agent、重跑测试或追加探针。

## FA-001：已用来源漂移不能收尾

修复成立。`delivery_v2.py:425-434` 按当前计划、审查、验证、已配置设计、任务实施路线及已接纳产物收集实际专业来源；`:445-451` 将其用于 complete/limited 共用的 close 准入。仅登记而未实际使用的可选 fix 不加入收尾依赖。该路径仍读取原 source_drift 与有效来源链，不改旧记录及其 pin。

已核对现成测试：已用 fix 漂移同时阻止 complete 和 limited；恢复原包后原真实 run 仍可支撑收尾；显式兼容更新且 affected_targets 为空时保留有效旧结果；未用可选 fix 的漂移不阻塞默认任务。测试没有把旧报告 pin 的可追溯性误作当前漂移已被接纳。

## FA-002：跨配置继承持续失败诊断责任

修复成立。`delivery_recovery.py:260-271` 汇总稳定目标的历史 attempt，并复用 `delivery_implementation.py:110-122` 已知同 bug 任务闭包；不因刷新 config、切换实施能力或同 bug 转交自然清空记录。`:274-287` 对事实内容摘要去重排序、策略作首尾空白规范化；重复／重排事实及仅改 outcome 不解除 pending。解除必须存在当前有效的不同事实内容或策略；逐事件重算会在该依据过期后保留先前未解决的 pending。

已核对现成测试：连续两次重配置仍阻塞 record 和 close；重复相同事实并仅改 outcome 不解除；当前有效新事实解除、依据改变后重新阻塞；同 bug 新任务继承失败，当前有效新策略可以解除共同诊断责任。未要求靠改名、覆盖旧失败或重新初始化取得通过。

## 验证证据与兼容性边界

父协调者保存的 `result.json` 记录 12 项定向测试（5 新增、7 原有）退出 0；`stderr.txt` 逐项列出 12 项成功及 `Ran 12 tests`，与命令和范围相符。包含旧默认组合关闭、作者继承、相关活动来源漂移、来源重接纳／gate pin 过期及恢复转接保持 owner 与有效调查的相关回归。fixture 拆为非 TestCase 公共类，避免新增类继承并重复发现旧测试。

未知 run、恢复转接、required acceptance、limited 例外和旧 close 事件写入逻辑未被本次改动直接修改；新判断接入原 assert_ready 顺序，没有替代未知运行或正式验收门禁。已存在的 close 事实与日志均未改写；升级活动工作仍按现有 source-update 显式接纳实际引擎。

限制：本轮是代码审阅及既有确定性证据核对，没有独立重跑模型行为评测、全套历史样本或全流程交付。机器仍不能判断新策略文字是否包含实质新判断、来源兼容判断是否正确或真实作者是否完整；需原有专业检查负责。事实引用重排的等价性从去重排序代码核对，现成新增测试直接执行了重复引用案例。历史闭合工作与未知运行的全部组合没有重新穷举。

## 实际来源绑定（SHA-256）

| 受审文件或现成证据 | SHA-256 |
| --- | --- |
| `delivery/delivery-orchestrate/scripts/delivery_v2.py` | `a5cac0618acac31a5a561642f56f1cb84c8acae75ebfd65f6921519550540aa7` |
| `delivery/delivery-orchestrate/scripts/delivery_recovery.py` | `1394950976f6d912cf86611e42f543fd6bcdb9e0c6bdc1e23b022adc246a7d64` |
| `delivery/delivery-orchestrate/scripts/delivery_implementation.py` | `40d95cea3d7906c0caa615a41321f338a266bdf205249c2362915283d78d77af` |
| `delivery/delivery-orchestrate/references/runtime-api-v2.md` | `50f98d113067f7b55c15a8f40a65911d3e32541dc8fba5f7d579b626719eeefa` |
| `delivery/delivery-orchestrate/references/maintenance.md` | `f1e5b7a72894860a055f693e8931a79eb3a8284915589062f3c1cced560919da` |
| `delivery/delivery-orchestrate/tests/test_delivery_fix.py` | `363ddae24df1c7198431ca7ff939e3863f61847554cbf205e6f38e7b087c66e2` |
| `delivery/delivery-orchestrate/tests/test_fix_gate_repairs.py` | `368db6e4a6bbc185b98dd0c093441a744bf36e75ea5312c8f0888657f1efefb8` |
| `.delivery/2026-10-16-delivery-fix/repairs/audit-gates/result.json` | `8215eaf6c423e9713b446c896b8540c8e7276e7b3297d5573d2fd8fb6277b26b` |
| `.delivery/2026-10-16-delivery-fix/repairs/audit-gates/stdout.txt` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `.delivery/2026-10-16-delivery-fix/repairs/audit-gates/stderr.txt` | `581f7c3c4872ea84256adf978f8e9e088405d5ef70f3ef87943737eb5cf9fa5d` |
