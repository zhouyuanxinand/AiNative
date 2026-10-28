# 工程化重构验证记录（2026-10-29）

本次调整代码归属与测试组织，保留页面内容、业务接口、运行目录和受控生成逻辑。实现说明见 [架构](architecture.md)，运行命令见 [开发指南](development.md)。

## 已完成的核验

| 范围 | 结果 |
| --- | --- |
| 前端行为测试 | 59 项通过 |
| TypeScript / Vite | 检查与构建通过；仍有原有主包超过 500 kB 提示 |
| 后端研发、小航与平台能力 | 744 项通过，4 项现有 nginx 环境相关跳过 |
| 完整后端逐项结果 | 完整运行并复验已修用例后，按用例去重汇总：1,942 通过、5 项既有失败、4 项现有环境跳过；无剩余导入错误，另有 62 个子测试通过 |
| 后端测试发现 | 147 个文件迁移前后均收集到 1,951 个用例，用例名称集合一致 |
| 跨工作目录 | 根、应用目录和仓库外目录的测试入口可用 |
| 小航浏览器 | 对话 22 项、拖动 10 项、动画 10 项通过 |
| 跨前后端流程 | 隔离的小航操作确认、原生任务书、四角色研发流程通过 |
| 文档审阅浏览器 | 来源互链、编辑、冲突草稿、修订恢复、独立滚动、键盘调宽及窄屏切换通过 |
| Vite 回跳代理 | 使用本地合成后端验证通过 |
| 生成内核 | 121 个生成代码及资源文件摘要与重构前相同 |
| 页面保真 | 23 个 CSS 源文件及最终构建 CSS 字节相同；浏览器核验无新增溢出 |
| 前端依赖 | 117 个 TS/TSX 模块无循环依赖，shared 不反向依赖 features/app |
| Git 忽略 | 凭证/缓存/数据库/报告被排除，工程源码/模板/锁文件可跟踪；已跟踪且命中忽略规则的文件为 0 |

浏览器业务写入只发生在临时隔离数据库或拦截的接口中，没有调用真实模型或 OA。真实模型探测单独留在 `live` 目录，不在默认回归中运行。

迁移时同步修正了测试本身的路径和过时夹具：停止脚本进程对象补齐父进程字段，反馈与 SPA 测试提供完整临时配置和独立管理员会话，SPA 测试采用现有的日志入口 403 契约；任务书正式计划的浏览器入口使用已存在的 `tab=flow`。文档审阅脚本使用小航已有的键盘移动能力避开历史版本按钮，没有修改产品界面。

## 保留的已有失败

`basic-service/app/tests/taskbook/test_generated_table_formatting.py` 中两组
`test_imported_table_and_indicator_keep_column_ratios_at_same_body_width` 仍失败：
当前 Word 兼容规范化把 `w:tblLook` 命名属性合并进 `w:val`，而测试断言封面表格 XML 文本完全不变。

另有 `taskbook/test_product_process_compatibility.py` 的
`test_real_fill_keeps_quantitative_and_qualitative_evidence_in_nested_slots`，在系统集成产品的改型 I、II、III 三组参数下失败：生成高温条款出现一次，测试预期两次。使用 Git 中未迁移的原测试文本、原 `__file__` 定位再次复现了改型 I，用于排除迁移路径或执行顺序造成问题。

这些失败不通过本次结构调整修复；重构未改变生成内核，也未删除、跳过或放宽五项断言。因此不能将完整后端测试声明为全部通过；默认 `backend` 检查会如实返回失败。复现：

```powershell
basic-service/.venv/Scripts/python.exe -m pytest basic-service/app/tests/taskbook/test_generated_table_formatting.py -q
basic-service/.venv/Scripts/python.exe -m pytest basic-service/app/tests/taskbook/test_product_process_compatibility.py -k test_real_fill_keeps_quantitative_and_qualitative_evidence_in_nested_slots -q
```

运行日志、截图、源码摘要及路径迁移清单在忽略的 `basic-service/app/runtime/engineering-structure/` 和 `runtime/structure-refactor/`，不作为产品文件上传。历史业务和模型验证记录继续保留各自的日期与范围。
