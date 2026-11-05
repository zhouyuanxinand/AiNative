# P2A 后端独立审核

最终状态：下方初审问题及复审中发现的前端状态问题均已修复并完成定向验证，当前无未关闭的确定问题。初审证据保留，最终结论见“修复复审与前端功能审核”。

日期：2026-11-01。基线：`5cd118056010258722a12080edf5ca3ec4cb7955`。审核当前未提交后端变更及新增文件，依据 `docs/superpowers/plans/2026-11-01-rd-platform-phase2a.md`。范围为 `workspace.py`、`store.py`、`rd_controller.py` 与相关测试；未修改实现或测试，未审核本轮前端，也未运行全量回归。

## Standards

未发现需要单独报告的明确规范违反；本次不把代码风格偏好列为缺陷。领域状态通过 Workspace 封装，HTTP 权限来自服务端身份和配置，资源写入使用同一数据库事务。

## Spec

### [P2] 资源整体停用不在状态 CAS 的保护范围内，旧版发布请求可覆盖并发停用

位置：`basic-service/app/src/service/rd_platform/workspace.py:273-280`；共享状态表定义在第 36 行，管理详情的修订返回在第 112 行。

计划要求：“CAS409不覆盖并发修改”，并要求保留“旧整体停用语义”。当前发布/停用既修改固定版本的 `workspace_publications`，又修改资源级的 `workspace_controls.retired`，但 CAS 只检查目标固定版本的 `revision` 和不随状态变化的内容 head。另一版本的停用不会改变这些预期值，因而过期的发布请求仍会把整体停用清除。

已用独立临时数据库复现，不依赖线程调度：

1. 初始化后 `generate/v1` 已发布且已有默认应用授权；保存 `generate/v2` 草稿，使 head 为 2。
2. 发布者 A 读取 v1：`publication_revision=1`、`head_version=2`，准备请求 `publish(version=1, expected_version=2, expected_state_revision=1)`。
3. 发布者 B 停用 v2，使用 `expected_version=2, expected_state_revision=1`。`generate/v1` 的有效性立即变成 `False`，符合整体停用政策。
4. A 提交步骤 2 的旧请求。请求成功而非 409，v1 恢复有效且可执行；head v2 仍显示 `retired`。整个过程中授权记录没有变化。

实际输出：

```text
After resource retirement: False
Stale publish accepted: published
v1 available after stale publish: True
Head status: retired
```

影响：两个发布者或两个编辑窗口分别操作不同固定版本时，旧页面操作可撤销较新的整体停用，使保有 grant 的旧固定版本重新进入目录和运行许可检查。事务串行化不能解决此问题，因为两个命令校验的是不同固定版本的修订。

必要修复：让整体状态拥有可由客户端读取并提交的资源级 revision，并在同一事务中与固定版本 revision 一并 CAS；或将所有会修改整体状态的发布/停用操作纳入统一资源级状态修订。审计记录应包含该整体状态的前后值。保留内容版号不随状态操作增加的约束。补充上述不同版本交错发布/停用测试，断言旧请求返回 409 且原固定版继续不可用。

## 验证与未发现问题的范围

执行命令（Python 来自主工作区现有虚拟环境）：

```text
D:/桌面/ai-zhonghang/zhonghang-service/agent-develop-task-doc-service/basic-service/.venv/Scripts/python.exe -m pytest basic-service/app/tests/rd_platform/test_workspace.py basic-service/app/tests/rd_platform/test_workspace_http.py -q
```

结果：**33 passed，2 条依赖弃用警告，5.90 秒**。额外跨版本 CAS 复现使用 Python `TemporaryDirectory`，没有写入用户数据或持久测试文件。

静态核对及现有定向测试支持以下结论：发布者与授权者权限分离；普通管理读取为 403，未获准固定详情为 404；研发 DTO 隐藏 configuration；授权按应用与固定版本、摘要匹配；撤权/到期影响采用、领取、续租、活动检查及完成；旧 Run 使用显式本地应用兼容政策；重启不恢复撤销授权；历史成果仍按项目权限读取。未在这些路径中发现额外确定缺陷。这里的“未发现”不替代全量回归或真实 OA 验证。

本次结论：Standards 0 项；Spec 1 项，最高严重度 P2。修复上述整体状态 CAS 后应定向复审。

## 修复复审与前端功能审核

