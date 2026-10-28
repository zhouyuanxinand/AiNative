# 后端开发

后端使用 FastAPI。`app/` 保持现有部署和数据目录契约；开发时从仓库根使用统一检查入口，或进入 `app/` 执行 `python -m src.main`。独立管理员服务入口仍为 `python -m src.feedback_main`。

## 代码归属

| 目录 | 职责 | 变更入口 |
| --- | --- | --- |
| `app/src/application/` | 应用装配、启动停止、公共中间件、静态页面和路径定位 | 新路由注册在 `factory.py`；资源根在 `paths.py` |
| `app/src/controller/` | HTTP 参数、身份依赖、错误响应和业务调用 | R&D 公共依赖在 `rd_dependencies.py` |
| `app/src/service/rd_platform/` | 项目事实、基线、任务、成果、审签、发布及事务 | `store.py` 为命令与事务入口；`runtime.py` 装配实例 |
| `app/src/service/assistant/` | 意图识别、对话上下文、能力登记和操作确认 | `conversation.py` 处理对话；`operations.py` 注册能力 |
| `app/src/service/jonhon_taskbook/` | 既有受控生成引擎、模板、规则和文档核验 | 保留现有引擎和资源布局 |
| `app/src/common/` | 身份、凭证、日志、请求归档等共用能力 | 供 HTTP 与应用装配使用 |
| `app/src/utils/` | 运行配置装配 | `config_loader.py` 复用统一路径 |
| `app/tests/` | 按职责分组的离线回归与共享场景 | 具体运行方法见仓库开发文档 |

`main.py` 只提供稳定的启动入口；测试装配应用时优先导入 `src.application.factory.create_app`。工厂不会启动生成工作线程，生产入口单独绑定 `application.lifecycle.lifespan`。管理员服务直接复用公共模块，导入它不会构造主站应用或播种主站数据。

## 新功能如何接入

1. 在对应业务目录实现规则，复用项目命令的身份、版本检查和幂等事务。
2. 控制器只转换 HTTP 输入输出。不要从业务规则反向导入 `rd_controller` 获取数据库或身份依赖。
3. 小航的新业务能力登记在 `assistant.operations`，通过明确参数预览和确认后执行原领域命令；对话文本不能决定任意脚本路径。
4. 共用身份与参数类型从 `controller.rd_dependencies` 导入；业务代码获取配置后的项目存储从 `service.rd_platform.runtime` 导入。
5. 跨测试场景放在测试支持目录，不从另一个 `test_*.py` 文件导入构造器。

## 保留的生成适配边界

原生成控制器仍持有任务队列、模型选择和运行状态。`rd_platform/integration.py`、`taskbook_inputs.py`、`taskbook_runs.py` 等是现有研发流程对该内核的适配，仍会调用其固定接口。该边界本次没有强行替换成新的仓储或插件框架；之后接入 K-box、本体和 Workspace API 时，应在各自适配入口推进解耦。

`application.paths` 集中应用、仓库及运行目录位置，`application.bootstrap` 仅维护原引擎绝对导入所需的搜索路径。禁止为了调整业务包目录而更改固定输入包的运行指纹算法、模板资源位置或生成规则。

`app/runtime/`、日志、上传文件及私有 `.env` 都是运行数据，不属于源码。重构代码时不搬迁或覆盖这些文件，也不要将真实模型调用混入默认离线测试。
