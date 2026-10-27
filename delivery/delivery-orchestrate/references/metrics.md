# 交付统计与成本归因

状态：质量-成本优化的最小统计口径。它不替代 journal、status 或验收；只把耗时、token 和 finding/验收归因到可比较的层级。

## 1. 数据层级

- **任务**：一个 summary 行，含 wall、phase 汇总、acceptance、finding、token。
- **阶段**：design/plan/admission/gate/implementation/review/rework/verification/close；记录起止、重叠标记、session/turn。
- **请求**：每次 model 请求的 model、input/output/cache/uncached、duration。
- **轮次/工具**：turn_usage、tool_usage；用于 active 与等待拆分。
- **finding/验收**：problem 到 fix commit/session，A-XX 到 attempt/evidence。

## 2. 最小文件集

~~~text
metrics/
├── summary.csv                 任务/批次汇总
├── phases.csv                  阶段窗口；重叠标 additive=no
├── model_usage.csv             请求级 usage
├── turn_usage.csv              轮次级时间/token/工具
├── tool_usage.csv              工具耗时/错误
├── acceptance_attempts.csv     每次 A-XX 尝试、first-pass、unknown
├── findings.csv                blocker/defect/observation、detected/introduced
├── finding_fix_map.csv         finding → fix commit/session
├── session_tree.csv            main/subagent/session 关系
├── price_table.csv             模型价格/币种/来源；未知为空
└── data_quality.md             来源、估算、缺失与不可归因范围
~~~

没有 session DB 时可手工产最小集，但必须标 source 和 unknown；不要用 commit gap 冒充 active。

## 3. 时间口径

- wall_min：窗口起止；
- active_min：turn/model/tool 实际时间；主会话共享窗口标 shared；
- wait_min：wall - active；人工等待单列；
- rework_min：返工 session/turn 的实际时间；没有则 unknown，不能用 commit gap；
- phase 可重叠，additive=no 时不得相加。

## 4. Token/成本口径

- input_tokens、uncached_input_tokens、cache_read/cache_creation、output_tokens 分列；
- 金额只在 price_table 有 provider/model/日期/币种/来源时计算；
- 没有价格时只报 token，不报金额；
- 主会话共享段标 shared，不平均分摊；独立 session 可精确归因；
- 记录 cost_source（bill/price/estimate/unknown）。

## 5. 质量口径

- 总阻断数 = 前置检出 + review 检出 + close 后 escaped；不能只统计 review blocker；
- first_pass_acceptance、stable_first_pass、unknown/NA 分开；
- observation 与 defect 分开；final 重新 triage；
- findings 必须有 detected_phase/introduced_phase；无法判定标 unknown；
- 验证深度记录真实入口/状态/失败分支，不以静态检查代替。

## 6. 采集与输出

- 优先从 journal、session DB、git 自动生成；不能自动时标 manual 并记录脚本/人工时间；
- 主会话按阶段/任务窗口切分，不能切开的标 shared/unallocated；
- 每次试点至少 5 个匹配任务；样本不足只作方向性结论；
- 输出 top 时间/成本/finding 热点，并明确数据缺口；不要把 raw token 当金额。

### 输入生产（usage 从哪里来）

- 有会话数据库时优先用 `export_session_usage.py` 导出 request-level usage CSV（v1 支持 ZCode 本地库 `~/.zcode/cli/db/db.sqlite` 的 `model_usage` 表；Claude Code / Codex 为后续扩展，脚本对未支持来源快速失败）；
- 取不到会话库时手工产出最小集：实施记录登记参与 session id 清单与 token 总量，共享窗口标 shared/unallocated；
- task/phase map 按阶段起止或任务窗口生成；主会话共享段只能给 allocated 口径，不冒充 exact；
- 编排路径 close 门禁：work 目录缺 `metrics/`（或目录为空）会阻塞 close；usage 确实不可取得时写 `metrics/UNAVAILABLE.md` 说明原因即放行。

## 7. 最小采集脚本

~~~bash
python3 -B delivery/delivery-orchestrate/scripts/collect_metrics.py \
  --work <工作目录> --usage <请求级usage.csv> \
  --map <task_phase_map.csv> --output <metrics目录>
~~~

map CSV 字段：session_id,task_id,phase_id,weight。一个 session 对应多个 task/phase 时按 weight 分摊，标 shared_equal_or_weighted；未映射 session 输出到 unmapped。

脚本按 session 汇总 input/uncached/cache/output/duration，并输出 usage_by_session.csv、usage_by_task_phase.csv、metrics_summary.json。价格不是必需；没有价格时只报 token，不报金额。任务/阶段归因来自显式 map，不能由 session 名猜。
