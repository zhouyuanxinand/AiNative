# P2/P3 独立规格与运行质量复核

复核日期：2026-11-01。基线：`5cd1180`；范围包含当前未提交及新增文件。依据：`docs/superpowers/plans/2026-11-01-rd-platform-phase2-phase3.md` 的 T1–T4，以及 alignment 第 5、7、8、9 节和 P2/P3 退出条件。

本次复核没有修改应用代码，没有提交。已有测试数量不作为规格完成的替代证据。审查过程中实现者仍在修改，以下记录首次发现的位置与复现，关闭状态须以末尾复测记录为准。

## 规格与实际行为发现

### R1 / P1：新版已有成果校验丢失固定上游执行器输入

- 位置：`basic-service/app/src/service/rd_platform/store.py`，`claim_node` 的 schema 3 分支（首次发现约 1262–1270 行）；`designer.py:491` 起的 `bind_inputs`。
- 复现：使用 `test_runtime.submitted` 和 `finish_taskbook_with_document` 完成一个固定上游；`pull_workpackage(quality_check)` 后执行 `designer_fixture.adopt_plan`，提交，再调用 `claim_node`。
- 实测输出：`schema=3`；`snapshot.upstream_results` 含 `generate/template_plan/content_completion/resolve_context/verify`；实际 `claim.previous_results` 仅 `__by_node__`，节点 `input_bindings={}`。
- 原因：schema 3 适配器先删除所有角色键，只从本包已完成节点恢复显式绑定。单节点 quality-team 的合法固定上游被清除，真实 `engine_bridge.verify:269` 必然报告缺少生成成果与回执。
- 要求：上游结果也必须固定到明确生产者，准备候选时锁定其身份及摘要，领取时按该生产者提供角色输入；不能回退为任意最后一个同名结果。
- 状态：已通知 P2 owner，修复中。

### R2 / P1：已发布采用的业务动作资源没有决定实际执行图

- 位置：`basic-service/app/src/service/rd_platform/designer.py:99–107`、`:155–162`；`workflow_templates.py` 的 `_validate_graph`/`adopt`。
- 复现：从 `taskbook-new-v1` 复制新修订，把业务节点 `taskbook.action_resource` 设为获准 `consistency-team@1`，保存、发布，`adopt_taskbook_flow` 采用该版，再拉取任务书包并创建默认草稿。
- 实测：`draft.business_template.graph` 固定 `consistency-team@1`，但 `draft.graph.nodes[0].resource_id` 仍是硬编码 `taskbook-authoring-team`。发布和采用均成功；不支持的动作替换也没有在发布时拒绝。新插入的动作节点同样没有执行消费方。
- 影响：P2 退出条件“编辑后实际采用的图与执行图一致”尚未达到；图中被采用的角色、依赖和动作可以变成仅展示的事实。
- 要求：按固定业务模板实例化动作及依赖，保持业务节点→动作实例→Skill 映射；无法执行的作用域在发布/采用时拒绝。不得在运行时重新取目录最新版。
- 状态：已通知 P2 owner，修复中。

### R3 / P1：加强审核门禁后，原 onboard 候选没有可用的证据生成路径

- 位置：`basic-service/app/src/controller/rd_derivation_controller.py:328–340`；`taskbook_controller.py:2371–2399`、`:2477–2486`。
- 原 `/api/templates/onboard` 仍创建普通 onboarding 候选，没有 `project_binding.json`。旧审核接口现在要求真实 `regression_evidence.json` 和 `visual_evidence.json`；唯一新的 regression 接口却强制读取该项目绑定文件，也没有旧候选绑定项目的命令。
- HTTP 实测：构造与旧 onboarding 同型的候选包（onboarding_report 加模板/Profile/mapping/catalog_patch，无 project_binding），调用 `/api/rd/template-derivations/legacycandidate/regression` 返回 `422 {"detail":"候选资产引用越界或缺失"}`，失败发生在任何真实回归之前。
- 影响：原候选不能通过应用界面/API 产生审核所需证据并发布。直接写服务器文件不构成兼容入口。T2 要求“原候选/版本功能兼容”未满足。
- 要求：增加受权、幂等、固定输入版的旧候选来源绑定/回归入口，或让原 onboarding 具备同等受控合同；保持新的真实证据门禁。
- 状态：已通知 root/P3 owner，待确认修复。

### R4 / P2：视觉复核入口按错误权限显示，分权账户无法完成治理

- 位置：`web/src/features/rd/TemplateDerivationPanel.tsx:40`（首次发现的 JSX）；服务端 `rd_derivation_controller.py` 的 `visual_review`。
- 初始实现把上传页面和“登记版式核验通过”放在 `can_prepare_templates` 分支，但 API 要求 `can_review_templates`。审核专用账户没有入口；准备专用账户看到按钮后收到 403。
- 状态：root 已修改为独立 `can_review_templates` 分支；本次已重新阅读代码确认分支对应，浏览器复测由集成人员记录。

