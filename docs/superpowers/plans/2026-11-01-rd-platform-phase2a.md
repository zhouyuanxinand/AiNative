# P2A：本地 Workspace 资源发布与应用授权

> 2026-11-01。依据用户“继续修改代码”进入下一批；先完成本计划，再开始应用代码修改。基线提交 `5cd1180`，分支 `codex/rd-platform-rebuild-20261031`。P0/P1 已完成，本批不代表 P2B—P5 同时启动。

## 目标与边界

依据《整体方案》、主题方案03 §2.3及总体开发计划，拆开资源定义/发布、对研发应用的授权、项目采用三个行为。研发读获准目录，Workspace 维护资源。当前仍同部署、手动上传原资料；原任务书引擎、受控模板及既有固定版本保持不变。

本批完成发布与投放权限分离、内容/状态版本分离、目录授权过滤与默认五条服务端分页、采用和运行中的撤权检查。专家团内部图形编辑、任意新资源实际调度、业务画布编辑、外部 API 接入留在后续批次。现有六个步骤仍为内置 Skill，不改称专家团。

## 本地政策与兼容决定

- 当前能力应用 ID 由服务端 `JTB_RD_WORKSPACE_APP_ID` 固定，默认 `rd-platform-local`，与 OA 登录应用 ID 无关，不能由查询参数或请求体改变。
- `JTB_RD_WORKSPACE_PUBLISHERS`、`JTB_RD_WORKSPACE_GRANT_MANAGERS` 为逗号分隔的经验证主体 ID。前者可编辑和发布，后者可投放和撤销；不存在隐式包含关系。当前无企业角色 API，不假装接通。主站/OA 管理员只作为身份来源，不能据此授权。
- 保留明确的本地开发开关 `JTB_RD_LOCAL_WORKSPACE_ADMIN=1`，仅统一登录关闭且客户端为回环地址时给予这两种本地测试权；默认不开启。页面说明本地范围。
- 原有六个内置 v1 执行资源在一次性初始化时向默认本地应用登记兼容授权；其他应用不自动获权。初始化记账且不恢复已撤销记录。已有资源内容和项目快照不批量重写。
- 旧 Run 缺少应用字段时按 `rd-platform-local` 的显式兼容政策复核，不能借新部署应用标识继承权。历史成果仍由原项目权限查看，撤权不删除历史文件。
- 研发资源目录以资源 ID 为入口计数，每项显示当前最高获准固定版及 `available_versions`；详情按指定版本验证。显示新版不改变项目已采用版。
- 原受控 DOCX 目录属于文档资产域，本批不新建文档资产授权制度；流程页面使用同一分页接口读取现有合法文档目录，原模板下载权限保持原实现，明确区别于 Workspace 能力目录。

## 数据与事务

沿用 `resource_versions`/`resource_heads`，新增 Workspace 状态、grant、审计/幂等和初始化标记表。保存内容创建新草稿版及内容摘要；发布/停用只改变独立状态修订，不生成内容版。固定版发布不自动授予任何应用。记录主体、时间、操作、目标、前后状态与独立修订。

授权绑定应用、资源 ID、固定版本、内容摘要；有独立 revision、状态、可选 UTC 失效时间。授权者只能投放已发布且整体有效的版本。撤销/到期立刻影响新读取与执行检查。原整体停用语义继续保留：停用会暂停该资源所有版本，保存新草稿不会恢复；显式恢复发布解除整体停用，其他版本仍须各自处于已发布且获准状态。界面必须明确整体状态及影响，允许恢复指定的已发布旧固定版，不能要求发布新内容版才能恢复。

团队仅保存固定成员引用 `configuration.members=[{resource_id,resource_version}]`。发布校验存在、固定版发布、无循环；投放及有效性校验成员许可闭包。研发 DTO 不公开原始 configuration；不把团队声明当成已接通执行器。

所有写操作要求 Idempotency-Key，同主体同键同内容返回原回执，异内容409；CAS409不覆盖并发修改。发布/停用还必须核对资源整体停用状态的 `expected_control_revision`，避免旧固定版的并发发布覆盖另一版刚做出的整体停用。管理详情返回 `control_revision` 和 `resource_retired`。已有纯 Store 内部维护接口可作可信兼容适配，但 HTTP 不接受客户端 can_manage/角色。

## 接口合同（本地逻辑接口）

统一前缀 `/api/rd`。成功列表：`{items,total,page,page_size,total_pages}`，默认 page=1/page_size=5，大小上限50，超页空列表及真实总数；前端据返回总数收敛页码。搜索/计数/分页都在过滤之后，不能用报错暴露未授权条目。

