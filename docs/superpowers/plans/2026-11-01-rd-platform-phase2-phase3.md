# P2–P3 完整代码改造实施计划

> **For agentic workers:** 使用 superpowers:subagent-driven-development 按本计划并行实施、集成和验收。用户已明确要求完成 P2–P3；本计划在应用代码修改之前形成，不重新请求执行授权。

**Goal:** 完成获准资源上的流程设计、固定采用与真实执行，以及有来源的有限补缺和完整目标模板派生治理，同时保留原任务书引擎。

**Architecture:** 继续由研发 Store 持有业务事务及唯一调度，Workspace 管理固定资源、发布与应用授权。图形和表单共用结构化草稿，编译为现有 Worker 的固定 DAG；本体补缺在一个受托动作内部有限循环，模板派生复用现有受控资产生命周期。

**Tech Stack:** React/TypeScript/Vite、FastAPI/Python、SQLite、现有 DOCX/Profile/mapping 工具；不引入第二个调度器或外部流程产品。

**Spec:** `2026-11-01-rd-platform-alignment.md` 第 5、7、8、9 节及 P2/P3 退出条件；《主题方案/03-Workspace资源与智能执行.md》专家团、两类模板、结构化修改及授权规则。保留 P2A 工作树全部已有修改。

## 全局约束

- 分支 `codex/rd-platform-rebuild-20261031`；不修改原工作树，不推送，不自动提交用户的既有改动。
- 原 `engine_bridge.py → src.pipeline_cli.run_pipeline`、受控资产和写入/QA 主链保持；不得创建简化文档生成器。
- 工作包提交后内部自动执行，缺证据准确停止；业务批准保持独立，不能由模型、模拟或运行成功替代。
- 外部 Workspace/本体/K-box 仍未连接；使用实际上传资料和本地受控规则，示例提供者不能提供生产事实。
- 新版草稿/候选/采用/Run 分开；旧 Run 与来源、模板及资源固定版不被编辑覆写。服务端重新验证权限、输入版本、内容摘要和幂等键。
- 两类业务模板和专家团内部图分域；只允许已注册的六个执行器入口，未绑定资源不能因绘图而执行。依赖独立节点由当前 Worker 串行调度。
- 有限分支按有效业务决定确定选型/改型/新研路线；任意表达式、循环、并行调度结构明确阻断。
- 保持中文 JONHON 界面、自然滚动、窄屏布局、共用弹窗退出行为；后台路径和配置不得泄漏到普通目录。

## 领域与接口合同

1. `FlowDraft`：固定目标工作包/业务模板、revision、input_revision、结构化 graph、来源、已确认字段。节点有唯一 id、固定 action/resource 引用、标题、角色、交付物、位置；边有唯一 id 和 source/target。复制产生新 id，不复制运行事实。
2. `ExecutionCandidate`：固定草稿 revision、语义/布局摘要、资源锁、compiled_plan、业务节点→动作实例→内部步骤映射、结构化 validation、差异/影响。准备后不可变。
3. `ExecutionAdoption`：candidate_id/digest、actor/time、前次采用引用。新 schema 提交必须使用采用候选；旧 schema 仅兼容历史服务端产生的对象，不接受客户端降级。
4. 项目写入继续 `POST /api/rd/projects/{pid}/commands`：`create_flow_draft`、`apply_flow_patch`、`validate_flow_draft`、`prepare_execution_bundle`、`adopt_execution_bundle`、`simulate_execution_bundle`、`restore_flow_revision`。沿用 expected_version、case_id、Idempotency-Key；具体 DTO 由领域模块统一返回，不由控制器复制校验。
5. Patch 统一 `{origin: manual|assistant|dialogue, base_digest, expected_draft_revision, operations}`。支持增删/复制节点、增删边、设置属性、移动位置；助手改已确认约束形成冲突，不覆盖。图、表单和结构化建议共用同一操作集。
6. 专家团是 Workspace `team` 固定资源，具有 members、输入输出合同和 execution_graph，展开为实际 Skill DAG；内含资源可作为依赖授权而不独立列目录。旧 Skill ID 不变。团队发布、应用授权、项目采用互不替代。
7. WorkflowTemplate 区分 selection/research；固定业务节点和关口，采用后状态从现有业务事实投影。直接选用不创建研发包；任务书仍位于 planning，scope decision 后进入 design。
8. `CompletionSession` 固定 policy/input/rule/provider；每轮记录稳定 obligation key、queries、引用候选、接受/拒绝、remaining、usage。stop_reason 包括 converged/no_new_evidence/conflict/max_rounds/budget_exhausted/deadline_exceeded/cancelled/permission_revoked/source_invalid。无模型调用则不虚报 tokens。
9. 每轮证据由活跃 claim 的 fenced progress checkpoint 保存；取消和预算停止在 Store 所属事务保存截止点，迟到结果不能重写。结果/历史授权读取，不暴露任意本地文件路径。
10. `DerivationCandidate` 固定基线和目标、批准差异规则、适用范围、目标专业依据、DOCX/Profile/mapping/规则/来源/回归资产及摘要。结构复用不等于工程认可。现有 ControlledAssetLifecycle 负责审核/发布/回退，新能力不能绕过旧发布入口的权限。

