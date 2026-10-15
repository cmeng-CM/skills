请只用 delivery-plan 正式保存实现计划。当前项目只有 label.py，没有独立技术方案，没有 .workflow 或编排器。
已确认要求：label 增加 keyword-only 参数 prefix: str = ""，输出为 prefix + text.strip()。prefix 原样保留，无自动分隔符。旧调用输出不变。输入类型由调用者保证，不增加 I/O、UI 或依赖。上述机制由模型提出，用户在本请求明确确认，理由是调用方控制排版。测试需要覆盖旧调用、带空白前缀、空正文、中文。不授权实施或运行产品测试。一次细化完整。
