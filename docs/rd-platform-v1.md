# 研发管理平台交接说明

本轮角色与业务路线重构（2026-10-28）：首页调整为“我的工作”，项目收拢为“当前成果、项目流程、资料与画像”。负责人可以登记选型路线和直接选用的实际交接，改型/新研继续使用既有启动与任务书工作包。当前仅保留项目负责人、工程师、独立评审三类办理职责，以及按需只读访问。成员只配置一项项目职责，执行人与评审人在任务中指定；不自动添加全局治理、领导或运营角色。旧页面URL、分页和锚点继续映射。执行计划见[角色与业务路线重构](superpowers/plans/2026-10-28-role-journey-refactor.md)。

现有任务书应用集中承载语义规则、资料知识处理及智能规划执行；后续按API就绪程度逐项下沉本体、K-box和Workspace。本轮没有新增虚构远程调用，原生成引擎继续沿用。设计/验证专业工具、共享知识治理及三平台完整运营仍待实际接口集成。本轮验证详情见下文的“本轮验证”。

适用于本地分支 `feat/rd-platform-v1`。平台首页为研发总览，导航贯通项目、需求、任务、成果及审签。研制任务书已内化为项目中的 BP05 工作包，在同一任务内完成输入确认、编制修订、WBS 与验证策划、独立审签、计划发布和下游交接；原生成算法保持不变。当前范围见 [任务书内化开发计划](superpowers/plans/2026-10-28-taskbook-native-workflow.md)，此前平台设计见 [整体重构设计](superpowers/specs/2026-10-28-rd-platform-refactor-design.md)。代码留在本地，未提交或推送。

## 演示启动

已安装依赖时，从仓库根目录执行：

```powershell
Set-Location web
npm run build
Set-Location ..
.\start-demo.ps1
```

访问 `http://127.0.0.1:18130/`。脚本只启动主平台，不占用已有的独立管理端口；已有本项目服务先用 `stop.ps1` 停止，或 `start-demo.ps1 -Port 18132` 使用其他端口。

脚本显式设置 `JTB_DEMO_MODE=true`，OA 校验放行，不调用企业登录服务；无需账号密码，默认演示负责人。页面可切换负责人、工程师、审核人和观察员，体验不同办理职责及独立审签。三个连接器研发项目保留原通用任务，并增加原生任务书样例与发布后的正式任务。数据通过真实领域服务持久化，重启不覆盖编辑；演示 DOCX 与 QA 证据明确标记 mock，不代表真实模型或工程验证产出。

默认演示数据库 `basic-service/app/runtime/rd_platform.demo.sqlite3` 和成果 `rd_artifacts_demo/` 与非演示库分开，`JTB_RD_DB`、`JTB_RD_ARTIFACTS` 仍可显式覆盖。需要使用真实 OA 时关闭演示开关，依照下方统一身份说明配置。任务书生成仍需原有真实模型配置，演示身份不会替代或伪造模型响应。

| 页面 | 地址 |
| --- | --- |
| 研发总览 | `/` |
| 研发项目及详情 | `/rd`、`/rd/{项目ID}` |
| 需求中心 / 研发任务 | `/requirements`、`/tasks` |
| 成果中心 / 审签待办 | `/artifacts`、`/approvals` |
| 项目内任务书工作面 | `/rd/{项目ID}/tasks/{任务ID}` |
| 任务书工具 / 文档修订 | `/taskbook`、`/review/{作业ID}` |

各中心从当前用户可见项目汇总，点击记录返回原项目办理。`/api/rd/workspace` 最多返回当前身份可见的200个项目；首版不支持超出该范围的全局统计。

## 已实现范围

