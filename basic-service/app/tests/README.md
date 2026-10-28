# 后端测试

测试按业务职责组织，既包含纯计算测试，也包含临时 SQLite、文件系统和 HTTP 集成测试。目录名称不代表全部都是单元测试。

| 目录 | 负责的行为 |
| --- | --- |
| `rd_platform/` | 项目、需求、选型、原生任务书工作单、输入包、审签与发布交付 |
| `assistant/` | 小航上下文、意图识别、操作草案、确认与权限检查 |
| `taskbook/` | 原有受控生成引擎、模板、来源证据、审校、文档排版与质量门禁 |
| `platform/` | 登录、管理员、模型配置、凭证、反馈、日志、静态资源和部署集成 |
| `support/` | 测试资源路径、共享场景工厂和夹具；不包含测试用例 |
| `fixtures/` | 版本管理中的固定测试输入 |

根目录 `pytest.ini` 统一配置包搜索路径和默认测试集合。使用项目 Python 环境，可以在仓库根目录运行：

```powershell
./basic-service/.venv/Scripts/python.exe -m pytest
./basic-service/.venv/Scripts/python.exe -m pytest basic-service/app/tests/rd_platform basic-service/app/tests/assistant
```

也可以在 `basic-service/app` 内运行 `../.venv/Scripts/python.exe -m pytest tests`。从其他目录调用时，同时传入仓库 `pytest.ini` 的绝对路径（`-c`）和此测试目录的绝对路径；所有资源路径均通过 `tests.support.paths` 定位。运行时备份、日志、依赖与构建产物不参与递归收集。

测试之间不互相导入。需要项目、工作单或审批状态时，直接使用 `support/` 中的场景工厂。`taskbook_workflow.native(store)` 创建采用研发流程的工作单文档；`taskbook_inputs.native` 是返回 `(store, project_id, task_id)` 的输入包夹具，两者职责不同。

默认 pytest 集合不包含浏览器脚本或真实模型探测。完整 HTTP 与浏览器烟测位于仓库根目录 `tests/e2e/`，需要真实模型的显式探测位于 `tests/live/`；前端浏览器回归归 `web/tests/` 管理。

新增测试优先验证公共行为，使用临时目录、合成文档和隔离数据存储。依赖 nginx 或特定操作系统的已有集成测试会报告环境要求；不得以目录调整、筛选默认集合或新增 skip/xfail 隐藏失败。
