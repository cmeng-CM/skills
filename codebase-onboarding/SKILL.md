---
name: codebase-onboarding
description: Scan a codebase for stack, entry points and conventions, then write/refresh its knowledge file — AGENTS.md (+CLAUDE.md/GEMINI.md aliases). Use on a project without one, on 帮我理解这个项目 / 生成 AGENTS.md, or when stale.
---

# Codebase Onboarding

生成或刷新项目认知文件（默认以 AGENTS.md 为跨工具真源，落地形式见 Step 4）。这份 skill 只做一件事:把"认知这个项目"这个动作从每次对话里剥离出来，做一次，落成文件，然后退出——认知本身此后由认知文件常驻承载，不再需要这个 skill 重复工作。

## Working Protocol

### Step 0: 判断是否真的需要跑一遍

先检查缓存标记 `.git/claude-onboard.md`（如果存在）。用 `scripts/check_cache.sh` 读取里面记录的 git HEAD SHA，和当前 `git rev-parse HEAD` 比对：

- SHA 一致 → 缓存仍然有效，直接读取已有认知文件内容展示给用户，说明"项目认知是最新的"，跳过下面所有步骤，直接进 Exit
- SHA 不一致 / 没有缓存 / 用户明确要求强制刷新 → 继续 Step 1

### Step 1: 派发 subagent 做扫描，不要在主会话里直接读

如果当前环境支持 subagent（Task tool 可用），把扫描工作整体委派给一个独立的 subagent（见 `references/scanner_prompt.md` 里的完整派发指令模板），而不是在主对话里逐个 `view`/`cat` 文件。

目的是上下文隔离：扫描要碰几十个文件，中间的试错、误读、重新定位都应留在 subagent 里，主会话只收最后的结构化摘要。

如果当前环境不支持 subagent，直接在主会话里按 Step 2 的分层策略读取，但读取范围要比 subagent 模式收得更紧——优先保证覆盖面，而不是每个文件都读全。

### Step 2: 分层采样，不要遍历全部文件

无论是 subagent 内部执行还是主会话直接执行，都遵循同一个采样顺序，越靠前的越必读：

1. **Manifest 层**（必读）：`README*`、`package.json` / `pom.xml` / `pyproject.toml` / `Cargo.toml` / `go.mod`、`Makefile`、已有的项目认知文件（`AGENTS.md` / `CLAUDE.md`，如果存在，先读它——不要在没看过旧版本的情况下直接覆盖）
2. **入口层**（必读）：`main.*` / `app.*` / `index.*` / 框架约定的启动文件（如 Spring Boot 的 `*Application.java`、FastAPI 的 `main.py`）、路由/控制器的顶层目录
3. **约定层**（抽样）：目录结构本身（用 `tree` 或 `ls -R` 代替逐个打开）、`.editorconfig` / lint 配置 / CI 配置文件，用来判断代码风格约定，而不是靠读多个业务文件去猜
4. **代表性源码**（抽样，2-4个文件即可）：从入口层顺着调用链挑1-2个典型模块，用来验证前三层猜测的架构是否成立，不追求覆盖率

分层的原因：项目认知需要的是"结构性理解"，不是"逐行理解"。manifest 和目录结构给出的信息密度远高于随机打开业务代码文件，把预算优先花在信息密度最高的地方。

### Step 3: 生成结构化摘要

扫描结束后，产出摘要，固定包含这几块（对应 `references/summary_template.md`）：

- **项目简介**：这个项目做什么，一两句话
- **技术栈**：语言、框架、关键依赖，版本如果能确定就带上
- **目录结构**：树状展示，只到能说明架构分层的深度，不需要展开到每个文件
- **关键入口点**：启动命令、主入口文件、如果是服务类项目则包括暴露的接口层
- **架构说明**：模块之间怎么连接、数据怎么流动、用了什么模式（如果能识别出来，比如分层架构/事件驱动/CQRS）
- **约定与坑点**：命名规范、测试怎么跑、已知的特殊处理逻辑

### Step 4: 写入 / 增量更新项目认知文件

先按项目现状决定落地形式，再动手：

- **A. 已有 `AGENTS.md`**（无论真实文件还是 symlink）：以它为目标，增量更新。
- **B. 没有 `AGENTS.md`，但有真实的 `CLAUDE.md`**（不是链接）：用户可能是故意只维护 Claude 专属配置——以 `CLAUDE.md` 为目标原地更新，不要擅自改成 symlink；同时在对话里提一句："检测到当前只有 CLAUDE.md，如果你也在用其他 agent 工具（Gemini CLI / Cursor 等），可以考虑改成 AGENTS.md 为真源、CLAUDE.md 做 symlink 指向它，需要的话我可以帮你转换"——给建议，不擅自做主。
- **C. 什么都没有**（新项目）：新建 `AGENTS.md` 作为真源，并在同目录创建 `CLAUDE.md`、`GEMINI.md` 两个 symlink 指向它（`ln -s AGENTS.md CLAUDE.md` / `ln -s AGENTS.md GEMINI.md`；同目录相对链接，仓库整体移动也不会断）。

目标文件确定后：

- 目标不存在（分支 C）：直接用摘要生成一份新的，控制在 500 词以内，只留 Step 3 里对下一次干活真正有用的部分——技术栈、入口点、命令、架构要点、坑点。不要把摘要里的完整背景介绍照搬进去，摘要是给人看的，认知文件是给模型下次直接用的。
- 目标已存在（分支 A/B）：先完整读一遍原文件，保留其中已经存在的项目专属指令（尤其是团队手写的行为约束，比如"不要修改 src/legacy/"这类），只在确实过时或缺失的地方做增补，并且明确用一行注释或对话里的文字标注"新增/修改了哪些部分"，不要静默覆盖用户已经维护的内容。

条目按读者视角措辞：摘要记录的是"发现了什么"，进认知文件时每条都要改写给下次干活的模型——先想"读者在什么情况下会碰到它、此刻该做什么/别做什么"，把这个结论写在前面，发现的事实只作为结论后面的原因说明保留。

### Step 5: 写入缓存标记

用 `scripts/write_cache.sh` 把当前 `git rev-parse HEAD`、分支名、时间戳写入 `.git/claude-onboard.md`。这一步决定了下一次打开项目时 Step 0 能不能命中缓存，跳过这一步等于让整个缓存机制失效。

## Exit Criteria

以下条件全部满足才算完成，不满足任何一条都不能进入 Exit Protocol：

- [ ] 项目认知文件（AGENTS.md，或用户明确保留的独立 CLAUDE.md）存在，且内容覆盖了技术栈 / 入口点 / 命令 / 架构要点 / 坑点这五项
- [ ] 如果原来就有认知文件，已有的项目专属指令没有被静默覆盖
- [ ] `.git/claude-onboard.md` 已写入，且 SHA 与当前 HEAD 一致
- [ ] 摘要已经展示给用户过目，不是直接落盘就结束

## Exit Protocol

1. 把最终的认知文件内容（或 diff，如果是增量更新）展示给用户
2. 一句话说明缓存已生效："下次打开这个项目，如果代码没变，会直接复用这份认知，不会重新扫描"
3. 结束，不主动进入下一个任务——这是一次性 setup skill，认知构建完成后应该让出主会话给真正的开发任务
