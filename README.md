# skills

可独立安装的 agent skills 集合。每个包以 `SKILL.md` 为主体，按需附带参考文档、资源和脚本。维护约定见 [AGENTS.md](AGENTS.md)，编写模板见 [模板.md](模板.md)。Delivery 的专业能力与编排入口位于 [delivery/](delivery/README.md)，安装名称保持 `delivery-*`。

技术方案和实现规划分别统一使用 [`delivery-design`](delivery/delivery-design/SKILL.md) 与 [`delivery-plan`](delivery/delivery-plan/SKILL.md)，普通设计、规划请求即可使用，无需先启动完整编排。新目标分别保存为同一任务目录中的 `design.md`、`plan.md`；已有明确归属的目标继续沿用原目录。旧 `design-tech-doc`、`plan-implementation` 已退役，历史文档、快照和运行记录保留。

`.delivery/`、`.workflow/` 是仅本地保留的任务材料和执行记录目录，不纳入 Git；已有历史提交不改写。

## 本地管理

在任意目录输入 `skill`，总览两处安装目录的全部 skill：按来源分三组展示——「仓库 · 自建」（本仓库源码，i / r 可管理）、「自建 · Obsidian Vault」（软链到 Obsidian 库，只读）、「外部 · 独立安装」（厂商或独立安装的真实目录，只读），并按编号操作：

```text
skills 总览 · 31 项｜仓库 14 · Vault 11 · 外部 6｜Claude 27 · Agents 26
状态表示文件连接，不代表客户端已重新加载；组内两端都在 → 仅一端 → 未安装

仓库 · 自建 14 项 · i / r 可管理
  1   delve                     两端已连接
  2   mineru                    未安装

自建 · Obsidian Vault 11 项 · 只读，v 看来源
 15   folo                      两端链接 → 61-skills/folo
 24   folo-collection-pull      Claude 链接失效 · Agents 未安装

外部 · 独立安装 6 项 · 只读，不改动
 26   agent-reach               两端独立 ⚠ 各一份
 31   find-skills               仅 Agents 独立

i 安装  r 卸载  v 详情  /关键词 筛选  q 退出 · i / r 仅接受「仓库」组编号
输入操作和编号，例如 i 12、v 26：
```

两端状态一致时合并为一句（两端已连接 / 未安装 / 两端链接 → 目标 / 两端独立 ⚠ 各一份）；不一致时按端分开说（仅 Claude 已连接、Claude 共享 · Agents 独立等），异常端跟在正常端之后。组内排序为两端都在 → 仅一端 → 未安装。`v` 详情展示来源分组、两端链接目标、说明，外部双份副本附带 SKILL.md 哈希比对。列表编号以当前屏幕为准；筛选后重新编号。`i 1 2` 批量安装，`r 1 2` 批量卸载，`/` 清除筛选。修改前预览并确认一次，默认操作两处；取消不写入。没有交互终端时，裸命令只输出状态。

也可以按名称直接执行，不再确认：

```bash
skill status
skill status --json
skill install delve delivery-plan
skill remove delve
skill install delve --target claude
skill install delve --dry-run
skill --help
```

`--target claude|agents|all` 默认 `all`，`--dry-run` 不创建目录或锁文件。`status --json` 输出机器可读状态（来源 origin、每端 state、双份独立警告）。`list` 是 `status` 的别名，`uninstall` 是 `remove` 的别名。源码目录变化后，按名称操作无需记住嵌套路径。

## 安装方式与状态

管理器把源码直接软链接到 `~/.claude/skills` 和 `~/.agents/skills`。修改源码无需重新复制；已运行客户端是否重新加载，取决于各自的发现、配置和缓存规则。

| 状态 | 含义与处理 |
| --- | --- |
| 已连接 | 正确指向当前源码；重复安装不重建链接 |
| 未安装 | 该处没有安装目标；安装时补链 |
| 链接失效 | 可识别的本仓库旧链接没有指向当前源码；安装时修复。Vault 链接目标不存在时同样标注 |
| 源已删除 | 仍有所属链接，但有效源码不存在；允许卸载残留 |
| 同名冲突 | 实际文件、目录、外部链接或无法认定的目标；拒绝覆盖和删除 |
| 检查错误 | 无法读取或检查；报错，不当作未安装 |
| 链接 → 目标 | Vault 或其他来源的软链；所属组只读 |
| 独立 / 共享 | 外部真实目录；两端独立副本标 ⚠ 各一份，详情附 SKILL.md 哈希比对 |

只发现根目录及 `delivery/` 的直接子包，历史快照和归档不进入安装目录。展示层额外只读列出两处安装目录中的 Vault 链接与外部条目；`i` / `r` 仅作用于「仓库」组，外部技能不纳入管理，同名时显示冲突。卸载只移除所属链接，保留源码。首版没有强制覆盖、远程下载、版本管理或自动搬家迁移。对两处安装目录的安装、卸载与链接调整一律通过 `skill` 完成，不手写链接或直写目录。

批量操作先整批检查；有冲突则不开始。中途失败会停止后续写入，报告已完成、失败及未执行项；再次执行会跳过正确链接并补齐缺失。两处目录之间不提供整体回滚。

## 命令入口

核心为仓库根目录可执行文件 [skill](skill)，只使用 Python 3 标准库，面向当前 macOS/POSIX 环境。仓库内可直接运行：

```bash
./skill
./skill status
```

全局入口使用 `~/.local/bin/skill` 到仓库 `skill` 的链接，终端 PATH 需要包含 `~/.local/bin`。旧 `.zshrc` 中的 `skill()` 函数应移除，否则会遮蔽新命令；已有终端请重新打开，或执行 `unfunction skill`。只重新 source 配置不会删除内存中的旧函数。

只使用 `skill` 入口，也支持合法的本仓库源码路径：

```bash
./skill install delivery/delivery-plan
./skill remove delve
```

支持绝对路径、加引号的含空格路径和额外选项。原安装、卸载 shell 脚本已移除；外部路径安装、仅取外部路径 basename 卸载、删除同名真实内容的旧行为不再支持。

## 验证与设计

```bash
python3 -B -m unittest discover -s tests -p 'test_skill_manager.py' -v
```

测试注入隔离源码、安装目录和锁路径，不修改本机真实安装；临时目录在测试结束后自动清理。覆盖发现范围、状态、保护、幂等、失败恢复、菜单、路径参数及真实 PTY 交互。测试源码保留用于后续回归。设计与交付记录见 [技术方案](docs/designs/local-skill-manager.md) 和 [实现计划](docs/plans/local-skill-manager.md)。
