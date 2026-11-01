# P0＋P1 首批开发任务：业务阶段纠偏与任务书能力保护

> **待评审，不是已完成记录，也不授权立即实施。**
>
> **For agentic workers:** 使用 superpowers:subagent-driven-development 或 superpowers:executing-plans 执行已获确认的任务。勾选项只在相应行为验收通过后更新；不要把文档中描述的接口当作当前已存在接口。

**Goal:** 使新业务按“需求确认→选型决定→研发启动→任务书策划→范围批准→工程设计”运行，保留旧项目、旧工作包和原生成能力。

**Architecture:** 增量扩展现有 Project/Case、命令事务、幂等回执和工作包执行。新流程使用明确政策版本；旧记录保持原语义。生成仍经过现有 engine_bridge。

**Tech Stack:** 现有 Python / FastAPI / SQLite、React / TypeScript / Vite，不新增流程引擎依赖。

**Spec:** [总开发计划](2026-11-01-rd-platform-alignment.md)，其中第 2、3、6、10、12 节是本批约束；来源见[资料索引](2026-11-01-rd-platform-evidence.md)。

## 全局约束与评审前置

- 所有路径相对于服务根目录：
  `D:/桌面/ai-zhonghang/.worktrees/rd-platform-rebuild-20261031/zhonghang-service/agent-develop-task-doc-service`。
- 不修改 `pipeline_cli.py`、`jonhon_taskbook/`、受控 DOCX/Profile/mapping/规则来迁就业务页面。若发现引擎问题，另列有样本的修复计划。
- 源文件、原始候选、采用值、业务决定、技术运行和正式交付状态独立。
- 不改变旧执行包的节点 ID、来源摘要、模板和模型；不以读取数据为由生成批准记录。
- 首批不实现完整专家团管理、自由拖拽连线、跨平台回调或 CAD/CAE 接口。这些已列入后续批次。
- **需要在 T3 开始实施前确认的制度项：** 选型决定、研发启动和任务书范围批准各自由谁办理，哪些必须使用企业正式审签。设计支持独立范围记录；不默认 OA 管理员有工程签署资格。本地演练记录标为 local_review，不能自动满足 formal_review 政策。

## Review Focus

1. 已生成过任务书的历史项目没有研发启动证据：保持历史状态，不据此造批准，测试归 T1/T7。
2. 需求确认时收到新来源或并发修改：确认旧版失败，保留编辑和来源，测试归 T2/T5。
3. 选型报告批准后被替换或路线变化：启动/模板采用拒绝错版，测试归 T3。
4. 旧 design 工作包运行期间启用新策划流程：原 Run 继续按旧快照，不换包、不重发，测试归 T4/T7。
5. 文件已生成但 QA 或工程范围未通过：能查看复核稿，不能下发正式设计任务，测试归 T4/T6/T8。

## 文件职责

以下“新增”均为拟定实施文件，本次不创建应用模块。

| 文件 | 操作 | 职责 |
|---|---|---|
| `service/rd_platform/lifecycle.py` | 新增 | 业务政策版本、阶段准入、需求确认及启动/范围状态推导；不执行模型 |
| `service/rd_platform/review_records.py` | 新增 | 固定报告包、审查提交/决定、资格政策调用；不自行授予身份 |
| `service/rd_platform/migration.py` | 新增 | 只读迁移预检、显式转换计划与接受报告 |
| `service/rd_platform/store.py` | 修改 | 调用上述领域模块；保持事务、幂等、权限和唯一主账 |
| `service/rd_platform/catalog.py` | 修改 | 按版本解析旧/新工作包与适用阶段，保持旧 ID 映射 |
| `service/rd_platform/case_records.py` | 修改 | 需求、比对、工程关口与新业务基线关联 |
| `service/rd_platform/business_binding.py` | 修改 | 新流程绑定加入确认/决定/启动引用；旧指纹兼容 |
| `controller/rd_controller.py` | 必要修改 | 输入 schema/命令路由，不复制领域状态逻辑 |
| `web/src/features/rd/types.ts` | 修改 | 区分需求确认、业务决定、正式审签和流程政策 |
| `CaseDecisionForm.tsx / TaskbookPreparation.tsx` | 修改 | 语义明确的关口操作与策划入口 |
| `CaseProcessPanel.tsx / WorkpackagePanel.tsx` | 修改 | 在正确业务节点显示现有编排与状态 |
| `SourceAnalysisPanel.tsx / CaseOutcome.tsx` | 修改 | 参数依据、冲突和多维成果状态 |
| `web/src/features/rd/SelectionDecisionPanel.tsx` | 新增 | 选型报告核对/送审/决定与启动办理，按政策显示 |
| `basic-service/app/tests/rd_platform/` | 扩展 | 领域、HTTP、旧记录兼容与执行边界行为测试 |

