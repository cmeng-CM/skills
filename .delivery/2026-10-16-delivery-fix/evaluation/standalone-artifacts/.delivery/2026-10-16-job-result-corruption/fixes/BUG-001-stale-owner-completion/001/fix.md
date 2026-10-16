# BUG-001：过期 owner 完成导致任务结果损坏 — 第 001 轮

| 文档说明 | 内容 |
| --- | --- |
| bug、轮次与任务范围 | BUG-001，001；依据本项目 README 诊断并修复 job-result corruption，父 agent `/root` 的受控独立能力委派，无正式任务 ID |
| 报告作者、时间与版本 | `/root/fix_standalone_forward`；2026-10-16T15:01:03.841536+08:00；报告 1.0，正式交接后固定 |
| 实施作者及成果归属 | 实际调查、queue_store.py 修复、4 项新增回归、探针及报告均由 `/root/fix_standalone_forward` 完成；父 agent `/root` 只提供本轮任务指令，未参与本项目代码修改。既有产品及 README 所述 prior attempt 的作者未提供，未核实，不视为空作者链 |
| 上下文标识 | 当前实际 agent canonical task `/root/fix_standalone_forward`；父上下文 `/root`；项目绝对路径 /private/var/folders/rp/10l3h8sd6mb_4z4lrwk4kk1c0000gn/T/delivery-fix-standalone-4i76gw3g；未获得可核实的额外会话 UUID，不编造 |
| skill 与契约 | 仅本项目 `.agents/skills/delivery-fix/SKILL.md`；契约版本 1；SKILL.md SHA-256 `7daff8e141e9646c1ea314dd9d61af7eb1b2083b2b5a503d9d17de93b7ce49d2`；实际读取的六项规则/骨架保存在 [skill-source](evidence/skill-source/)，逐文件指纹见 [baseline-manifest.json](evidence/baseline-manifest.json) |
| 输入与授权 | 本项目 README 内容指纹 `7130047ab768cb6382142a1c5df1a3f75afe80da40665c134057d56de30bae91`；委派明确授权 queue_store.py、必要新增回归及 .delivery 材料，保留公共 API、现有要求和现有测试，不提交、不 push、不调用其他 skill 或运行器、仅在本项目写入 |
| 产品基线 | 无 Git；修复前 queue_store.py SHA-256 `5dafb66963d6fa0d9b45fb8a917012df4c1ba824e0f668b46d030e2cb402fc98`；修复后 `638deb0d2074ff34c1738a48b50c1e69204681d350450ce3b5cf3477d95abea1`；[基线快照](evidence/baseline/)、[最终快照](evidence/final/)、[最终指纹](evidence/final-manifest.json)、[产品差异](evidence/product.diff) 可恢复实际对象 |
| 前次关联 | 初次检查项目仅 README、queue_store.py、tests 和 .agents，无 .delivery、无前轮报告。README 的延长租期尝试只有观察，没有前序报告或实施身份；未覆盖或篡改其历史 |

根因已有可重复证据支持：`complete` 仅检查 leased 状态，遗漏当前 owner 比较，旧 owner 因此写入 stale 结果并使当前 owner 后续完成失败。已在状态修改与保存之前增加 owner 检查，公共方法签名及文件格式保持兼容；7 项测试通过，前后探针显示拒绝操作零状态变化、正确结果重载保留。本结论只属于修复与作者自检，尚无独立审查或整体验收。

## 1. 问题与边界

README 要求 pending 可 claim、lease 到期可 reclaim、只有当前 lease owner 可完成；旧 owner 应返回 False 且不能改变内存或持久化状态；成功结果应在新 Queue 对象中存在；重复 enqueue 不覆盖运行中或已完成任务。现有代码可让已被替换的 worker 先提交 stale 结果，之后合法 owner 被 done 状态拒绝，错误结果持续留存在文件中。

本轮已明确授权落地修复，不需要变更要求或 API。仅修改 queue_store.py 的 complete 检查，新增相关测试；README 和 tests/test_queue.py 完全保留。未更改 lease 时长、claim 边界或验收标准。没有主动串联其他 skill、编排器或 Git 行为。

## 2. 现场与复现