2026-11-01 追加。复核整体控制 CAS 修复，并扩大只读审核至 `FlowManagement.tsx`、`WorkspacePanel.tsx`、`api.ts`、`types.ts`、`RdPlatformPage.tsx`、`App.tsx`、`useDirectoryState.ts` 及本批浏览器测试。没有修改实现或测试。

### 已关闭：整体停用 CAS

`workspace_controls` 已有独立 revision，管理详情返回 `control_revision` 与 `resource_retired`；发布/停用在同一事务中校验 `expected_control_revision`，更新整体修订并审计前后整体状态。迁移为旧表补列，重启保留已停用状态。前端固定版本状态命令同时携带目标版本、head、发布状态 revision 和 control revision。

执行 `test_workspace.py -q -k 'control_revision or cross_version or controls_schema'`：**4 passed，23 deselected，0.58 秒**。跨版本并发测试显式提交共同 head 与 control revision，确认仅一个写入成功，另一个返回 409。因此初审 P2 关闭。

测试精度说明：串行回归原先通过 `publish(store, old)` 使用了旧固定版本作为 `expected_version`，可能先被 head CAS 拦截；实施者已将 helper 修正为 `resource.head_version`。修正后单独重跑 `test_cross_version_stale_publish_cannot_override_newer_resource_retirement`：**1 passed**，现在会准确检验跨固定版本的整体控制冲突。

### 已关闭：冲突刷新迟到响应与撤权清理

复审中发现 `WorkspacePanel.refreshConflict` 最初未使用其他目录请求已有的 `sensitiveEpoch` 保护：403 清理完成后，之前发起的管理详情请求仍可重新写入 `detail`/`editing`，并覆盖撤权提示。实施者已在冲突刷新及写入回执的成功、失败分支增加同一权限代次检查。

独立 Chromium 测试使用 Vite `127.0.0.1:18370` 与全 API 隔离夹具：先制造保存 409，再延迟冲突刷新 `/workspace/resources/secret/latest` 的 200；并行搜索目录返回 403；确认敏感状态为空后释放迟到 200。**通过**：配置缓存保持为空、配置编辑框不出现、撤权提示保留，旧成功提示不出现。夹具检查了当前组件状态及可见页面，没有访问或修改真实项目。新增浏览器测试亦覆盖迟到冲突读取和写入回执不触发权限刷新。

### 已关闭：整体停用状态与固定版恢复入口不一致

复审中发现前端最初忽略 `resource_retired`：v2 整体停用后，仍为 `published` 的 v1 无法点击发布恢复，授予按钮却仍可点，并且“停用版本”文案未说明所有版本暂停。当前类型与页面已消费整体状态；文案改为“停用资源”，显示整体停用及控制修订，已发布旧版可明确“恢复发布”，确认说明其他已发布且有效授权版本也会恢复；整体停用时禁止授予。

独立 Chromium 隔离夹具设置 v1 为 `published`、head=4、control revision=6、`resource_retired=true`。**通过**：恢复发布按钮可用、授予按钮禁用、确认文案说明整体影响，发布请求准确发送 `version=1, expected_version=4, expected_control_revision=6`，成功后显示真实恢复语义。

### 其他检查与边界

- `FlowManagement` 的目录来源使用服务端过滤分页；当前工作包/研发流程固定节点来自选定固定定义，动作与适用工作包关联保留。没有新增任意配置执行或图形编辑能力。
- `flow_*` 与 `workspace_*` 参数独立，App 路由识别这些参数；搜索采用 300ms 防抖和输入法组合保护，条件变化取消旧目录请求，服务端总页数用于收敛超页。
- 普通目录只取摘要 API；管理列表/固定详情都有取消及权限代次保护。固定版状态操作使用当前 head，冲突恢复按原固定版本或 `latest` 精确读取，没有依赖当前分页中的目标。
- 新增窄屏样式保持自然滚动、操作按钮换行与左对齐，未新增整页固定高度。已检查现有浏览器测试的 390×520 点击/滚动覆盖；完整截图及小航位置的视觉验收由前端验证代理负责，本复审不把静态 CSS 检查当成独立完整视觉通过证明。

本轮最终结论：**无未关闭的确定问题**。初审后端 P2 及复审发现的前端状态问题已修复；本报告只声明上述定向验证结果，完整 RD 回归、生产构建及完整浏览器验证由主代理统一记录。
