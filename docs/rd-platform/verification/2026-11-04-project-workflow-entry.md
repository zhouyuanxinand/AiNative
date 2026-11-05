# 项目流程模板入口与任务书终点验收

日期：2026-11-04（Asia/Shanghai）。分支：`codex/rd-platform-rebuild-20261031`。未提交或推送。

## 实际结果

用户使用的创建概念统一为“流程模板”。流程管理默认显示项目流程，新增真实已发布 `taskbook-generation` V1“研制任务书生成流程”，依次为资料受理、需求确认、成熟产品比对、选型决定、研发启动依据、研制任务书生成。新建项目和管理页启动入口消费同一受控发布目录，并提交固定 id/version/digest。项目冻结采用图；后续修订、停用及历史版本均沿用原治理机制。

新项目的任务书输入采用继续使用已选项目图，无需另选研发阶段模板。项目画布不再展示模板外八阶段或要求后续范围批准/方案设计/交付。原任务书专家团仍包含上下文、模板、补缺、生成、校验的完整执行链；只有当前输入、固定绑定、真实文档、实际执行和质量门禁全部满足，服务端才投影流程完成。生成受阻和历史成果不会伪装完成。旧完整研发案例保留原阶段逻辑。

同轮修正选型送审包的固定模板引用，防止新项目错误记录旧选型模板；禁止冒用固定业务动作、改资源版本或增加条件跳过节点。项目空间、首页和研发管理筛选按新流程真实终态显示。

## 验证范围

- 后端新完整文件 `test_project_workflow_templates.py`：24 passed，包含发布、拒绝草稿/停用/错误摘要、固定引用、终点、真实运行映射、旧版本继续办理、输入失效、禁止绕过、选型送审引用。新增复现均先红后绿。
- 已有直接受影响文件 13 个：179 passed。分别为 `test_workflow_templates.py`、`test_workflow_lifecycle.py`、`test_project_profile.py`、`test_store.py`、`test_workspace.py`、`test_designer.py`、`test_taskbook_planning_v2.py`、`test_first_scenario_v2.py`、`test_http.py`、`test_governance_http.py`、`test_workspace_http.py`、`test_catalog_plan_preview.py`、`test_selection_activation.py`。复用已通过结果，没有无筛选全量重跑。后端合计 203 项。
- 前端完整单元文件：`businessGraph.test.mjs` 6 passed、`projectWorkflowPresentation.test.mjs` 6 passed、`caseOutcomeModel.test.mjs` 5 passed。出现准备入口不匹配后定点修复并重跑完整受影响文件，保留断言。
- `rd-project-workflow-entry.browser.mjs`：8 组检查通过；真实发布目录/画布/启动弹窗只读，创建和异常路径完全拦截写请求。包括固定版本、390px 页面、准备阶段引用、生成终点、完成筛选、历史 V1 创建响应丢失、空目录与读取失败恢复。浏览器无 pageerror。
- `rd-workflow-template-lifecycle.browser.mjs`：6 组既有治理检查通过，原断言/超时保持，仅显式切换到原研发阶段类别并更新用途名称。
- TypeScript 与 Vite 正式构建通过；既有大包体积提示仍存在。相关 diff 无空白错误。
- 本地主服务已重载。`18370/api/health` 为 200，ready_for_generation=true；`/api/rd/session` 为 local_mode=true；真实目录返回已发布六节点模板 V1。

## 证据与未覆盖

截图位于 `screenshots/2026-11-04-project-workflow-entry/`，其中 01/02 为真实发布目录及创建入口，03/04/06 为明确隔离的浏览器项目夹具。`receipt.json` 记录完整 UI 检查清单；生命周期异常夹具证据在子目录 `lifecycle/`。夹具没有写入真实模板或项目库。

本轮没有重新调用模型生成文档、没有替换之前真实案例或声明其交付门禁已通过。原生成能力由执行链回归验证；新完整流程的真实模型生成仍待后续实际资料办理时验证。内网、Word 2007 本机打开以及正式企业审签不属于本轮覆盖范围。
