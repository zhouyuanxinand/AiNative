# P2A 前端实施与验证（2026-11-01）

实施范围为计划 Task 3：本地 Workspace 资源治理与研发获准目录。没有修改后端、原 pipeline、模板或 P2B 画布编辑器，也没有提交或推送代码。

## 已完成

- `web/src/features/rd/{api.ts,types.ts}` 增加 Workspace 独立会话、获准摘要/固定详情、管理分页/固定详情、grant 命令与服务端目录分页类型。普通目录 DTO 不包含 configuration；读取不使用浏览器缓存。
- `WorkspacePanel.tsx` 独立使用编辑、发布和应用授权权限；任何治理权才读取管理面，普通用户仅读取当前应用获准摘要。配置只在管理固定详情展示。发布、停用、授予、撤销各用共享确认与实际回执，未绑定执行器明确说明。
- 保存使用 head CAS；发布/停用同时携带固定 version、expected_version、expected_state_revision、expected_control_revision；grant 使用独立 expected_revision。409保留草稿，保存按 id/latest 精确刷新，状态/授权按原 id/version 精确刷新。未知结果同意图同幂等键重试；403清除敏感列表、配置草稿、详情、重试内容及待确认操作。
- `FlowManagement.tsx` 四类目录统一每页五条服务端分页；资源卡片只读摘要，受控DOCX目录继续原下载权限。原画布缩放/平移/列表/节点关系和项目编排保留。
- `useDirectoryState.ts` 统一独立 flow_* / workspace_* URL 状态、300ms搜索防抖、中文组合输入保护、即时清空/Enter提交；读取支持取消和迟到响应忽略，超页按真实总数收敛。页码、类型、搜索和选中固定资源可刷新恢复。
- `workspacePanel.css` 沿用共享令牌和自然页面滚动。390px短窗口按钮左排避开默认小航浮窗，标题说明亦留避让空间；没有增加全页固定高度。DESIGN/UX-CONTRACT同步本批约定。
- 主代理已在 `RdPlatformPage.tsx` 接上 `onCatalogChange`，治理成功或权限失效后重新读取根目录。

必要计划补充：`App.tsx` 现有研究路由只保留六个全局参数，会剥离所有目录状态，导致刷新恢复失败。本批只增加 flow_tab/kind/item/q/page 及 workspace_q/kind/page/item/version 精确白名单；未知前缀字段和凭证仍删除。对应路由测试已更新。

## 验证结果

环境：Node `D:/Scoop/apps/fnm/current/node-versions/v22.23.2/installation`，Playwright Core `D:/tmp_pw/node_modules/playwright-core/index.mjs`，Chromium headless shell 1248。

| 验证 | 结果 |
|---|---|
| `node --test web/tests/app-routes.test.mjs web/tests/url-query.test.mjs` | 8/8通过，包含目录状态与凭证白名单 |
| `node web/tests/rd-workspace-p2a.browser.mjs`（TEST_BASE_URL=18373；全API隔离夹具） | 通过：普通只读不请求管理面、独立granter/publisher、五条分页、URL恢复、IME/清空/迟到取消、失败/空态、grant/revoke、save/pub/retire、幂等重试、409按head/固定版精确读取、跨版本head/control CAS、403清屏、390x520实际点击保存和JSON校验 |
| `node web/tests/rd-flow-management.browser.mjs`（TEST_BASE_URL=18370；读取真实18372目录，项目变更为隔离夹具） | 通过：四目录、真实图边、缩放/平移/键盘/列表、五条分页、搜索与窄屏、可选节点增删、失败保存同键重试、依赖重连和提交后只读；没有真实生成或项目写入 |
| `npm --prefix web run build` | TypeScript和Vite生产构建通过；保留既有大于500kB chunk提示 |
| premium `audit_project.py . --mode strict --output runtime/rd-phase2a-premium-audit.json` | 退出1：仍为21条既有finding，0 unresolved；本批前端文件没有新增finding，详情保留JSON |
| `node web/tests/feedback.browser.mjs` | 管理反馈段运行通过；末段仍假设退役首页 `#workspace-shell`，其旧夹具缺研发目录字段，报filter undefined并超时。没有据此修改无关反馈页 |
| `git diff --check`（本批已跟踪前端/文档文件） | 通过，仅Git LF/CRLF提示 |

截图在 `runtime/rd-phase2a-browser/`：只读桌面、390x520只读、granter治理表面、publisher桌面、flow短窗口、publisher短窗口保存/校验和短窗口顶部。已逐项查看治理表面、窄屏顶部/底部。原画布回归截图在 `runtime/rd-phase2a-flow-browser/`。

待联调/未宣称覆盖：真实OA外部主体配置和真实企业角色API、Word 2007、任意新模型实际生成、新资源真实执行器绑定、P2B完整图形编辑。本地治理API角色矩阵和实际后端全量回归由主代理/后端代理另行记录。本批截图治理权限使用模拟API，不代表真实OA权限联调。

## 最终语义与竞态复核

后端retire沿用资源整体停用语义，前端已统一“停用资源”，确认明确所有版本暂停、历史成果保留；管理详情增加resource_retired/control_revision，整体停用时即便所选固定版仍published也显示可用的“恢复发布”，确认解释解除整体停用以及旧有效授权版恢复，未授权应用仍须grant。整体停用时授予应用禁用。浏览器覆盖跨版本整体停用后所选published版恢复及granter禁用。

refreshConflict和mutation在await成功/失败后均校验sensitiveEpoch。新增延迟latest详情与延迟POST回执两条并发测试：保留请求→新搜索触发403→清屏→释放旧200；断言详情/配置不恢复、无旧成功提示、不会触发旧管理刷新。更新后的rd-workspace-p2a.browser.mjs在18370通过，截图同步更新。
