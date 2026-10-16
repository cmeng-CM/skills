# 源码目录与安装入口迁移记录

版本 1；2026-10-16；作者 `/root`，上下文 `implementation-controller`。生成能力 delivery-implement，专业契约 1；实际规则来源 `evidence/baseline/sources/delivery-implement/`。覆盖 T-03 的实施交接，不代表 AC-03 的独立调用已验收。

六个根目录 delivery-* 包已整体移动至 `delivery/` 同名子目录。搬迁时 53 个源文件内容摘要完全不变；没有移动 `.delivery`、历史 `docs/delivery` 或 `.workflow`。迁移清单见 `evidence/migration/move.json`。

两个安装目录的 12 个原软链已重新指向新包根，调用名称保持 delivery-*。操作前确认全部目标仍是基线原软链，再复用现有安装脚本；没有覆盖未知实际目录。实际命令结果见 `evidence/migration/install.json`。

`professional_skills` 的独立只读检查确认：53 个源文件一致、439 个保护对象一致、根目录无旧活动副本、包内所有普通 Markdown 链接存在且未越出单包。安装完成后的复核将另外留存。

包检查通过：六包、35 份 Markdown、5 份 JSON、48 个普通本地链接。三个原回归共 121 项通过，原始结果见基线测试目录。后续规范/引擎修改将按其实际版本重新审查验证；V-06 才证明单包实际调用。

本地提交尚未执行；后续按边界提交并核对保护清单，不 push。