表中 `service/` 和 `controller/` 均位于 `basic-service/app/src/`。不用一次性拆分整个 Store；只有被本批改变的业务逻辑迁入对应小模块。

## 计划接口

签名在实施时可按项目现有类型风格表达，但语义与字段不能自行变更。首批依旧通过项目命令事务调用，不提供独立绕过权限的写入口。

```text
LifecyclePolicy.resolve(case) -> Policy(version, required_decisions, applicable_stages)
confirm_requirements(case, command, actor) -> RequirementBaseline + ConfirmationReceipt
prepare_selection_review(case, command, actor) -> ReviewBundle
record_selection_decision(case, bundle, command, actor, policy) -> Decision
authorize_rd_start(case, command, actor, policy) -> ActivationRecord
record_taskbook_scope_decision(case, bundle, command, actor, policy) -> Decision
migration.inspect(project) -> MigrationPreview
migration.apply(project, approved_preview, expected_version) -> MigrationReceipt
catalog.definition(definition_id, version) -> FixedWorkpackageDefinition
```

共同命令外壳继续使用 `expected_version`、`Idempotency-Key` 和 case_id。领域快照在服务器生成，不接受客户端上传“已批准”完整对象。

拟定最小字段：

| 对象 | 必需字段与含义 |
|---|---|
| BusinessLifecycle | policy_version；selection_order_id；rd_activation_state；可空 rd_project_code；当前引用 |
| RequirementBaseline | id/revision；input_revision；条目固定内容；source_refs；确认主体/时间/范围；digest |
| ReviewBundle | id/kind；固定对象及报告引用；输入/模板/产品证据版；digest；review_mode；required_policy_ref |
| Decision | id/kind；bundle_id/digest；verdict；scope；actor；qualification/policy_ref；时间；是否正式签署；失效原因 |
| ActivationRecord | id；有效选型决定；需求基线；授权范围/依据；主体与时间；状态 |
| Workpackage v2 | 固定 definition_version；business_node_id；plan_revision；输入和模板引用；run 关联 |
| MigrationPreview | 原版本/摘要；目标政策；引用映射；不可确定字段；活动 Run；可转换性；预检摘要 |

不能让同一个 `approved` 同时表示“需求已确认、模型核验通过、电子审签通过”。

## T0：固定生成与数据基线

**输入：** 当前研发工作树、旧任务书分支、已提供的液冷样本和当前本地数据。
**产出：** 可复核 manifest 与差异清单；不更新生产对象。

**Files**

- 新增文档：`docs/rd-platform/baselines/taskbook-parity-manifest.json`
- 扩展测试：`basic-service/app/tests/rd_platform/test_engine_contract.py`
- 复用已有任务书专项测试，不增加“源码中必须出现某字符串”的镜像测试。

- [ ] 记录当前分支、基线提交、未提交文件清单；经确认的代码提交与数据备份分开办理。
- [ ] 读取两份来源原件、模板/Profile/mapping/规则 hash；记录液冷管路六参数和允许差异。缺文件写 missing，不用名称近似文件替换。
- [ ] 对桥接行为补测试 `test_bound_pipeline_receives_exact_context_and_assets`：捕获调用边界，断言来源角色、六参数、固定资产、模型和生成模式完整传入。不能用该桩测试声称文档质量通过。
- [ ] 执行测试；另登记真实样本输出、内容核查、Word 客户端结果与已有未通过项，保持证据类别分开。
- [ ] 评审 manifest；确认后再进入新业务逻辑修改。

**验证命令（实施时执行）：**

`python -m pytest basic-service/app/tests/rd_platform/test_engine_contract.py -q`

接受标准：桥接无参数或资产降级；未执行客户端检查明确为未执行；不以哈希不同直接判模型生成退化。

## T1：业务生命周期版本与历史兼容读

**依赖：** T0。
**输入：** 原 Project/Case 与新政策定义。
**产出：** 所有后续任务共用的 LifecyclePolicy；旧记录可继续读取。

**Files**

