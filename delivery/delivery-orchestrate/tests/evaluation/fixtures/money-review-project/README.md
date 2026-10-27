# 本地账本命令

使用 `python3 app.py transactions.json` 读取JSON交易列表，输出按币种排序的收入、支出和净额。kind为income/expense；amount为十进制正数字符串，允许0至2位小数，整数部分不超过18位；currency为非空字符串，未知币种独立处理。结果金额为两位小数字符串；空列表输出{}。

无效金额、非正数、缺kind/未知kind和非列表输入须非零退出，stdout不得留下部分汇总。禁止引入第三方依赖、网络和数据库。

`history/` 保留前次实现，`review/001.md` 是原问题记录；当前 `money.py`、`app.py` 是本次复审对象。实施者交接说明见 implementation.md。测试命令为 `python3 -B -m unittest discover -s tests -v`。本次只要求复审，禁止直接改产品和测试。
