# 既有正文与控制映射的独立审阅输入

本项补充普通计划生成之外的独立映射活动；资产自检不代表模型已完成专业判断。使用原冻结runner，不修改其prepare/run协议。

从仓库根创建新的正式output，再进行可信准备：

```bash
python3 -B delivery/delivery-orchestrate/scripts/evaluate_suite.py prepare \
  --case delivery/delivery-orchestrate/tests/evaluation/delivery-mapping-existing-review.json \
  --skills-root delivery --variant candidate \
  --output .delivery/当前目标/evidence/behavior/candidate-mapping-review-01
python3 -B delivery/delivery-orchestrate/tests/evaluation/prepare_mapping_case.py \
  --output .delivery/当前目标/evidence/behavior/candidate-mapping-review-01
```

准备器只为该case的全新工作区创建真实契约2 init/configure候选；每次从冻结副本的delivery.py调用，绝对skill路径按真实workspace生成。状态须保持待独立准入，未登记任何通过；不可跳过准备失败直接run。sources.json和before.json原始快照不改写。准备命令、时间、输出、来源作者、生成器摘要在output/trusted-preparation，agent看到的只有普通项目事实及实际候选账本。

此后使用README既有external-seatbelt run方法，禁读仓库和整个评测私有目录，保持与其他候选相同模型、推理、外部工具和OS边界。完整正文、实际JSON、真实gate及报告由独立评审者核实；不要把维护构造文件给agent，不按固定词语命中评分。

mechanical预检单独留存，不给正式case伪造先前审阅。prepare拒绝覆盖，生成器也拒绝其他case、已有run或已有preparation。预检工作区经过额外CLI权限探测，仅作机制证据，正式模型必须新prepare。
