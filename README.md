# skills

Claude Code / Codex / OpenCode 的 skill 集合仓库。每个 skill 以 `SKILL.md`（prompt-as-code）为主体、各自自包含，skill 之间无共享代码。写 skill 遵循 [`模板.md`](模板.md) 的四段式规范。

## 安装与卸载

仓库提供两个脚本，把指定 skill 以**软链接**方式安装到四个客户端目录：
`~/.claude/skills`（Claude Code）、`~/.codex/skills`（Codex）、`~/.config/opencode/skills`（OpenCode），以及跨工具标准路径 `~/.agents/skills`（ZCode 等读这里）。

- [`install-skill.sh`](install-skill.sh) — 安装 / 覆盖安装一个 skill
- [`uninstall-skill.sh`](uninstall-skill.sh) — 从四个客户端目录移除一个 skill

软链接的好处：**改源即生效**。skill 随时在仓库里更新，无需重新安装，各客户端立刻看到最新内容。

### 直接调用

```bash
# 在仓库根目录下
./install-skill.sh <skill 目录路径>
./uninstall-skill.sh <skill 名称或路径>
```

### 推荐用法：`skill` 命令（zshrc 函数）

每次都 `cd` 到脚本目录、还要拼 skill 的绝对路径，太繁琐。在 `~/.zshrc` 里加一个 `skill` 函数，即可在**任意目录**用 `install / remove / list` 三个子命令调用本仓库的脚本：

```zsh
# skill 安装/卸载/列表：任意目录可用，调用 skills 仓库的脚本
skill() {
  local repo="$HOME/workspace/github/skills"
  local cmd="$1"
  local clients=(
    "$HOME/.claude/skills"
    "$HOME/.codex/skills"
    "$HOME/.config/opencode/skills"
    "$HOME/.agents/skills"
  )
  case "$cmd" in
    install)
      [ $# -ge 2 ] || { echo "用法: skill install <skill 目录的绝对路径>"; return 1; }
      bash "$repo/install-skill.sh" "$2"
      ;;
    remove|uninstall)
      [ $# -ge 2 ] || { echo "用法: skill remove <skill 目录的绝对路径或名称>"; return 1; }
      bash "$repo/uninstall-skill.sh" "$2"
      ;;
    list)
      local dir entry name target found
      for dir in "${clients[@]}"; do
        echo "## $dir"
        [ -d "$dir" ] || { echo "  (目录不存在)"; echo; continue; }
        found=0
        for entry in "$dir"/*(N); do
          [ -e "$entry" ] || [ -L "$entry" ] || continue
          found=1
          name="${entry:t}"
          if [ -L "$entry" ]; then
            target="${entry:A}"
            printf "  %-20s -> %s\n" "$name" "$target"
          else
            printf "  %-20s (实际目录)\n" "$name"
          fi
        done
        (( found )) || echo "  (空)"
        echo
      done
      ;;
    *)
      echo "用法:"
      echo "  skill install <skill 目录的绝对路径>     # 安装/覆盖安装到四个客户端目录"
      echo "  skill remove  <skill 路径或名称>        # 从四个客户端目录卸载"
      echo "  skill list                               # 列出四个客户端目录已装的 skill"
      return 1
      ;;
  esac
}
```

加载后即可使用：

```bash
source ~/.zshrc

skill install /Users/cm/workspace/github/skills/delve
skill remove  /Users/cm/workspace/github/skills/delve
skill remove  delve          # remove 也支持只写名称
skill list
```

实现要点：
- 用 `bash` 调用而非 `source`——脚本里 `set -euo pipefail` 配 `exit`，`source` 会让 `exit` 关掉当前终端。
- `install` 走脚本的"传相对路径也会自动转绝对路径"逻辑，所以传相对路径同样可用。
- `remove` 用脚本里的 `basename` 取名，传绝对路径或纯名称都能卸载。
- `list` 用 zsh glob `*(N)` 处理空目录，软链接显示 `-> 源目录`，git clone 的真实目录显示 `(实际目录)`。

### 关于"全局命令"的取舍

`skill` 函数定义在 `~/.zshrc` 里，仅 zsh 交互式 shell 可用；若将来要给团队分发、或想在 bash / 脚本 / 非交互环境也能调，可把这段函数改写成一个带 `#!/usr/bin/env bash` 的 `skill.sh`，再软链到 `~/.local/bin/skill`——逻辑一行不用改，只是换个"住址"。详见 [`CLAUDE.md`](CLAUDE.md)。
