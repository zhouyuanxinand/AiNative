# P2A Task 1 后端领域验证

2026-11-01。范围为 `workspace.py`、Store 集成及领域/运行回归测试；未修改生成引擎、受控模板、Profile、mapping，也未提交 Git。

## 实现结果

- 资源内容版不可变，保存产生草稿和内容摘要；发布/停用使用独立状态修订，不增加内容版。管理固定详情附 `head_version`、全部 `available_versions`，支持旧固定版状态操作的 head CAS。
- 发布权限与应用投放权限分别校验。所有 Workspace 写入使用主体级幂等键、事务、CAS、前后状态审计；发布不自动投放。grant 绑定应用、固定版、摘要、独立 revision 及可选 UTC 失效时间。
- 一次性初始化只为 `rd-platform-local` 登记六个原内置 v1 授权，初始化标记阻止重启恢复撤权；保留旧整体停用语义，不改写原内容或工程项目。
- 获准目录先按发布状态、grant、有效期、团队依赖闭包过滤，再按资源 ID 聚合、搜索和分页；默认每页 5 条。公开摘要采用字段白名单，无 configuration、主体或授权内部元数据；管理 DTO 保留配置。
- 团队仅使用固定成员引用，发布校验存在、已发布和无循环；投放及有效性检查成员许可闭包。自定义声明仍 `executable=false`，未新增执行器。
- create_case、流程采用、pull、save_plan、submit 均复核必需能力许可；业务目录裁剪不可用必需工作包/流程和可选能力。提交保存应用、授权政策和内容摘要，保持原 v1 执行绑定。
- 领取、活动检查、续租、完成均复核许可，撤权或过期后拒绝续租及结果；活动检查不读取/哈希来源文件。旧 Run 缺少应用字段固定按本地兼容应用处理。历史项目和成果继续按原项目权限读取。项目 DTO 和旧幂等回执均隐藏执行配置，worker 内部快照保留原绑定。

## 验证证据

Python 使用原环境 `basic-service/.venv/Scripts/python.exe`，测试数据库和文件均位于 pytest 临时目录。

- 先新增领域测试，首次运行 6 failed，均因 Store 缺少应用/Workspace 能力；后续新增摘要持久化、DTO 清理、非法 JSON、旧回执用例均分别观察到预期失败，再修复。
- 最新 `python -m pytest basic-service/app/tests/rd_platform/test_workspace.py -q`：**23 passed**。覆盖发布/授权分离、角色拒绝、状态/内容版分离、CAS及并发grant、幂等重启、到期、应用隔离、分页、团队闭包/循环、旧停用迁移、采用检查、运行撤权/过期、旧Run兼容、历史成果可读、配置泄漏及旧回执清理。
- Store + Runtime + Workspace 回归：**101 passed**（该轮 Workspace 为 14 项，后又补齐至 23 项）。两处旧测试已按新契约改为发布/停用不增加内容版。
- 首轮完整 RD：349 passed / 2 failed；失败仅为上述两处旧版号断言，随后已修订并通过定向回归。第二轮完整 RD 为避免与整合验证重复，按主代理要求中断；最终完整 RD/HTTP/生成契约验证由主代理统一执行。

## 范围与限制

真实 OA 企业资源角色 API 尚未接入，HTTP 主体/配置权限由 Task 2 验证。新 agent/team 配置仅用于受控登记，不代表已接通执行器。真实外部模型生成、Word 2007 不在本领域测试的完成声明内。未修改用户真实项目数据。

## 独立审核 P2 修复：跨版本整体停用 CAS

独立审核指出固定版发布修订无法保护共享的资源整体停用标记。已先加入确定性交错复现、缺失整体 revision 拒绝及旧表迁移用例，观察到 **3 failed / 23 passed**：旧版发布错误成功，缺少整体 revision 的发布错误成功，旧表未提供 revision。

修复为 `workspace_controls.revision INTEGER NOT NULL DEFAULT 1`。初始化在同一事务中为旧表补列、为全部资源（含只有草稿者）补齐 control；已存在的 retired、revision 及兼容初始化标记保持不变，重启不重新授予能力。管理详情提供 `control_revision` 和 `resource_retired`。每次发布/停用同时验证 head、固定发布修订及 `expected_control_revision`，然后递增整体 revision，审计包含整体 retired/revision 前后值。只有可信 Store 适配器可补当前整体修订，Workspace 写入口要求调用方明确提供。

新增真实双线程跨版本写入测试证明同一整体 revision 下仅一方成功、另一方 409，且重启后整体 revision 保留；确定性交错测试证明先停用 v2 后提交旧 v1 发布请求不能重新启用 v1。最终定向验证：

- Workspace 领域：**27 passed，3.75 秒**。
- Workspace + Store + Runtime：**114 passed，31.53 秒**。

本次未再次运行全量；HTTP 与前端 control revision 合同由对应任务更新并由主代理整合验证。
