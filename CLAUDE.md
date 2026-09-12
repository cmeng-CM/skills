# CLAUDE.md

## 仓库性质

Claude Code / Codex / OpenCode 的 skill 集合仓库。每个 skill 以 `SKILL.md`（prompt-as-code）为主体、各自自包含，skill 之间无共享代码；没有 package.json / pyproject.toml 等依赖清单，依赖在 SKILL.md 正文里以文字说明。

## 技术栈

- 主体：Markdown（YAML frontmatter + 正文行为协议）
- 辅助脚本：Bash（一律 `set -euo pipefail`）、Python 3（标准库优先；仅 md2docx 额外需要 `python-docx`）
- 外部工具（仅改 md2docx 时需要）：`pandoc`（必须）、`node`/`npx` + `mmdc`（mermaid 渲染，可选）

## 结构与入口

- 仓库根下一 skill 一目录，入口即 `SKILL.md`。写 skill 遵循 `模板.md` 的四段式：frontmatter → 一句话定场 → Working Protocol → Exit Criteria → Exit Protocol；正文超 500 行就拆到 `references/`
- 安装：`install-skill.sh <skill 目录>`（软链到 `~/.claude/skills` 与 `~/.agents/skills` 两个目录）；卸载：`uninstall-skill.sh <skill 名或路径>`
- 无构建、无测试框架：质量验证靠各 skill 的 `test-prompts.json`（`[{id, prompt, expected}]` 格式）配合 darwin-skill 打分；验收标准与执行规程见 `基线测试.md`（≥80 合格，70-80 有短板，<70 需优化）

## 坑点

- 安装名以**目录名**为准（脚本取 basename）；`md2docx/` 的 frontmatter `name: md-to-docx` 与目录名不一致，改它不影响安装名
- 安装脚本的 `rm -rf` + `ln -s` 两步写法、绝对路径转换都不要改（不要"优化"成 `ln -sfn` 或相对路径）：目标是真实目录时 `ln -sfn` 会把链接建进目录内部，相对路径目标会断链
- 两个安装目标里 `~/.agents/skills` 是跨工具标准路径——**ZCode / Codex / pi 都读这里**（Codex 源码 `core-skills/src/loader.rs` 的 `AGENTS_DIR_NAME = ".agents"`），`~/.claude/skills` 只给 Claude Code。只装后者会让 skill 在其余客户端全部不可见
- Python 脚本最小依赖原则：优先纯标准库；浏览器渲染等重能力默认 opt-in
- 仓库级安装/卸载与 `skill` 函数说明在 `README.md`，写 skill 的规范在 `模板.md`
- 遗留路径痕迹：旧脚本/settings 引用 `tools/skill/`（单数）与 `tools/skills/`，现已去 tools 层级、skill 直接放仓库根，遇到历史路径先核对