环境：macOS 27.0.1 arm64，Python 3.9.6；详见 baseline-manifest.json。所有测试使用显式时钟、项目内临时目录，无 sleeps 或外部服务。`TMPDIR` 指向本轮 evidence/runtime-tmp，TemporaryDirectory 用完自动释放，`-B` 禁止字节码缓存。

稳定复现：enqueue job → worker-A 在 now=0、lease=10 claim → worker-B 在 now=10、lease=10 reclaim → worker-A complete stale。预期 False 且状态不变；基线测试返回 True。基线现有测试 3 项，1 项失败，退出码 1，原始输出 [baseline-tests.txt](evidence/baseline-tests.txt)。命令及退出码见 [baseline-command.json](evidence/baseline-command.json)。

诊断探针记录完整内存和文件：旧 owner 完成前 owner=B/state=leased/result=null，之后 owner=B/state=done/result=stale；B 的正确完成返回 False，新 Queue 仍读到 stale。详见 [causal-probe.py](evidence/causal-probe.py) 和 [before-probe.txt](evidence/before-probe.txt)。探针退出码 0 只表示记录程序执行完毕，并非修复通过。

## 3. 诊断过程

| 候选原因或实验 | 区分的问题与预期 | 实际证据 | 判断与限制 |
| --- | --- | --- | --- |
| 租期太短或边界错误 | 先检查现有 39/40 边界测试及确定性 reclaim | 基线边界测试通过；now=10 明确接管，owner 确为 B | 延长租期只改变触发概率，不能阻止接管后的非法完成；不把它当根因修复 |
| complete 缺失 owner 授权判断 | 检查真正修改状态和保存的调用点；对同一输入分别比较拒绝结果及完整状态 | complete 读取 job 后只检查 state；现有测试和探针均显示旧 owner 返回 True，内存/磁盘写入 stale | 直接因果证据支持；并非仅“测试变绿”推断 |
| 持久化恢复丢失结果 | 探针检查写入内容与新 Queue 读取是否一致 | 基线恢复一致读到 stale；修复后恢复一致读到 fresh | 此复现的错误写入发生在授权判断，未观察到恢复转换错误；没有扩展成对全部 I/O 故障的排除 |
| 补充回归并在旧产品运行 | 非 owner 未接管也应拒绝，连续接管后所有旧 owner 应拒绝，重复 enqueue 和 pending/done 拒绝应保全状态 | [before-expanded-tests.txt](evidence/before-expanded-tests.txt)：7 项，5 个失败记录，退出码 1（含连续 reclaim 的 subTest 和后续连带失败） | 新测试在未修复产品上暴露问题，保留了失败；其余相关边界维持通过 |
| 相同探针及同套测试在修复后执行 | 旧 owner 返回 False 且完整快照一致，当前 owner 能持久完成 | [after-probe.txt](evidence/after-probe.txt)；[after-tests.txt](evidence/after-tests.txt)：7 项全部通过，退出码 0 | 支持本轮修复及相关自检范围，不授予独立审查结论 |

基线原始输出中有 macOS 开发工具缓存/FSEvents 警告；实际测试运行完成，具体失败为 owner 断言，不是环境中断。未重试这些环境警告或更改机器设置。

## 4. 根因与修复选择

调用链为 claim 更新 owner 和 until 并保存 → 租约到期时后续 claim 覆盖 owner → 旧 worker 调用 complete → 旧实现只判断 leased，直接把结果改为 done 并保存。由于保存前没有比较传入 owner 与 job.owner，过期 worker 得到写权限，并阻塞正确 worker 的完成。探针同时捕获了违规返回值、违规状态变化和新实例读取的错误结果，对这一确定性路径构成直接证据。

修复在 complete 的 guard 中增加 `job["owner"] != owner`，与 state 条件一起在 update 和 _save 前返回 False。它截断非法写入来源，保留正常 owner 的持久完成路径，既不改变 API，也不需要更长租期或新参数。本轮为根因修复，不是租期缓解。

complete 没有 now 参数；本轮沿用以当前已记录 owner 判断归属的接口语义，没有自行加入时钟或改变 expiry 行为。多进程并发读写、同一个 owner 标识复用下的分代区分、文件写入中断或掉电恢复并非本轮已执行证据覆盖的条件；不据本次测试声称已验证。