- `/rd` 项目列表、`/rd/{项目ID}` 项目工作区：成员职责、需求修订和固定基线、任务分派、成果、审签与事件记录。
- 服务端 SQLite 持久化；修改携带项目版本，过期提交返回 409；稳定请求键避免重试生成重复业务操作。
- 原生任务书在任务内生成、修订和核验；生成作业执行前绑定项目、任务、执行人、固定输入包及需求基线，保留输入清单和文件哈希。旧通用任务和独立工具继续兼容。
- 明确选择文档修订登记固定成果，保存文件哈希及完整 QA 证据快照；通过检查后由指定的独立审核人批准或退回。自动 QA 通过仍需人工审签。
- 原生任务书及下发任务按具体需求、资料和模板依赖评估变更影响；受影响或影响未知的用途待复核，明确无关的变更不阻断办理。旧通用任务继续采用基线换版复核机制。旧成果和历史决定保留，旧作业不能换绑为新基线成果。
- 项目成员权限覆盖绑定作业的原有历史、文档审阅、下载及 Office 编辑入口；移除成员和调整分派撤销相应权限与待审授权。

## 任务书工作包的操作流程

从“研发项目”进入项目任务，登记有依据的改型或新研批准，采用固定流程模板后创建研制任务书工作包。成熟产品直接选用不会自动进入编制流程。既有批准材料可手工登记，来源须选择真实登记或演示数据；当前不代办外部选型审批。

1. **输入与编制 / ND13**：项目集中保存技术要求、规范及参考文件，按版本勾选资料。确认需求、范围、生成参数、模型、模板及规则环境形成输入包；任务私有草稿支持刷新恢复和冲突处理。开始编制调用原生成引擎。
2. **文档与核验 / ND13**：候选稿在任务内打开原审阅器，编辑仍使用同一 ReviewStore 修订。采用明确修订后，核对十五类内容、来源依据和需求引用；缺项不能凭空补成已满足，不适用须记录原因。原 QA 与覆盖核对分开保存。
3. **WBS 与验证 / ND14**：将要求和正文位置关联到设计、工作及验证条目，明确交付物、责任、前置关系、接受标准、接受人和计划日期。支持 JSON 模板导入为草案及人工增改；核对并保存后才形成草案版本，尚不派工。
4. **审签与发布 / ND15**：送审一次固定文档哈希、修订、输入包、QA、覆盖与 WBS。指定的独立审核人批准或退回，编制人不能自批。后续编辑不改变已送审内容，批准后形成任务书发布包。
5. **交接与变更**：负责人明确发布计划，将 WBS 转为正式任务及交接包；指定接受人接收后才可开工。项目概览同页展示上方流程、下方甘特，二者读取同一份计划，绿色实际日期仅来自真实开工/完成记录。

技术运行成功、自动检查通过、人工批准、计划发布和交接接受是独立事实。已有可核验文件的技术阻断运行允许人工修订，但仍须对所采用修订重新检查并满足全部送审条件。

演示任务按标题区分：输入待确认、编制与核验、待独立评审、退回修订、已批准待发布、计划交接、变更待复核。建议先用“工程师”查看编制稿，再切换“审核人”办理待评审样例，最后由“负责人”发布计划。变更样例保留历史批准和已开工记录，通过同一资料的新版本触发定向复核，不影响其他样例。

预置文档运行类型是 `demo_sample`，不调用模型、不伪造生成成功。真实生成需要在原配置入口提供可用模型、真实资料和适配模板；OA 放行不代表模型配置可省略。ONLYOFFICE 未部署时仍可使用现有正文修订与文档上传路径。

### 代码与接口位置

业务模块位于 `basic-service/app/src/service/rd_platform/`：`taskbook_workflow` 管理工作包与阶段，`taskbook_inputs/drafts/runs` 管理输入及运行，`taskbook_coverage/planning/release` 管理核对和固定送审，`plan_handoff/taskbook_changes` 管理下发和变更。原生路由在 `controller/rd_taskbook_controller.py`，前端在 `web/src/features/taskbook/components/workspace/`。

原生工作面接口为 `GET /api/rd/projects/{pid}/tasks/{tid}/taskbook`。其下 `draft`、`input-packages`、`precheck`、`runs`、`revisions/select`、`checks` 和 `submit-review` 承担对应动作；项目资料使用项目下的 `sources` 接口。阶段推进、WBS 保存、发布计划、接收交接与影响处理复用项目 `commands`。业务写入校验当前身份、项目版本和幂等请求键；私有草稿使用独立版本。