- 新增 `basic-service/app/src/service/rd_platform/lifecycle.py`
- 修改 `store.py / catalog.py`、`web/src/features/rd/types.ts`
- 新增 `basic-service/app/tests/rd_platform/test_lifecycle_policy.py`

- [ ] 先写行为测试：旧无 policy_version 记录解析为 legacy_v1；没有授权记录则 rd_activation_state 为 historical_unverified，rd_project_code 不补造；读取不写数据库、不改变快照 hash。
- [ ] 新建案例使用首场景政策 v2；生成 selection_order_id，但无批准前不分配正式研发编号。
- [ ] 流程政策由服务端和已采用固定定义确定，客户端不能提交 legacy_v1 来绕过新流程准入。
- [ ] 先登记首场景固定选型流程定义，引用现有输入/需求/比较办理能力；不宣称已有通用模板编辑器。P2 再补目录治理与设计器。
- [ ] 定义独立的确认/启动/范围决定准入，不把八个阶段统一解释为同一审签。保留原 stage 字段兼容，由明确映射提供新业务展示。
- [ ] 同意图重复创建/命令返回原回执；同键异意图和错 expected_version 返回冲突。
- [ ] 运行本任务测试及原 Store 的版本/权限/幂等测试，检查没有给原项目添加虚构业务事实。

**验证：**

`python -m pytest basic-service/app/tests/rd_platform/test_lifecycle_policy.py basic-service/app/tests/rd_platform/test_store.py -q`

## T2：固定需求确认，移除默认额外审签语义

**依赖：** T1。
**接口：** `confirm_requirements(case, command, actor)` 产生 RequirementBaseline 与确认回执。

**Files**

- 修改 `lifecycle.py / store.py / case_records.py`
- 修改 `CaseDecisionForm.tsx / types.ts`
- 新增 `basic-service/app/tests/rd_platform/test_requirement_confirmation.py`

- [ ] 写测试：非空有来源需求可确认并进入选型；不存在新增独立审批任务；旧版/冲突/未闭合关键澄清按政策拒绝。
- [ ] 将原文、采用值、答复和拒绝候选分开；确认仅锁定当前采用条目与来源，拒绝项不被批量恢复。
- [ ] 服务器生成固定基线和 digest；新输入使相关确认待复核，保留原确认。
- [ ] 新流程调用明确的 confirm_requirements 命令；legacy_v1 的 advance_stage 保持原兼容语义，不能自动重写其历史。
- [ ] 服务端对 v2 收到的旧 advance_stage 命令执行同一新准入校验或返回 422，不能绕过需求确认、选型决定、研发启动和任务书范围批准；仅 legacy_v1 沿用旧语义。增加直接 HTTP 调用旧命令的绕过测试，不能只测试新前端按钮。
- [ ] 界面使用“确认需求并进入选型”，来源/缺口可定位；企业额外必审以显式政策表现，不写成全场景默认。
- [ ] 验证并发修改失败后用户草稿和定位不丢失。

**验证：**

`python -m pytest basic-service/app/tests/rd_platform/test_requirement_confirmation.py -q`

## T3：选型报告决定与研发启动分开

**依赖：** T2；实施前必须明确本批采用的工程决定政策。
**接口：** prepare_selection_review、record_selection_decision、authorize_rd_start。

**Files**

- 新增 `basic-service/app/src/service/rd_platform/review_records.py`
- 修改 `store.py / case_records.py / lifecycle.py`
- 新增 `SelectionDecisionPanel.tsx`
- 新增 `basic-service/app/tests/rd_platform/test_selection_activation.py`

- [ ] 测试：保存路线建议不激活研发；未生成固定选型报告或批准错版不能启动；直接选用不生成研发 WBS/编号。
- [ ] 根据已有逐项比较形成可核对的选型报告工作稿，固定需求、产品配置/来源、比较、路线、模板与报告内容版。真实逐项统计不得用 30/90%/50% 常量替代。
- [ ] 明确送审、决定、退回、重新形成报告的记录；资格检查独立于 OA 管理员名单和项目读写权限。
- [ ] 有效决定引用报告包 digest；需求、产品配置或路线变化令受影响决定待复核，不能启动旧版。
- [ ] 改型/新研通过独立授权记录激活策划；即便同一操作窗口办理选型与启动，也分别保存范围与回执。
- [ ] 本地演练可按已确认本地政策留具名决定，但必须标为非电子签署；正式政策缺失时阻断正式批准。
- [ ] 测试响应丢失后按原意图重试，不能多次立项或重复分配编号。

