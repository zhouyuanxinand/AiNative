# 重新分析资料 DOC 转换故障修复计划

## 已复现问题

使用用户提供的 YLZJ-BG-469 DOC 调用实际 `_source_text`，在 `DispatchEx` 创建 Word 包装对象时失败：生成缓存模块缺少 `CLSIDToClassMap`。Word 本身可以启动。仅将根对象换成 `dynamic.Dispatch` 仍不足，`Documents.Open` 返回文档对象时又会进入相同缓存路径。

## 改造范围

1. 在旧版 DOC 转换内部使用独立 COM 实例，并通过动态包装处理根对象；对返回文档对象的 Open 调用直接使用 IDispatch，再动态包装，避开损坏的生成缓存。
2. 继续使用短路径副本、只读打开、禁止宏及链接更新、原件哈希检查和转换后结构校验。仅关闭本次独立实例，不删除用户 COM 缓存。
3. 对可预期的 InputNormalizationError 显示明确中文原因，区分转换组件缺失与已安装但转换失败；未知异常不向页面暴露内部路径或堆栈。
4. 保留旧分析结果和上传资料，不以旧结果冒充本次成功。

## 验证

- 先补充损坏 COM 缓存及 API 错误信息的回归用例，确认修复前失败。
- 验证整个受影响测试文件：输入转换、长路径转换、资料分析。
- 用同一份实际 DOC 重新提取正文，并检查表格和原文件哈希。
- 对运行中的本地服务加载修复后，验证资料重新分析请求；不自动确认采用提案。
- 不运行无筛选全量测试，不修改正文生成和模板装配逻辑。

接口参数依据：[Microsoft Word Documents.Open](https://learn.microsoft.com/en-us/office/vba/api/word.documents.open)。