固定输入保存文件副本、参数、模型选择、模板/profile/mapping 及规则环境指纹。环境变化要求重新确认；当前没有任意历史规则版本回放能力。原生运行在派发前保存意图和归属，启动时恢复可信终态，无法确认的失联运行标记中断，由用户明确重试。

## Windows 启动与构建

以下命令从仓库根目录执行。需要 Node/npm，以及 Python 3.12 或 3.13；仓库镜像使用 3.13。首次部署参考根目录 `.env.example` 创建私有 `.env`，已有配置应保留。真实凭据不放入 Git。

```powershell
Set-Location web
npm ci
npm run build
Set-Location ..
.\start.ps1
```

`start.ps1` 创建或复用 `basic-service/.venv`、安装 `basic-service/requirements.txt`，以 `basic-service/app` 为工作目录后台启动主服务及管理服务。默认主站为 `http://127.0.0.1:18130/rd`，管理服务为 `http://127.0.0.1:18131/admin`。`JTB_HOST`、`JTB_PORT` 可调整主服务监听；管理服务使用 `JTB_FEEDBACK_HOST`、`JTB_FEEDBACK_PORT`。脚本拒绝占用端口。用根目录 `stop.ps1` 停止脚本启动的两个进程。

只调试主后端时，可在 `basic-service/app` 执行 `..\.venv\Scripts\python.exe -m src.main`。前端开发在 `web` 执行 `npm run dev`，默认地址 `http://127.0.0.1:5173`，代理后端 18130、管理端 18131；修改后端端口时需同步 `web/vite.config.ts`。

日志位于 `basic-service/app/logs/`，启动日志为 `backend-startup.{stdout,stderr}.log` 和 `feedback-startup.{stdout,stderr}.log`。`/api/health` 只证明应用健康，不能证明 OA 或模型可用。已有 Compose 部署方式见 [README](../README.md)；默认仅在本机发布容器 80 至宿主 18130。

## 统一身份与首次建档

以下说明适用于 `JTB_DEMO_MODE=false` 的非演示部署。研发接口要求 `src.common.platform_auth.get_current_user` 建立的已验证身份，不能通过请求体指定操作人。仅关闭 `JTB_AUTH_ENABLED` 不提供研发身份；外网体验应使用上述演示开关。演示模式的身份来源明确返回 `source=mock`，不能作为真实企业员工身份使用。

部署变量示例采用仓库内网预设，应用编号须由现场确认：

```dotenv
JTB_AUTH_ENABLED=true
JTB_AUTH_APP_ID=127
JTB_AUTH_PLATFORM_BASE_URL=http://172.23.255.36
JTB_AUTH_PUBLIC_URL=
```

OA 登录应用编号与模型服务的 `MODEL_APP_ID` 分开配置。空 `JTB_AUTH_PUBLIC_URL` 自动跟随入口的协议、主机与端口；使用其他主机需配置 `JTB_AUTH_CALLBACK_HOSTS`，或用 `JTB_AUTH_PUBLIC_URL` 指定固定 HTTP(S) origin。反向代理须保留实际入口 Host 和端口，并正确处理 HTTPS。

已保存的登录配置 `basic-service/app/runtime/auth_settings.sqlite3` 优先于部署环境变量；可用 `JTB_AUTH_SETTINGS_DB` 指定位置。登录设置变更后重启服务。主站设置只读，由现有管理员入口授权的配置维护者修改；详见 [统一登录说明](platform-auth-migration.md)。研发项目负责人职责独立于管理后台授权。

首次业务流程：

1. 经统一登录进入主站，确认 `/api/current-user` 中 `authenticated=true`、`user.verified=true`，记下 `user.userid`。
2. 打开“研发项目”创建项目，创建者自动成为负责人。负责人登记成员的真实平台用户 ID，分配工程师、审核人或只读职责；显示姓名不作为权限依据。应确认现场平台 ID 对同一员工稳定。
3. 登记需求、来源、验收描述，解决必需项澄清后确认需求基线。
4. 登记改型/新研批准与流程模板，创建任务书工作包，指定不同的执行人与审核人。负责人可审核他人编制的成果；编制人和送审人不能自批。
5. 按上述原生流程完成输入确认、编制、修订、覆盖核对和 WBS；保留原生成参数口径，例如研制阶段 `F/C/S/D`。
6. 送审固定版本，审核人批准或退回；负责人发布已批准计划，接受人接收后开始正式任务。上游变化进入定向影响处理。旧通用任务仍保留登记成果和采用基线入口。

