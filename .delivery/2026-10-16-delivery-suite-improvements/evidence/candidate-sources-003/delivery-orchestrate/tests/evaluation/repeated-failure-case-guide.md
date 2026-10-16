# 重复失败交接的实施输入

delivery-implement-repeated-failure.json是只调用delivery-implement的普通修复项目。公开history已包含维护者对同版同命令两次真实失败，不是先前LLM修复活动；它们原样保留，不能改成假通过。资产存在不表示模型已经完成诊断或修复。

```bash
python3 -B delivery/delivery-orchestrate/scripts/evaluate_suite.py prepare \
  --case delivery/delivery-orchestrate/tests/evaluation/delivery-implement-repeated-failure.json \
  --skills-root delivery --variant candidate \
  --output .delivery/当前目标/evidence/behavior/candidate-implement-repeated-failure-01
```

随后沿用同一external-seatbelt/真实原生CLI条件run。无需在prepare后再跑record_repeated_failure.py，历史已属于冻结输入。该维护生成器只为首次构造留存可复现的真实来源，拒绝覆盖旧历史，不能把模型工作区的历史更新成当前结果。

完整trace和实际产物需由独立评审者判断。重复失败交接后的新诊断、真实修复与副作用分别核验；最终测试绿或一句策略说明都不能单独证明诊断质量。本例不等于同一模型此前连续失败两回合的实验，评价不得超过实际轨迹范围。
