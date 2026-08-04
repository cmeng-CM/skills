# CLAUDE.md

## 仓库性质

Claude Code / Codex / OpenCode 的 skill 集合仓库。每个 skill 以 `SKILL.md`（prompt-as-code）为主体、各自自包含，skill 之间无共享代码；没有 package.json / pyproject.toml 等依赖清单，依赖在 SKILL.md 正文里以文字说明。

## 技术栈

- 主体：Markdown（YAML frontmatter + 正文行为协议）
- 辅助脚本：Bash（一律 `set -euo pipefail`）、Python 3（标准库优先；仅 md2docx 额外需要 `python-docx`）
- 外部工具（仅改 md2docx 时需要）：`pandoc`（必须）、`node`/`npx` + `mmdc`（mermaid 渲染，可选）

## 结构与入口

- `skills/` 下一 skill 一目录，入口即 `SKILL.md`。写 skill 遵循 `skills/模板.md` 的四段式：frontmatter → 一句话定场 → Working Protocol → Exit Criteria → Exit Protocol；正文超 500 行就拆到 `references/`
- 安装：`skills/install-skill.sh <skill 目录>`（软链到三个客户端的 skills 目录）；卸载：`skills/uninstall-skill.sh <skill 名或路径>`
- 无构建、无测试框架：质量验证靠各 skill 的 `test-prompts.json`（`[{id, prompt, expected}]` 格式）配合 darwin-skill 打分；验收标准与执行规程见 `skills/基线测试.md`（≥80 合格，70-80 有短板，<70 需优化）

## 坑点

- 安装名以**目录名**为准（脚本取 basename）；`md2docx/` 的 frontmatter `name: md-to-docx` 与目录名不一致，改它不影响安装名
- 安装脚本的 `rm -rf` + `ln -s` 两步写法、绝对路径转换都不要改（不要"优化"成 `ln -sfn` 或相对路径）：目标是真实目录时 `ln -sfn` 会把链接建进目录内部，相对路径目标会断链
- Python 脚本最小依赖原则：优先纯标准库；浏览器渲染等重能力默认 opt-in
- `README.md` 是空占位，仓库级说明实际在各 SKILL.md 与 `skills/模板.md` 里
- 遗留路径痕迹：旧脚本/settings 引用 `tools/skill/`（单数），现为 `tools/skills/`，遇到历史路径先核对