## 存储、备份与恢复

| 数据 | 默认位置或配置 |
| --- | --- |
| 研发数据库 | `basic-service/app/runtime/rd_platform.sqlite3`；`JTB_RD_DB` 可指定路径 |
| 固定成果文件 | 默认在研发数据库同级 `rd_artifacts/`；`JTB_RD_ARTIFACTS` 可指定路径 |
| 生成输入及输出 | `JTB_UPLOAD_DIR`、`JTB_OUTPUT_DIR`，或 `basic-service/app/resources/application-{dev,test,prod}.yml` 的 storage 配置 |
| 文档修订与审阅归档 | 当前输出目录下 `reviews/` |

研发数据库目前使用 schema `user_version=2`，首次访问自动初始化或从版本 1 增量升级，增加 `taskbook_runs` 与 `taskbook_drafts`，保留旧项目、任务、成果、审签及绑定 ID。旧任务继续作为通用任务，不按名称自动转为已完成的业务节点。数据库保存项目聚合、版本、事件、生成绑定和幂等结果；固定成果保存独立文件。公开成果引用为受控下载地址，数据库内部保留文件路径及 SHA-256。下载再次核验哈希；文件缺失或被修改时拒绝使用。

备份时先停止本实例并确认没有写入，再将研发数据库、固定成果目录、生成输入/输出及审阅归档一起备份。正式环境还应纳入 `runtime/` 中的登录、凭证等现有配置存储，按敏感数据管理。只备份 SQLite 无法恢复文档字节。恢复时保持数据库引用的成果绝对路径，或先实施受控路径迁移；不要仅移动成果目录后修改环境变量。恢复后检查项目详情、历史决定和批准版下载哈希。

当前按单应用实例运行，使用 SQLite 事务串行提交研发命令，生成队列仍在进程内。没有多实例协调、持久任务队列或容量承诺；不要据此增加多个 workers/副本共享同一套运行目录。服务中断后需核对原作业状态并显式重试，不能假定自动续跑或自动登记成果。

## 开发检查与真实服务前提

在仓库根目录安装开发依赖并运行统一检查入口：

```powershell
.\basic-service\.venv\Scripts\python.exe -m pip install -r basic-service\requirements-dev.txt
python scripts/check.py rd
python scripts/check.py backend
```

前端验证使用 `web` 下 `npm run build`，包括 TypeScript 检查与 Vite 构建。新领域测试使用临时 SQLite、真实文档字节和隔离测试身份；这些结果不能证明真实 OA、模型或 Office 联调成功。本次研发业务改造尚未以真实企业账号和模型完成完整业务验收；既有 README 的历史 OA 联调记录有其独立范围。

浏览器回归脚本为 `tests/e2e/rd_browser_smoke.py`，手动运行，不参与默认 pytest 收集。先构建前端，在仓库根运行：

```powershell
.\basic-service\.venv\Scripts\python.exe -m pip install -r basic-service\requirements-browser.txt
python scripts/check.py e2e --case rd_browser_smoke.py
```

浏览器安装与可执行文件设置见 [开发指南](development.md)。

脚本启动临时回环服务、使用临时数据库和文件，仅在测试进程替换企业令牌验证器；生成文档使用确定性 DOCX 夹具，不访问真实 OA 或模型。真实 UI 验证建项目、成员、需求基线、任务、接单、生成上下文确认、固定成果登记、送审及独立批准；随后校验批准文件哈希、四个非成员访问拒绝场景和 390px 页面布局。运行结束关闭服务，证据及截图保存在忽略提交的 `basic-service/app/runtime/rd-browser/`。本次这些检查均通过，不代表生成模型的工程质量验收。

