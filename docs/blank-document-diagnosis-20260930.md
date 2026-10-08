# DOCX 打开空白、字符为 0：外网验证记录

排查时间：2026-09-29 至 2026-09-30。

## 当前结论

使用已有液冷数据，在外网完成了生成、下载、审阅基线、Linux 容器运行和 Microsoft Word 实际打开测试，未复现“打开空白、字符为 0”。现场文件仍在内网，因此这些结果不能证明现场文件正常，也不足以确定现场故障原因。本轮没有修改生产代码，新增的探针只位于 runtime 调试目录。

截图中的输入“匹配分：0”是预检评分，不是生成 DOCX 的字符统计。“下载未通过文件（仅供复核）”表示交付门禁状态；实测该状态不会清空文件正文。

## 已执行验证

| 验证环节 | 方法 | 结果 |
| --- | --- | --- |
| 文件结构 | 检查历史生成件及回放件的 ZIP CRC、XML、正文节点、关系目标、兼容性命名空间 | 均正常；正文非空，无全隐藏或删除正文 |
| 实际下载接口 | FastAPI TestClient 调用真实下载路由，3 份样例均以 blocked 状态下载 | 下载件与源件 SHA256 完全相同，正文分别 10,389 / 11,023 / 10,999 个 XML 文本字符 |
| 审阅基线 | 调用实际审阅路径并下载归档基线 | 基线与源件逐字节一致，投影包含 367 / 375 / 365 个内容块 |
| Microsoft Word | 独立隐藏 Word 16.0 实例只读打开历史生成件与两份回放件，导出 PDF | Characters.Count 分别为 12,411 / 13,089 / 13,089，均打开成功 |
| Linux 生成 | 已有 9/23 镜像提供 Linux 运行环境，挂载当前源码、原输入及记录的模型决策，禁用网络重新执行确定性生成 | approved；9,046,921 字节，正文 XML 字符 10,999，100 个媒体文件 |
| Linux DOC 转换 | 用容器内 LibreOffice 单独转换原始 YLZJ-BG-469 需求 DOC | 转换成功，正文 XML 字符 6,655，24 个表格，102 个媒体文件 |
| Linux 生成件在 Word 打开 | 将本次 Linux 生成件独立复制后，在 Word 16.0 中只读打开、导出 PDF | 13,089 个 Word 字符，108 个行内图片；抽查渲染页面可见标题、正文、图片和图题 |
| 现有相关测试 | 审阅存储、审阅文档、SPA/API 路由测试 | 44 passed |

Word 字符统计包含控制字符，与 XML 纯文本统计口径不同；两者均明确非 0。媒体文件数与图片引用次数也不必相同。

## 验证边界

- Linux 完整生成回放使用此前记录的分类与语义决策，未重新调用内网 Qwen；因此不能代表本次内网模型返回了相同决策。
- Linux 原始 DOC 转换另行验证。完整回放采用此前 Word 转换后的同一份标准化输入，以保持记录中的来源 ID 有效，未将旧来源 ID 强行套用到 LibreOffice 转换产生的新 XML。
- 当前本机只有 Word 16.0，未验证现场 Office 版本、现场额外代理及实际下载文件的字节。
- 下载接口目前验证任务状态、目录、后缀和文件存在性，不验证正文非空。上游若产生空文件，仍可能提供下载；这是校验缺口，不能据此认定它造成了本次问题。

## 后续现场定位所需的最小证据

保留发生问题的原始下载 DOCX，不要先用 Word 另存覆盖。后续拿到这份文件及对应任务时间/任务 ID，可与服务端生成件对比大小、SHA256、正文 XML 和 Word 打开结果，区分生成、传输与 Office 显示问题。对应的 `.job.json`、质量报告及 `/logo` 日志可进一步关联生成阶段。

## 可复查产物

相对于服务根目录，全部诊断材料位于 `basic-service/app/runtime/blank-document-20260929/`：

- `download_probe.py`、`download-probe.json`：真实下载和审阅接口结果。
- `ooxml_probe.py`、`ooxml_probe_results.json`：DOCX 包结构检查。
- `word_probe.ps1`、`word_probe_results.json`：实际 Word 打开记录。
- `replay_linux.py`、`linux-replay.log`、`linux/verification.json`：离线 Linux 生成及原 DOC 转换记录。
- `linux/linux-current.docx`：本次外网验证生成件。
- `linux_word_probe_results.json`、`linux-current-word-probe-page3.png`：Linux 生成件在 Word 中的统计与渲染证据。