## T1：完整设计领域与实际执行映射（P2）

**Owner:** P2 backend；`rd_platform/designer.py`、`workflow_templates.py`、`workspace.py`、`catalog.py`、`store.py`、`runtime.py`；不改 controller/executors/engine_bridge。

- [x] 先补领域行为测试：统一 patch、保存重启、环/悬空边/必需关口/输入输出/资源版与权限、坐标不触发执行。
- [x] 建立两类业务模板固定定义与治理、专家团合同与可验证内部图；获准根与依赖授权分开，不泄漏隐藏依赖。
- [x] 实现草稿/CAS、校验、差异、不可变候选、采用历史、从历史恢复新草稿；在途只能另起修订，不能覆盖 Run。
- [x] 编译专家团为既有执行 DAG，保持旧 role adapter；previous_results 按显式生产者绑定，重复同名节点结果独立，不取任意最后值。
- [x] 新版提交重验采用候选及资源，保存 business_node_id/action_instance_id/step_instance_id/run_id 映射；实际执行图等于采用图。
- [x] 纯模拟 normal/missing_input/rejected/cancelled 不写生产 Run/决定/制品、不调用引擎。
- [x] 在 Store.progress 增加 P3 checkpoint 集成：识别 `completion_checkpoint` payload，保存 node/run/fencing/轮次与去重摘要；停止原因随取消/预算事务留存。将确切合同通知 P3 owner。
- [x] 测试目录、资源、Store、Worker、历史 v1/v2；保存/准备不运行、重复幂等、错版和撤权拒绝、重启、旧回调、同名实例。

## T2：有依据补缺与完整模板派生（P3）

**Owner:** P3 backend；新 `rd_platform/completion_loop.py`、必要扩展 `completion.py`/`executors.py`；新 `jonhon_taskbook/template_derivation.py`、扩展 `asset_lifecycle.py`；不改 Store/controller/原 pipeline/engine_bridge。

- [x] 先补失败测试：有依据字段/章节/表格可补，无依据/冲突/越权/变更来源不能补；所有停止条件留完整证据。
- [x] 有限循环调用当前固定来源，准确验证 source id/version/hash/location 和批准映射。扫描不只针对人工标记；合理空白、历史内容、原引擎负责装配义务不误填。
- [x] 固定 policy（默认轮数 3、查询 100、候选 200、120 秒；仅运行控制值，非工程标准）；输入校验并受工作包总预算限制。
- [x] 每轮 `progress({'completion_checkpoint': ...})` 后才继续；取消/预算输出终止原因，已完成轮次可查询；去重和恢复不得重新采纳被拒绝值。
- [x] 接入原 content_completion；保留 ledger/ready/generation_ready/conversion_review 字段以及审阅稿与正式交付的区别。仅确定性有依据值进入原生成链可消费台账。
- [x] 实现目标差异包验证与派生，复用 outline editor/onboarding；禁止只改名称发布高频模板，目标指标/方法/判据有来源且适用。
- [x] 完整资产摘要和真实回归证据绑定审核；缺资料候选准确 blocked。发布按目标产品/领域 CAS，回退只恢复目标绑定，不覆盖无关后续发布。
- [x] 提供清晰的 Python/API DTO 合同给 root 和前端；原候选/版本功能兼容，不能保留旧权限绕过。
- [x] 补缺、派生、生命周期、原 engine 合同及样本回归测试。

