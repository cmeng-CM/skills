# 包装检查探针与能力契约对照

执行者：capability_docs，三个能力 skill 的作者；本次只读产品检查。时间：2026-10-15。

## 包装检查实际结果

在 `/private/tmp/delivery-suite-package-probes-uhjj1tl6/` 复制实际六项 skill，分别制造损坏，没有修改正式 skill 或新增正式测试。

| 案例 | 实际改动 | 退出码 / ok | 结果 |
| --- | --- | --- | --- |
| normal | 完整包，无改动 | 0 / true | 通过 |
| broken-link | implement 入口增加指向不存在参考文件的 Markdown 链接 | 1 / false | 明确报告断链 |
| missing-file | 删除 review-standard.md | 1 / false | 两个引用位置均报告断链 |
| missing-entry | 删除 verify/SKILL.md | 1 / false | 报告缺少入口 |
| invalid-json | 将 verify 行为案例截断为非法 JSON | 1 / false | 报告 JSON 语法错误 |

准确命令、时间、变更及输出见 manifest.json 和各案例 stdout/stderr；被测脚本保存在 check_suite.snapshot.py，正常包文件指纹也在 manifest.json。5/5 结果符合预期。该证据只证明这些包装损坏可检出，不证明语义质量、所有 Markdown 语法、行为案例实际执行或完整编排效果。

## 三项能力与 runtime-api 的语义对照

实现产物形成与验收分离、审查规格/质量双判断、非实现者独立性、问题稳定 ID 与修复记录、验证失败/未知区分、人工确认真实性、风险接受不改写符合等方面，没有发现直接的质量门禁冲突。

有一处首版接纳限制需要明确说明：

- delivery-verify/references/delivery-contract.md 约定独立报告接入核对有效性、不要求无意义重做；独立验证可以真实运行命令并保存日志。
- runtime-api.md 的命令验收必须指向本引擎的 run_operation；delivery.py::validate_verification 仅从当前日志找到 kind=run 的完成事件。不存在时仅无 run_operation 的 unknown 可接纳；passed 和 failed 均拒绝。
- 因此独立阶段已真实执行且版本未变的命令证据，不能直接形成本引擎 command 门禁的通过/失败，首版需要由引擎再真实运行。不能伪造旧 run，也不能将原要求的 command 改成 inspection 绕过要求。

建议作为首版明确的“外部命令执行证据不直接导入”限制记录：保留独立报告与证据、说明需要新运行的原因；这不是删除旧证据或要求全部能力重新工作。未来如真实使用频繁出现不可重复的外部操作，再设计受约束的外部运行接纳。无需让五个能力反向依赖编排脚本。

此项已报告父任务，未擅自修改产品或契约。其余判断基于当前文档与定向源码阅读，没有完成全引擎独立审计。

后续处置：父任务确认保留首版引擎限制并明确文档。按其授权，在 delivery-verify/references/delivery-contract.md 补充新 run 回执、产品版本一致、重跑副作用评估、不得改 inspection 绕过、不能安全重跑则保留待验的规则。quick_validate 再次通过。未修改其他两个能力或引擎；编排侧文档由对应负责人同步。历史演练 skill 快照保持当时版本。