现场仍需准备：

- 可达且配置正确的 OA 应用、至少两名不同用户和稳定的员工用户 ID；确认单人审签制度符合现场要求。
- 可用模型服务、访问权限及匹配的模型参数。既有“服务凭证设置”或 `.env.example` 的 `MODEL_*` 等配置入口继续使用；页面保存的模型凭据有独立持久化与优先级规则，见 README。
- 实际项目资料、适用的受控模板、规则及引用资产。演示 DOCX 和测试替身不能替代工程输入或正式 QA。
- 如需完整 Office 版式编辑，准备 ONLYOFFICE Document Server，以及 `JTB_REVIEW_EDITOR_URL`、`JTB_REVIEW_EDITOR_INTERNAL_URL`、`JTB_REVIEW_PUBLIC_URL` 和双方一致且至少 32 字符的 `JTB_REVIEW_EDITOR_SECRET`。浏览器能访问编辑器，编辑器能访问文档及回调地址。未配置时可使用现有正文编辑；部署模板见 `docker-compose.review.yml`。

当前已支持 WBS 条目、依赖检查和计划甘特，未包含关键路径计算、智能排程、多人会签、代签/紧急放行、BOM/CAD/CAE/LIMS/ERP 集成、旧作业批量导入、通用流程引擎或正式容量验收。批准成果及旧基线保留为历史，不提供把旧成果直接改标为满足新基线的入口。

首版初始验证：相关后端回归114项、前端测试9项及构建/浏览器流程通过，QA证据留存、澄清重复生成和跨任务恢复问题已修复。

2026-10-28 整体重构验证：当前相关后端回归106项通过；后端专项认证/管理/领域验证220项通过、4项跳过；原生成链路专项26项通过。当前前端请求、上下文、导航及跨分页定位测试11项通过，TypeScript/Vite构建通过125个模块。演示与非演示两种浏览器业务闭环、角色切换、独立审签、下载哈希、手机导航和390px布局均通过。演示证据位于 `runtime/rd-demo-browser/`，非演示证据仍在 `runtime/rd-browser/`。独立复核发现的分页定位、企业退出登录及Windows自定义端口停服问题均已修复；默认端口与自定义端口实际启停验证通过，其他已有服务保留。

代码保留在本地分支工作区，尚未提交或推送。当前主页面按演示方式运行，无需OA登录。

## 2026-10-28 任务书内化验收

最终相关后端回归 **206项通过**，前端行为测试 **26项通过**，TypeScript/Vite生产构建通过144个模块。后端仅有现存Starlette/httpx弃用提示；前端有主包超过500kB的体积提示，均非失败。四个核心生成文件SHA-256与本轮改造前相同。

`tests/e2e/rd_taskbook_browser_smoke.py` 使用真实隔离SQLite/API、明确标记的演示身份和预置文档，验证任务内文档呈现、五工作区、私有草稿刷新、WBS模板下载导入及错误保留、独立批准、批准文件精确哈希、负责人发布、接收后开工、资料变更保留历史，以及观察员只读。1440px和390px没有整页横向溢出，浏览器无页面异常、无外部网络请求。截图及 `proof.json` 位于 `basic-service/app/runtime/taskbook-native-browser/`。

复跑命令（仓库根目录，先构建前端）：

```powershell
python scripts/check.py frontend
python scripts/check.py rd
python scripts/check.py e2e --case rd_taskbook_browser_smoke.py
```

已在现有演示数据库启动最新服务，校验到三个项目、七个原生任务书工作包及定向变更记录。真实模型生成质量、企业审批制度和客户模板的现场验收仍需使用实际资料与服务完成。


## 本轮验证（角色与业务路线重构，2026-10-28）