**验证：**

`python -m pytest basic-service/app/tests/rd_platform/test_selection_activation.py -q`

## T4：把任务书移入策划业务节点，保留旧执行包

**依赖：** T1、T3、T0。
**接口：** versioned catalog.definition、任务书范围决定；原 execute 和 run_pipeline 签名不变。

**Files**

- 修改 `catalog.py / store.py / business_binding.py / case_records.py`
- 修改 `TaskbookPreparation.tsx / WorkpackagePanel.tsx / CaseProcessPanel.tsx`
- 新增 `basic-service/app/tests/rd_platform/test_taskbook_planning_v2.py`

- [ ] 写测试：新 v2 已启动改型案例可在 planning 拉取任务书；未启动不能拉取；direct 路线不创建包。
- [ ] 为任务书定义新增固定 v2，明确 planning 阶段及 business_node_id；v1 仍保留原 design 适用性。catalog 查询版本必须精确，不以 latest 代替运行快照。
- [ ] 将需求确认、选型决定和启动引用纳入新业务绑定及输入指纹；旧绑定校验继续接受原算法，不现场重算改写历史。
- [ ] 新计划沿用原必需动作及依赖校验；提交前可加现有获准可选动作，提交后自动执行，不逐节点问人。
- [ ] 执行成功后保持策划业务关口，保存任务书固定成果；质量阻断或范围未批准时不能下发正式方案/详细设计任务。
- [ ] 任务书范围批准必须绑定当前成果和输入，通过后才允许新流程进入 design；不能只凭文件存在。
- [ ] 回归运行中的 v1 包：不迁移阶段、不改变 nodes/snapshot、不重复生成；取消与迟到结果拒收保持。
- [ ] 测试真实桥接依旧调用原 run_pipeline，不能引入新的简化生成路径。

**验证：**

`python -m pytest basic-service/app/tests/rd_platform/test_taskbook_planning_v2.py basic-service/app/tests/rd_platform/test_catalog_plan_preview.py -q`

## T5：六参数来源与补缺边界

**依赖：** T2、T4。
**输入：** 现有 source_analysis、业务决定、来源及澄清记录。
**产出：** 可采用的 ParameterFact 与固定上下文，不改变原引擎六参数枚举。

**Files**

- 修改 `analysis.py / business_binding.py / store.py`
- 修改 `SourceAnalysisPanel.tsx / TaskbookPreparation.tsx / contextLabels.ts`，复用已有中文标签函数。
- 新增 `basic-service/app/tests/rd_platform/test_parameter_provenance.py`

- [ ] 测试资料可确定的值直接显示来源；未知封面阶段不默认 S，冲突不默认选置信度较高值；产品分类别名不得暗中换成另一模板。
- [ ] 明确每个值的 source/decision/rule 引用及采用状态；中文展示和内部枚举分别维护。
- [ ] 用户只处理关键澄清和适用性确认；不重复手工填写已从资料正确识别的六参数。
- [ ] 保留正确为空的备注、模板说明及历史清理规则，不将它们当作客户指标缺失。
- [ ] 采用模板前核实已确定且来源有效；失败明确指出缺哪个参数、影响什么，不跳到隐蔽表单。
- [ ] 检查模型建议不能直接取得正式技术事实或审签身份。

**验证：**

`python -m pytest basic-service/app/tests/rd_platform/test_parameter_provenance.py -q`

## T6：用户工作面与状态展示

**依赖：** T2—T5。
**范围：** 修正业务入口和状态，不在本任务顺带实现 P2 完整设计器。

**Files**

- 修改 `CaseWorkspace.tsx / ScenarioWorkspace.tsx / CaseOutcome.tsx`
- 修改 `CaseDecisionForm.tsx / TaskbookPreparation.tsx / CaseProcessPanel.tsx`
- 修改 `FlowManagement.tsx` 的准确能力标注；完整专家团与目录授权留 P2A
- 新增 `web/tests/rd-lifecycle-v2.browser.mjs`

