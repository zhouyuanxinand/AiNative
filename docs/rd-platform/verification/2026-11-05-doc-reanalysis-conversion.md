# 重新分析资料：旧 DOC 转换修复验证

## 故障证据

- 用户页面显示 `InputNormalizationError`，发生在正文提取阶段。
- 本机使用同一份 YLZJ-BG-469 需求文件复现：Word COM 生成缓存模块缺少 `CLSIDToClassMap`；在线服务日志也出现同一模块缺少 `CLSIDToPackageMap`。
- 原件可以由 Word 读取。根对象改用动态包装后，`Documents.Open` 返回值仍会触发损坏缓存，因此只修改启动方式不足以修复。

## 修改

- `input_normalizer.py`：创建独立 Word COM 实例；使用原始 `IDispatch.Invoke` 打开文档并动态包装返回值，绕开生成缓存。继续使用短路径副本、只读打开、宏及链接更新禁用和原件哈希校验。
- 关闭文档及独立 Word 实例后，先释放 COM 引用及循环引用，再结束线程 COM 环境，避免延迟垃圾回收访问已结束的 COM 环境。
- `analysis.py`：已知输入转换错误显示具体可操作原因，未知异常仍不暴露内部详情。失败不覆盖旧分析结果、不提交需求采用。
- 不清理机器共享 COM 缓存，不改任务书正文生成、模板装配或质量门禁。

## 定点验证

1. 修复前：损坏缓存的真实 DOC 转换用例、分析错误说明用例均失败。
2. 修复后：同两项用例通过。
3. 完整受影响文件 `test_input_normalizer.py`、`test_input_normalizer_long_paths.py`、`rd_platform/test_source_analysis.py`：**45 passed**。包含真实中文 OCR、真实 Word 转换、缓存损坏、长路径、只读与原件不变、失败保留旧提案。
4. 调整长路径测试替身为原始 IDispatch 调用，保留原有只读及不加入最近文件断言；单独重验该完整文件：**3 passed**。
5. 仅有已有 FastAPI/Starlette 弃用提示。未执行无筛选全量；未修改原有断言或测试超时。

## 实际资料与服务

- 实际用户上传的 DOC 需求文件转换得到 **214 段、24 表**；DOC 产品规范转换得到 **373 段、8 表**。二者转换证据均为 `word_com` / `needs_review`，保留原有人工复核提示。
- 本地研发平台后端已重启并保留原环境及凭证，`/api/health`、`/api/rd/session`、`/api/rd/catalog` 均返回 200。
- 前端 `http://127.0.0.1:18370/`、`/projects` 及代理 `/api/health` 返回 200。
- 完整模型分析使用独立临时项目验证，不操作用户项目的采用、审批、模型选择及历史结果。

## 真实模型接口结果

- 当前项目选择 `azure/gpt-5`：两份 DOC 均成功转换，但上游模型多次触发原有 90 秒超时重试；验证客户端在 360 秒等待后退出。该问题发生于模型响应阶段，未冒充成功或复用旧结果。
- 使用用户截图中的 `azure/gpt-5.4` 在另一个独立临时项目对照验证：分析接口 **HTTP 200**，耗时 **179.91 秒**，得到 **50 条**带原文依据的提案，系列为 **YLZJ**，状态 `proposed`，未确认采用，需求实体列表仍为空。
- 两份来源 SHA-256 验证不变；两次临时验证项目均通过正常删除接口移除。
- 以上仅验证分析链路与引用校验可用；本轮未逐条验收模型提案的业务完整性，也未生成或审批正式研制任务书。
- 本地过程记录（不含凭证）：`runtime/doc-reanalysis-fix/service.json`、`live-analysis-result.json`、`live-analysis-gpt54-result.json`。

## 验证范围限制

- 本次验证 Windows Word 转换路径；Linux LibreOffice 转换实现未改，本轮未验证 Linux 实机。
- 应用内浏览器工具初始化失败，本轮以真实 HTTP 接口验证为准，未声称完成浏览器点击或截图验证。