- 157项研发领域/API/演示/任务书测试通过；50项前端行为与组件测试通过；TypeScript与Vite生产构建通过。构建仍提示主JS包超过500kB，未调整其警告阈值。
- 真实独立服务、SQLite及Edge验证通过：4身份切换、3项目区域、选型保存、直接选用实际接收登记、直接路线已有任务可达、旧URL/分页/锚点，以及评审默认打开固定审签。1440px和390px均无整页横向溢出，未出现浏览器脚本错误；该验证未调用OA、模型或外部专业系统。
- 证据：`basic-service/app/runtime/role-journey-browser/proof.json`与同目录截图。复现命令：从仓库根运行`python scripts/check.py e2e --case rd_journey_browser_smoke.py`。
- 原任务书`jonhon_taskbook`与`pipeline_cli.py`相对本轮前快照没有代码变化。旧生成逻辑、来源约束、修订与审签继续沿用；当前可运行演示已重启在http://127.0.0.1:18130/。

扩展历史回归未作为全通过声明：全量1889项收集成功，长时间运行后停止；定位到4个可单独复现的失败，位于本轮未改动区域：`test_windows_stop_uses_saved_ports_and_never_stops_unrelated_process`（停止脚本测试对象缺少ParentProcessId）；`test_queued_cancelled_submission_has_complete_server_snapshot_and_isolated_crud`（测试配置缺少logs_dir）；表格格式的两组`test_imported_table_and_indicator_keep_column_ratios_at_same_body_width`（封面表格tblLook属性发生差异）。本轮没有为了通过这些测试改写任务书版式算法。

本轮已修正独立审阅发现的问题：直接选用保留既有任务入口；原生历史批准包不提升为当前版；无关需求换版沿用定向输入适用性；待核实/待复核选型进入负责人待办；成功重试后历史失败留在运行历史。


## 角色边界复核（2026-10-28）

已撤除上一轮额外加入的技术负责人、领导、知识治理、IT运营工作台视角，以及成员设置中的第二层workbench_role。知识治理和IT运营属于所属平台的管理职责；技术协调由具体项目任务承接，不默认新增一类可分配权限。

首页待办只依据实际负责人动作、任务执行人与指定评审，不按职位名称或资料缺项自动给人派工作。保留项目负责人、工程师、独立评审三类办理职责，只读访问按需授予。重复的首页职责说明卡片移除，成员设置改为按需展开。

停止自动增加演示成员，并对既有演示库进行一次有证据的清理：仅移除能证明由旧迁移自动添加、内容未被修改且没有任务、意见、历史、运行或草稿引用的成员；保留手工配置和业务历史。旧的四个额外演示身份不再可选，已有相关cookie按只读身份处理。项目汇总不再附带只服务于运营视角的运行投影，原生任务内的运行历史仍可查看。

## 小航与模型迁移（2026-10-28）

小航默认以动效人物呈现，点击后打开可调宽度的右侧工作栏，收起恢复人物。单一对话自动识别导航、业务问答、业务操作和普通问题；只有业务意图读取当前身份有权访问的项目事实。需求、任务、选型、独立审签和计划发布复用已有领域命令，先形成十分钟固定草案、再显式确认执行；模型推理期间项目发生更新时拒绝旧上下文草案，不静默覆盖。

统一模型配置已从原任务书项目及其 `codex/taskbook-expand-16-types` 外网工作区迁移；凭证只存在 Git 忽略文件与服务端数据库。小航独立选用实测可用的 DashScope/qwen-plus，任务书原有模型选择与生成规则保持。用户旁设置、退出复用原项目组件，本地退出后不自动恢复负责人身份。

能力注册表支持受控的领域命令、脚本和 skill 处理器，尚未配置的脚本/skill 不会仅凭聊天文本执行。扩展协议、接口和验证入口见 [小航助手](xiaohang-assistant.md) 与 [模型迁移](model-configuration-migration.md)。

本轮浏览器覆盖右栏占位、三种伸缩方式、1440/1200/980/390px、动效/减少动效、业务草稿保留、中文输入、停止/重试、操作确认和会话退出。真实模型验证使用最小问候及临时合成项目，不修改当前项目资料。全站严格 UI 静态审计仍有19项旧组件问题，本轮新增小航和平台壳无对应发现；既有 `feedback.browser.mjs` 的生成反馈部分仍假定根路径为旧独立工具，未适配当前 `/taskbook` 路由和身份协议，因此不声明该历史脚本已通过。