### R5 / P2：派生候选与差异规则第六条之后无法从界面访问

- 位置：`web/src/features/rd/api.ts:104`、`:108`；`TemplateDerivationPanel.tsx:29`、`:38–40`。
- 初始 API helper 只取服务端默认第一页五条，组件又对这五条执行本地分页并忽略 `total`，导致后续候选和规则没有可达入口。
- 状态：root 已改为明确服务端 page/page_size=5、保留 total，并分别给候选/规则分页；本次已阅读更新代码确认，浏览器复测由集成人员记录。

### R6 / P2：业务画布不能选择或插入获准专家团动作

- 位置：`web/src/features/rd/BusinessWorkflowPanel.tsx` 中 `FlowGraphEditor business choices={[]}`；`FlowGraphEditor.tsx:20` 及新增节点/属性控件。
- 初始 business 分支隐藏固定资源选择器，新增节点没有 `action_resource`，属性也不能设置固定专家团版本。仅能新增空业务节点，无法实现 alignment §7.2 的“允许插入已授权动作模板实例”。
- 要求：在业务图中使用获准 team 目录形成固定 `action_resource`，与后端支持的工作包/业务作用域一致；不能把能力编辑混入共享 Workspace 内部图。
- 状态：已通知 root，待实现/复测。

## 质量与边界复核记录

### R7 / P2：专家团内部路线属性被接受后静默丢弃

- 位置：`basic-service/app/src/service/rd_platform/workspace.py` 的 `validate_team_graph`；`designer.py` 的 `expand`；`web/src/features/rd/TeamConfiguration.tsx` 复用的 `FlowGraphEditor`。
- 实测：复制 `consistency-team`，内部 consistency 节点加 `route='direct'`，保存、发布、授权均成功；`Designer.expand` 得到 `('consistency', None)`，原路线没有保留或求值。内部编辑器也提供有限路线选框。
- 影响：团队声称只在直接选用路线运行的步骤会在改型/新研照常执行，违反固定图和执行图一致性。
- 要求：内部能力图若尚不支持路线，应在保存/发布校验明确拒绝且隐藏该控件；业务动作图已支持的有限路线仍独立保留。不能接受后忽略具有执行含义的字段。
- 状态：已通知 P2 owner/root，修复待复核。

## 已检查的质量与边界

- 编译实现已有独立节点 ID、不可变候选、语义/布局摘要、采用记录和运行快照；团队展开采用同一 Worker。重复团队内部生产者绑定在编译时形成，不是按最后同名输出取值。R1 是其跨工作包输入遗漏。
- 检查了候选重验、显式根/依赖授权、发布状态与内容摘要、取消/预算 checkpoint、租约旧回调拒绝、来源 hash/位置/引用映射、目标资产完整 manifest、审核后变更检测、按产品/领域 CAS 发布与回退。
- P3 补缺当前为本地确定性来源匹配，不应描述成外部本体/K-box 已接入或模型自动专业判断。生产目标模板仍需要真实目标依据和原引擎回归；fixture 成功不代表专业高频模板可发布。
- 原任务书 `engine_bridge → src.pipeline_cli.run_pipeline` 保持；本复核没有进行模型生成、真实 Word 2007 客户端验证，也没有替代 T4 的真实 HTTP/浏览器全链证据。
- 复现命令使用既有虚拟环境 `D:/桌面/ai-zhonghang/zhonghang-service/agent-develop-task-doc-service/basic-service/.venv/Scripts/python.exe -X utf8 -`，临时 SQLite/资产位于系统临时目录，没有修改工作树数据。

## 接受结论

截至首次复核，不能声明完整 P2/P3 通过：R1/R2 是可复现的真实执行问题，R3 是原治理路径兼容缺口，R6 是明确未完成的业务画布范围。R4/R5 的代码修正已观察到，但不能据此把全部范围判为通过。待上述问题修复后按原复现和固定版正例回归，再更新此记录；原引擎样本与客户端/外部系统限制须继续单列。

## 修复后的独立复查（2026-11-01）

重新阅读实施计划、P2/P3/前端回执及实际实现，并独立执行以下定向验证；未修改应用代码、提交或重启服务。