- [ ] 正常入口连通上传/需求确认/选型/启动/策划任务书；复用现有工作包画布及左右详情，避免再生成一个独立任务书首页。
- [ ] 用户看到“业务阶段、技术执行、质量门禁、工程决定”各自状态；复核稿可查看，正式下载/交接按门禁控制。
- [ ] 未实现的专家团不伪装成已发布能力；现有六函数展示为执行步骤/本地能力，并保留旧 ID。
- [ ] 页面原位错误、返回定位、跨页草稿、遮罩关闭及离开确认保持一致；无权限操作明确原因，不只禁用按钮。
- [ ] 浏览器测试覆盖窄屏滚动、主侧栏持续可见、弹窗滚动、画布列表切换和失败后重试；保存失败不清空草稿。
- [ ] 目录每页 5 条随 P2A 的服务端授权分页一并实现，避免只改前端数字却继续返回越权全量目录。
- [ ] 为每个 1—4 业务过程保存截图，标注真实数据/隔离测试数据。截图不是专业签署证据。

**验证：**

`npm --prefix web run build`
`node web/tests/rd-lifecycle-v2.browser.mjs`

## T7：迁移预检与旧项目续办

**依赖：** T1、T4。
**接口：** migration.inspect、migration.apply；apply 必须有固定预检摘要及显式接受。

**Files**

- 新增 `basic-service/app/src/service/rd_platform/migration.py`
- 新增 `basic-service/app/tests/rd_platform/test_lifecycle_migration.py`
- 新增 `docs/rd-platform/migrations/lifecycle-v2.md`

- [ ] 在离线副本建立测试：已完成、草稿、运行中、失败、取消、有/无真实启动证据各一类。
- [ ] 只读预检列出 ID/阶段/政策映射、未知事实、活动 Run、文件 hash、候选目标与不可迁原因；不自动接受。
- [ ] 旧无启动证明记录保持 historical_unverified；不从“文件已生成”推断工程批准。
- [ ] 活动运行留原 Owner；未执行草稿可按显式新计划采用，保留旧快照与来源。不能批量改 stage 字符串。
- [ ] 实施幂等迁移回执、expected_version、文件/对象总量核对；同一次接受重试不复制成果。
- [ ] 文档说明迁移后新写入的回退/对账方式，禁止恢复旧数据库覆盖新事实。
- [ ] 迁移预检通过不等于执行获准；实际数据写入另按确认范围办理。

**验证：**

`python -m pytest basic-service/app/tests/rd_platform/test_lifecycle_migration.py -q`

## T8：首链端到端验收与交付记录

**依赖：** T0—T7。
**产出：** 能复核的测试记录、截图、真实任务书样本和未通过项。

**Files**

- 新增 `basic-service/app/tests/rd_platform/test_first_scenario_v2.py`
- 扩展 `web/tests/rd-lifecycle-v2.browser.mjs`
- 新增本批验收记录于 `docs/rd-platform/verification/`；样本原件/密钥不提交源码库。

- [ ] HTTP 行为测试直接选用、改型、新研缺模板三条路线，依照当前来源条目计算比对结果。
- [ ] 测试重复点击、保存响应丢失、错输入版、拒绝候选、QA 阻断、取消后迟到回执及重启恢复。
- [ ] 在隔离测试项目中按用户液冷文件与六参数走 1—4，取得模板固定回执与真实原引擎输出。
- [ ] 对照 T0 检查原文、指标、环境章节、图表、字体、封面、Word 兼容与质量阻断。不得为完成测试手工伪造缺失客户阈值或正式签署。
- [ ] 分别记录本地业务流程验证、真实模型生成、文档结构检查、Word 2007 实机、正式工程决定；无法验证的项保留未执行。
- [ ] 汇总可发布范围、迁移影响与遗留问题；只有范围内检查通过才建议上线，不笼统写“所有测试通过”。
- [ ] 提交代码前依用户要求执行本地分支提交；本计划本身不授权合并/推送。

**实施时验收命令：**

`python -m pytest basic-service/app/tests/rd_platform -q`
`node --test web/src/features/rd/workflowLayout.test.mjs`
`npm --prefix web run build`
`node web/tests/rd-lifecycle-v2.browser.mjs`
`git diff --check`

旧任务书专项测试集按 T0 清单运行；仅在新改动或失败关联时追加测试，不用反复全量运行替代缺失的真实客户端验证。

## 执行顺序与审阅边界

```text
T0 → T1 → T2 → T3 → T4 → T5 → T6
            T1＋T4 → T7
全部完成 → T8
```

T0 的样本清单和当前代码盘点可独立进行；T3 的制度问题必须在实现相应正式决定前明确。T6 可在接口固定后并行实现，但不能为方便前端提前省略后端关口。每个任务结束后核对改动范围和测试，按获准范围形成小提交，避免将任务书引擎、权限、页面和迁移混成一笔难以复核的修改。