| 接口 | 用途 |
|---|---|
| GET `/workspace/session` | `{application_id,can_edit_resources,can_publish_resources,can_manage_application_grants,local_bootstrap}` |
| GET `/catalog/resources?q=&kind=&page=1&page_size=5` | 当前应用获准资源摘要，无 configuration；单项含 available_versions |
| GET `/catalog/resources/{id}/{version}` | 同授权范围固定版摘要；不存在/未授权统一404 |
| GET `/workspace/resources?q=&kind=&page=1&page_size=5` | 仅发布者或授权者可读管理目录；列表仍返回 resources 别名兼容旧前端 |
| GET `/workspace/resources/{id}/{version}` | 管理固定内容版，含 configuration、publication_revision、当前应用 grant |
| POST `/workspace/resources` | 发布者保存草稿；现有 operation=publish/retire 转为状态命令，不再新增内容版；需 expected_version（当前head）；状态操作另需 version固定版、expected_state_revision及expected_control_revision |
| POST `/workspace/grants` | 授权者设置当前应用固定版本 grant，`{id,version,operation:grant\|revoke,expected_revision,expires_at?}`；禁止客户端改变应用 |
| GET `/catalog` | 业务选择器引导数据，保持结构，但 actions/工作包/流程均按有效必需能力过滤；未授权可选节点裁剪 |
| GET `/catalog/items?category=actions\|workpackages\|research\|selection\|reports&q=&page=1&page_size=5` | 流程页面服务端分页；工作包、流程遵循与 `/catalog` 相同过滤 |

Store 通过 `workspace` 服务封装领域逻辑，统一提供管理列表/固定详情、获准列表/详情、状态/授权写入及 capability_available。controller 只解析身份、权限和参数并调用服务。发布者与授权者读管理信息均须经明确配置；普通用户资源工作台显示获准只读目录。

## 开发任务

### Task 1：Workspace 领域与 Store 集成

修改 `basic-service/app/src/service/rd_platform/store.py`，新增 `workspace.py`，必要时补 `executors.py` 的快照字段检查。先写领域行为测试，再实现状态/授权及兼容初始化。采用 create_case/adopt_taskbook_flow/pull/save_plan/submit 均检查当前应用许可，必需项不可用拒绝，可选项隐藏；提交保存 application_id、授权政策与内容摘要，保留原 v1 执行绑定。领取、心跳/取消检测、完成使用相同许可检查，撤权后停止续租并拒收结果。频繁取消检查仅校验许可，不反复哈希全部文件。

验收：角色写入分别拒绝、内容版与状态版分离、发布不投放、固定版不漂移、授权/撤权/过期/重启、隐藏依赖、分页过滤、旧 Run 与已完成成果可读；旧生成契约及生命周期测试不退化。

### Task 2：HTTP 权限与目录

修改 `basic-service/app/src/controller/rd_controller.py`；新增独立 Workspace 主体权限解析，应用配置注入 Store。实现上表接口、CAS/幂等、合法查询参数；旧管理员Cookie不授资源权，未知查询应用参数不改变目标。普通管理读403，获准详情404；不得提供全量 fallback。新增 HTTP 身份/角色矩阵与分页测试。

### Task 3：资源工作台与流程目录

修改 `web/src/features/rd/{api.ts,types.ts,WorkspacePanel.tsx,FlowManagement.tsx}` 及局部 CSS。研发目录使用摘要 DTO；Workspace 显示独立编辑/发布/应用授权能力。发布、停用、授予、撤销分别使用共享确认与真实回执。配置只在管理面呈现；未绑定执行器显示真实限制。冲突刷新按固定资源/当前 head精确读取，不能依赖分页列表找到目标。

查询/页码/类型/选中资源写独立 URL 参数；中文输入法保护、300ms防抖、取消迟到请求、加载/空/失败区别；权限失败清理已无权数据，409保留草稿，网络未知结果用同键重试。分页每页5条，不增加整页固定高度，390px及短窗口底部操作可达。更新 DESIGN/UX 中本批规则，原画布继续可查看。

### Task 4：验证与回执

运行全部 RD 后端测试、生成桥接与任务书专门回归、前端构建和相关浏览器测试。新增隔离数据库/模拟API测试，不污染用户真实项目。实测本地列表与权限响应，并截图桌面/窄屏/授权表面。记录已覆盖与未覆盖（真实 OA 外部角色、Word 2007、真实新模型生成不由本批假定通过）。更新执行记录及总体计划状态。

## 不可突破的约束

不改原 pipeline、controlled template、profile、mapping；不自动批准工程阶段；不把角色名字写进客户端当权限；不写原始凭证；不以任意 resource configuration 执行代码；不发布远程或推送代码。原数据仅增加 Workspace 记账表与一次性兼容种子，工程项目不迁移。

## 执行记录

- 计划完成时应用工作区仍为基线提交；两份只读审计指出的原始配置泄漏、权限合并、前端分页及未消费幂等键均纳入本批。
- 后续任务进度、偏差与验证证据记录于 `docs/rd-platform/verification/2026-11-01-phase2a-execution.md`。