| 初始发现 | 复查结论与直接证据 |
|---|---|
| R1 | 已关闭。候选固定上游工作包、Run、结果摘要及生产者；schema 3 按 `upstream:<step_id>` 从固定 `__by_node__` 取角色输入，重复角色不取最后值。`test_schema3_quality_claim_passes_fixed_receipts_into_real_verification` 将固定回执送入真实 verify 执行器并得到 delivery_approved；浏览器确认可显式选择固定上游生产者。 |
| R2 | 已关闭。默认动作图从已采用业务模板的 action_resource 与依赖实例化；保存/发布使用同一编译器，不能替换掉任务书完整合同或绑定尚无执行合同的后续阶段。固定专家团 V2 加 extra-check 的七步骤 Worker 测试通过，映射保留两个业务节点，撤销 V1 不会降级 V2。 |
| R3 | 已关闭兼容入口缺口。真实旧 onboarding HTTP 创建的候选可列出，经 bind-project 的 manifest CAS、固定输入修订与幂等绑定，再进入回归、视觉、审核、发布和回退。此 HTTP 正例的引擎是明确标注的合成 stub；另已阅读实际 OriginalPipelineRegressionRunner，确认调用原 run_pipeline、两份固定输入、六参数、目标 DOCX/Profile/mapping 及真实模型配置门禁，没有简化生成器或客户端布尔成功入口。 |
| R4/R5 | 已关闭。review-only 账户可上传视觉证据及独立审核；prepare-only 不显示审核入口。候选和规则各自服务端分页；七候选/七规则的第二页在真实 Chromium 中可达。 |
| R6 | 已关闭。业务画布读取获准团队目录，可选固定 action_resource；新增动作放在已支持审批关口前并保留原前置依赖，后续阶段禁止绑定。保存请求和工作包合同由浏览器测试核对，后端编译正例由 R2 覆盖。 |
| R7 | 已关闭。团队内部图服务端拒绝 route、错误动作版本及不匹配输入输出合同；前端 TeamConfiguration 隐藏路线控件。四个拒绝用例及浏览器断言通过。 |

独立执行结果：

- `pytest basic-service/app/tests/rd_platform/test_designer.py basic-service/app/tests/rd_platform/test_workflow_templates.py basic-service/app/tests/rd_platform/test_derivation_http.py -q`：**37 passed，21.95 秒，2 个既有弃用提示**。
- `node --test web/src/features/rd/businessGraph.test.mjs web/src/features/rd/flowDraftReducer.test.mjs`：**7/7 passed**。
- `node web/tests/rd-phase23-review.browser.mjs`：**passed**；隔离 API，七候选/七规则，包含业务动作保存、review-only 版式/审核、旧候选绑定/回归及固定上游绑定。没有把浏览器夹具声明成真实专业发布。

### R8 / P2：新增业务动作的办理状态没有投影实际执行事实

复查新增发现：`BusinessWorkflowFacts` 初始只为标准业务节点建立固定 facts 表。新增 `extra-check` 即使已有相同业务模板、当前输入的成功 Run 与 business_node_id 映射，仍必然显示“尚无当前办理证据”。服务端 `WorkflowTemplates.project_projection` 同样把此类动作投影为 pending，且任务书完成只检查任意历史完成包，未检查当前输入/模板。已通知 root；应按已采用业务模板版本和当前输入关联 Run/执行候选及步骤，避免把另一模板或旧输入运行算作当前证据。修复后的最终状态另附于下方。

证据边界：本轮没有重复全量 RD 测试，没有调用模型生成、企业高频模板专业验收、Word 2007 客户端或外部 Workspace/本体/K-box。全量测试和真实 HTTP/Worker 联调由对应实施/总验收回执负责；本报告对其仅阅读核对，不冒充本轮独立执行。

### R8 修复复测

已关闭。前后端现在按当前输入、固定执行候选及业务模板身份/版本/摘要关联实际 Run，并按 business_node_id 与执行映射聚合内部步骤；可显示完成、进行中、阻塞或取消，不再把其他模板/旧输入的成功误算为当前事实。服务端同时返回 node_execution_refs，后提交的替代 Run 可覆盖此前成功状态。

复查中另确认 selection 的 confirm_requirements 原可绑定 consistency-team，新增状态投影必须继续区分审批与技术成功：现已拒绝审批节点 action_resource，历史图仍优先按真实业务批准事实投影。实际审批命令未被绕过。

- 独立执行 `node --test web/src/features/rd/businessWorkflowFacts.test.mjs`：最终 **7/7 passed**；完成/运行/阻塞、固定模板版本和摘要、输入、候选、Run 不匹配及草稿创建顺序与实际提交顺序相反均覆盖。
- 独立再次执行扩展后的 `rd-phase23-review.browser.mjs`：**passed**；新增动作的完成/运行/阻塞、另一模板版本及旧输入五种页面状态全部覆盖。
- 独立执行修复后的 `pytest .../test_workflow_templates.py -q`：**7 passed，2.02 秒**；真实 Worker 映射完成、替代 Run 提交→运行→取消、旧模板/旧输入/错误候选排除、审批绑定拒绝及历史关口不被技术运行代签通过。

最终前端还明确禁止所有 gate 节点绑定动作，并按实际 submitted_at 选择最新匹配 Run；本次再次阅读代码并重跑上述七个状态测试和扩展浏览器，结果通过。

## 最终独立结论

R1–R8 均已修复并有上述定向复测。当前审查范围内**没有剩余的重大规格或运行质量发现**。此结论针对已实现的本地 P2/P3 能力和明确记录的证据，不代表外部系统接通、企业高频模板已取得专业发布资格、真实模型所有样本通过或 Word 2007 客户端验收完成；这些边界继续按总验收回执分别记录。