## T3：完整画布和证据/治理界面（P2/P3）

**Owner:** frontend；`web/src/features/rd/`、相关浏览器测试、DESIGN.md/UX-CONTRACT.md。独占 types/api/页面改动。

- [x] 统一 draft reducer：图与表单共享；拖动、键盘位置、节点增删复制、连线编辑、属性、撤销重做和结构化建议差异。
- [x] 编辑器明确显示对象/版本/状态；保存、校验、差异、采用、执行独立；409 保留草稿，权限失效清空敏感信息，历史/运行图只读。
- [x] 流程页补总览、选型/研发模板、专家团动作和固定组成；项目入口实际采用并显示执行映射，不以卡片替代能力。
- [x] Workspace 内部图在维护权限下编辑，项目只读组成；不让研发业务编辑改共享资源。
- [x] 补缺轮次/引用/拒绝/剩余义务/用量/停止原因面板；派生目标、差异、资产与验证结果、独立审核发布入口；普通项目采用发布版无需再审批。
- [x] 浏览器覆盖实际交互、短屏和窄屏、错误/空/权限/CAS、图表一致、只读历史；每类流程留截图。记录模拟与真实接口验证区别。

## T4：HTTP 边界与全链联调（root）

**Files:** `controller/rd_controller.py`、必要 `controller/taskbook_controller.py`、HTTP/integration 测试、计划/验收记录；等各 owner 输出合同后接线。

- [x] 新目录、业务模板治理、派生读取/写入统一身份和源校验；发布者/授权者/项目负责人权限分离。旧 candidate publish/review/rollback 同样受检。
- [x] 校验请求中的路径/文件引用，不接受任意服务器路径或自报批准；上传仍保存原件和 hash，派生使用实际受控资产/授权项目来源。
- [x] 验证跨项目访问、未授权/隐藏资源详情/分页/下载、幂等/CAS、旧接口绕过及恶意候选证据。
- [x] 重启本地测试实例，走真实保存→校验→候选→采用→Worker→结果，核对固定图摘要与节点输出；试运行不调用模型。
- [x] 原任务书专项回归和真实管路样本按已确认两文件/六参数核对；不通过交付门禁如实记原因，不降低阈值。
- [x] TypeScript/Vite、关键 Python 测试、浏览器交互和独立 spec/质量复核；问题修复后重跑相关验证。

## Review Focus

1. 同名节点和跨团队输入不能串结果：T1 测明确 producer，T3 测复制无状态。
2. 撤权、来源变更、候选后新版与迟到结果：T1/T4 覆盖采用、领取、checkpoint、完成的版本和权限。
3. AI patch 不能覆写已确认关口，模拟不能签署或写正式产物：T1/T3 测结构化冲突与零执行调用。
4. 模板只改名称、伪造回归布尔值、改 Profile 后旧批准、回退覆盖其他产品：T2/T4 必须阻断。
5. 补缺取消/预算与格式转换仍需复核：T2/T4 保存证据，不把 review copy 标为正式可交付。

## 迁移、回退与验收

只新增本地表/可选字段及版本化资源，不原地迁移旧运行快照；新模板版本不会替换已采用版。现有 P2A schema 保持兼容。所有新状态写入均为事务/CAS/幂等；回退代码不能用旧库覆盖已产生的新事实。

完成证据记录在 `docs/rd-platform/verification/2026-11-01-phase2-phase3-execution.md`，逐项映射 T1–T4，区分单测/真实 API/浏览器/模型生成/客户端验证。无企业专业高频资料时不发布伪造目标模板；交付的是可验证的派生能力、测试夹具成功例及真实缺证据阻断回执。P4 外部厂商接入、P5 全业务专业系统不在本次用户指定 P2/P3 范围。

## 最终验收

T1–T4 已完成，独立复查 R1–R8 均关闭。详见 [完整验收记录](../../rd-platform/verification/2026-11-01-phase2-phase3-execution.md)。原样例生成复核稿，旧 DOC 转换门禁保留；不将代码通过等同正式工程交付。T2 实施过程中由 root 追加委托 P3 owner 完成派生控制器及旧治理入口接线，接口权限仍在 T4 统一验证。
