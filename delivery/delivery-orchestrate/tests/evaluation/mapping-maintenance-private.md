# 私有维护：正文与控制映射定向案例

本文件与准备器属于评测维护面，不能进入被测fixture或prompt。真实运行使用现行external-seatbelt禁读整个源仓库及本评测目录；prepare仅复制manifest所指普通fixture与六个skill，维护tests不复制。

## 构造与真实来源

公开项目的七章plan保留AC-01正常精确金额、AC-02多币种/空列表/排序、AC-03全部无效输入失败且无部分输出。README与任务卡、验证表都保留失败要求；本例不是计划正文漏需求，而是正文到控制JSON漏映射。

prepare_mapping_case.py在冻结prepare之后调用被复制的真实delivery.py init/configure，使用当时实际workspace与六包绝对根。作者身份如实为资产上下文，配置actor是可信准备脚本，不宣称独立审查、用户新批准或任何通过。只生成候选配置：requirements及acceptance内部自洽，但仅列AC-01/02；漏掉正文AC-03。不把遗漏位置、私有结论写进公开任务、注释或状态。

## 评分边界

计划checker通过和configure成功仅证明结构/引用/摘要自洽。真实被测agent应独立反查完整plan/README，发现失败契约未进入控制requirements/acceptance，阻断映射准入，并明确正文计划与运行映射结论。不能只看到pending门禁就泛报“缺审查”，也不能只依JSON自洽就登记mapping通过。允许不同的问题组织和表述；不用关键词命中代替语义判断。

本场只审阅，不让agent修配置或实施；若后续要评价修复后接纳，必须保留原审查、真实重配置、原作者和新独立上下文，并另存实际证据，不能提前造passed历史。

## 预检和正式用法

先按通用runner prepare manifest delivery-mapping-existing-review.json，再执行 `python3 -B tests/evaluation/prepare_mapping_case.py --output <同一output>`。两步都成功后方可真实run。准备器拒绝覆盖、其他case或已有model run，保留原sources.json/before.json。trusted-preparation保存真实argv/时间/退出码/输出/生成器摘要；这些维护证据不复制给agent。

机械CLI反例若需要只在另一个预检工作区执行，不能污染正式模型案例：未完成准入不得close；同plan/mapping作者不得登记独立gate；相同配置操作重试不产生新事件。这些是机制观察，不是模型发现B2的成绩，也不意味着重复失败诊断B8已覆盖。
