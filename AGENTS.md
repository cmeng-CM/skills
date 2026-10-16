# AGENTS.md

## 仓库定位

本仓库维护可独立安装的 agent skills。主体是带 YAML frontmatter 的 `SKILL.md`，按需附带参考文档、模板、脚本与测试。各 skill 自包含，不依赖兄弟包的共享代码；没有仓库级统一构建或依赖安装命令。

## 目录与入口

| 位置 | 用途 |
| --- | --- |
| 根目录各 `<skill>/SKILL.md` | 独立 skill 的触发范围、操作规则和资源入口 |
| `delivery/delivery-*/` | 五项基础专业能力、可选复杂修复能力及一个编排 skill；组合方式见 [delivery/README.md](delivery/README.md) |
| `references/`、`assets/`、`scripts/`、`tests/` | 各 skill 按需设置的参考资料、模板资源、工具和测试，不要求每包都有 |
| [模板.md](模板.md) | skill 编写模板；模板调整与实际 skill 改动分别确定范围 |
| [设计规范](delivery/delivery-design/references/document-standard.md)、[规划规范](delivery/delivery-plan/references/plan-standard.md) | 分别由新设计、规划 skill 维护，修改真源，不另建副本 |
| `docs/designs/`、`docs/plans/` | 设计与计划资料；是否适用于当前改动须结合文档范围和实际实现判断 |
| `.delivery/`、`.workflow/`、历史 `docs/delivery/` | 任务材料、执行状态或验证证据；不是 skill 源码包 |
| [README.md](README.md) | 安装、卸载与本机 `skill` shell 函数说明 |

## 修改原则

- 先读目标 skill 的 `SKILL.md`，再按引用读取相关规范、脚本和测试。审阅或方案讨论只读；实施范围以用户请求为准。
- 简单文档维护采用检查、修改、核验，不自动创建完整工作流、派子 agent 或提交。用户选择某个执行流程时，遵循该流程的具体约定。
- 修改 skill 时同时检查触发描述、正文、引用资源和测试是否一致；涉及行为改变时核对典型场景、边界和不应触发的场景。
- 技术设计和实现规划统一使用 `delivery-design`、`delivery-plan`，普通对应请求即可触发；单项调用不自动进入完整编排。新目标产物放在 `.delivery/日期-主题/`，同目标沿用已有明确目录。
- `delivery-*` 与保留的 `task-workflow` 各自维护；修改其中一组不自动同步另一组，不改写旧执行状态或历史。Delivery 的兼容与升级规则见 [maintenance.md](delivery/delivery-orchestrate/references/maintenance.md)。
- 历史方案、评审结论、执行记录和证据保留当时的语义，不因当前入口改名或规则调整而批量替换。新结论应说明适用版本与证据范围。
- `.delivery/`、`.workflow/` 仅保存在本地，不加入 Git；取消跟踪时保留本地文件，历史提交不改写。
- 客户端支持、字段长度、工具依赖等结论应注明适用范围；不把单个客户端的实现细节写成所有运行环境的保证。修改既有约束时同步核对实际检查器。

## 脚本与依赖

- 辅助代码以 Python 3 和 Bash 为主。Python 优先标准库；新增外部依赖在所属 skill 中声明，不为单包改动引入仓库级依赖体系。
- 根目录安装与卸载脚本使用 `set -euo pipefail`，通过 `bash` 执行，不要 `source`。
- `folo/` 使用自己的 CLI 和版本约定。具体依赖、环境选择和命令以目标 `SKILL.md` 为准。

## 安装与卸载

```bash
bash install-skill.sh <skill目录>
bash install-skill.sh delivery/delivery-plan
bash uninstall-skill.sh <skill名或路径>
```

- 安装器将指定包软链接到 `~/.claude/skills/` 和 `~/.agents/skills/`，名称取包目录的 basename。
- 安装器会删除同名旧目标后重建链接，卸载器也会删除同名实际目录或文件；执行前核对目标，保全不属于本次操作的内容。
- 保留现有绝对路径处理和先删除再建链接的语义，不直接改成 `ln -sfn`：目标为真实目录时可能把链接建进目录内部。
- 软链接使安装位置指向当前源码，无需重复复制；已运行客户端是否重新加载、活动任务采用哪个版本，仍须按客户端与流程规则确认。

## 验证方式

按改动对象选择验证，不设统一评分引擎、分数阈值或测试文件名。现有 `test-prompts.json`、`tests/behavior-cases.json` 和 Python 单元测试均按各包用途维护。

- **仅文档或导航改动**：检查内容与实际实现一致、相对链接可达、旧入口引用已处理，并运行 `git diff --check`；不为此启动全仓库模型评测。
- **Python 工具改动**：运行受影响包已有的单元测试；没有现成测试时，按行为风险选择可复现的验证，不把语法检查当成功能通过。
- **skill 行为改动**：用相关案例检查触发与实际结果；新增案例文件只表示定义了案例，不能算已执行。真实模型评测记录模型、输入、skill 版本、实际产物及限制；对照实验隔离评审答案。
- **Delivery**：结构检查、确定性回归、模型行为、独立审查和实际交付验证分别留证，不能互相替代。运行方式见 [维护与证据](delivery/README.md#维护与证据)和[真实行为评测](delivery/delivery-orchestrate/tests/evaluation/README.md)。

已有单元测试使用以下命令，按改动选择对应目录：

```bash
python3 -B -m unittest discover -s <skill目录>/tests -p 'test_*.py' -v
```

适用目录包括 `task-workflow`、`delivery/delivery-design`、`delivery/delivery-plan`、`delivery/delivery-orchestrate`。不要把仅有行为案例 JSON 的目录当作已运行单元测试。

文档检查器和包结构检查器只证明各自声明的机械条件；通过不等于语义正确、模型执行有效或用户验收完成。汇报时说明实际运行了什么、覆盖什么，以及仍未验证什么。