## 5. 实际修改

| 实际成果 | 前后与作用点 | 位置及作者 | 处置 |
| --- | --- | --- | --- |
| complete 授权修复 | state 非 leased 或 owner 不匹配立即 False；任何 update/save 之前拒绝 | queue_store.py:29，`/root/fix_standalone_forward` | 正式保留；1 行产品改动，见 product.diff |
| 4 项回归 | 活跃租约非 owner；连续 reclaim 多旧 owner；运行中重复 enqueue；pending/done completion 拒绝；比较深拷贝内存及文件 bytes，并验证成功重载 | tests/test_owner_regression.py，`/root/fix_standalone_forward` | 正式保留；已在前后版本真实执行 |
| 诊断探针 | 同一时序记录非法写入和恢复，再在修复产品执行 | evidence/causal-probe.py，`/root/fix_standalone_forward` | 仅证据工具，未接入公共 API，无临时产品日志残留 |
| 报告及快照 | 规则来源、前后产品版本、失败及成功输出、作者和交接 | 本轮目录，`/root/fix_standalone_forward` | 正式交接材料 |

没有其他产品实验修改。现有 README 和 tests/test_queue.py 与基线逐 bytes 一致；对应指纹记录在前后 manifest。没有提交、push 或编排账本。

## 6. 自检与回归

| 检查 | 方法及实际版本 | 实际结果与原始证据 | 范围和限制 |
| --- | --- | --- | --- |
| 项目规定基线测试 | 未修复产品，`python3 -B -m unittest discover -s tests -v` | 3 项，1 失败，退出 1；baseline-tests.txt | 实际原故障复现，非新增案例定义 |
| 扩展回归基线 | 同命令，旧 queue_store.py + 新增测试 | 7 项，5 个失败记录，退出 1；before-expanded-tests.txt | 保留新测试识别问题的失败和连带影响 |
| 原故障前后探针 | `python3 -B <本轮evidence>/causal-probe.py`，PYTHONPATH=项目 | before-probe.txt 与 after-probe.txt；两次探针进程退出 0 | 修复后 stale_return=false，快照一致，current_return=true，restart.result=fresh；探针成功退出本身不代表验收 |
| 项目规定最终自检 | 修复后产品 + 4 项新增测试，同 discover 命令 | 7 项全部通过，退出 0；after-tests.txt；after-tests-command.json | 覆盖当前 owner、过期接管、39/40 边界、pending/done、重复 enqueue、成功新实例重载、拒绝内存/文件不变；作者自检 |
| 范围与身份核验 | 前后 bytes 比较及 SHA-256，保存完整快照 | final-manifest.json、product.diff；README 与现有测试相同 | 证明相关文件未被削弱；没有 Git，因此用快照和指纹标识实际产品 |

所有执行命令、cwd、退出码、TMPDIR 记录在对应 `*-command.json`；实际输出未经摘除失败或替换。未执行独立审查、真实多进程并发或整体验收。

## 7. 续接与交接

根因有直接、可重复证据支持，正式修复及相关回归已形成，7 项作者自检通过。本轮材料可供调用方检查来源、版本和作者后接入下游；并不自动接纳为独立审查或交付验收通过。

无本轮已知失败遗留，无待回执命令、后台进程或持有资源。项目内队列测试临时目录已由 TemporaryDirectory 清理。最终核验发现 runtime-tmp 并非空目录：保留系统 Python 启动时生成的 `xcrun_db`（1087 bytes）作为已知项目内环境副产物，未将其当作队列产品状态或删除现场；见 evidence/artifact-checks.json 和 evidence/runtime-residuals.json。无外部服务、真实业务数据或产品临时日志。无 Git 仓库，无提交或 push。既有产品和历史缓解作者不明是作者链缺口，后续独立性核对须保留，不能写作无人参与。

下一项有信息价值的动作是由调用方安排具备独立性的审查者，核对 README 语义、owner guard 的位置及本轮前后证据；本执行者不替其下结论。恢复时先比对 final-manifest.json 与实际文件，确认没有新修改或未回执操作。本轮交接后保留不覆盖；同问题后续活动沿用本 bug 目录建立 002 关联轮次。
