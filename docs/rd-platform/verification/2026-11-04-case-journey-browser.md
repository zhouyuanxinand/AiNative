# 连续办理导航浏览器验证（2026-11-04）

改造已在 `codex/rd-platform-rebuild-20261031` 工作树完成，本轮未提交 Git。先按开发计划明确导航，再实现和验证；任务书生成引擎、模板、模型调用参数与后端业务校验没有改动。

补充工程验证：`caseJourney.test.mjs` 完整文件 23/23 通过；最终 TypeScript `--noEmit` 与 Vite production build 均通过。构建保留已有大于 500 kB 的主包提示，本次不扩大到打包拆分。两次独立代码审查提出的概览误标当前步骤和禁用原因不可访问均已修复并由浏览器断言覆盖；无未解决的新增审查问题。没有运行无筛选全量或重复无关测试。

人工视觉复核包含初始成果概览、需求、比对、准备及完成成果；桌面步骤栏随滚动保持可见，编辑页助手放在标题操作区，手机两列步骤与单列内容正常。已同步 `DESIGN.md`、`UX-CONTRACT.md`，开发清单见 `docs/superpowers/plans/2026-11-04-case-journey-navigation.md`。

本轮三个定点浏览器文件均通过。所有业务 API 由 Playwright 路由夹具拦截；没有真实项目写入、真实模型请求或正式工程审签。没有执行无筛选全量测试。

| 文件 | 结果 | 主要覆盖 |
| --- | --- | --- |
| `web/tests/rd-case-journey.browser.mjs` | 通过，24 次隔离命令，2 次正常执行轮询 | 固定项目完整连续链、五种命令失败重试、草稿保持、步骤可用性、旧案例最小兼容分支 |
| `web/tests/rd-source-analysis.browser.mjs` | 完整文件通过，9 次隔离命令、6 次隔离分析 | 原有分析/采用/模型联动、幂等重试、资料版本与删除、文件卡片、助手草稿和窄屏断言 |
| `web/tests/rd-project-workflow-entry.browser.mjs` | 完整文件通过，11 组检查 | 发布目录刷新、创建历史版本保护、固定六节点流程、390px布局、任务书终态与目录错误恢复 |

连续链从已有隔离来源开始，通过真实页面操作完成：分析、确认采用、修订并保存需求、确认需求、分别登记产品和文档逐项比对、分别保存两项路线决定、生成固定选型报告、退回并重新批准、独立确认研发启动、固定任务书输入、拉取工作包、建立流程草稿、校验、准备候选、确认采用、明确提交。提交后的后台计算结果经正常项目轮询返回，页面持续停留在执行工作面，最后由用户打开成果概览。没有直接修改夹具为完成状态来代替用户提交。

采用、需求确认、选型决定、研发启动和输入绑定各包含首次 503 失败与保留原幂等键的重试。失败保留当前工作面和填写，普通需求/比对/路线保存不跳转，退回选型不启动研发，候选采用不自动提交。步骤按钮和页脚导航不发送业务命令。成果概览、项目流程和证据页不会冒用某个编辑步骤的 `aria-current`；编辑页唯一标记正在查看的步骤。

最终补充验证初始禁用的“需求确认”步骤：从“资料识别”按钮按 Tab 可聚焦原因容器，并显示完整 Tooltip；鼠标点击同一容器也显示原因。容器 accessible name 包含步骤名及原因，只有不可用步骤增加键盘焦点，内层按钮始终禁用，打开提示不切换工作面且 API 写请求总数保持零。首次点击测试发现 focus 与 click 双触发把提示立即关闭；生产侧改为 hover/focus 触发、点击显式聚焦后，该断言及连续文件完整复跑通过。此补充只运行 `rd-case-journey.browser.mjs`，复用已通过的资料分析和项目入口结果，未更改已有断言或超时。

来源和需求之间回看保留需求草稿，同一助手实例保留草稿。各保存完成后检查未保存标记消失，避免隐藏表单阻止自动轮询。固定项目之外另设独立旧案例起始夹具：保留七个步骤，采用输入仍留在准备页面，编排入口在阶段确认前禁用。此分支不替代前述连续链任何环节。

截图覆盖初始成果概览、资料、需求、比对与路线、编制准备、空工作包和完成后成果概览的 1440px、1920px、390px，以及禁用步骤原因、采用错误、选型批准待启动、编排候选、执行中和旧案例阶段关口。390px同时记录步骤区与滚动后的工作面。文档与应用滚动区域均无水平溢出，工作面只有一组主标题；已人工查看桌面、窄屏、长文件名、空态和成果截图。初始概览保留单一继续办理主按钮，没有原重复快捷入口和未开始阶段的空状态块。

本轮发现并复现固定项目研发启动后遗留 `decision` 未保存状态的问题：业务决定表单被移除时，清空输入的 effect 不再执行，导致自动轮询暂停。生产侧补充表单卸载时清理对应 dirty 状态后，新连续文件完整复跑通过。修复前证据保留为 `pre-fix-activation-dirty.json/png`。其余首轮失败属于导航选择器或新增夹具缺项，均只修正相关测试；原测试断言意图和超时保留。已通过项目入口文件没有重复执行。

证据：

- [连续链 receipt](screenshots/2026-11-04-case-journey/journey/receipt.json)
- [资料分析 receipt](screenshots/2026-11-04-case-journey/sources/receipt.json)
- [项目入口 receipt](screenshots/2026-11-04-case-journey/project-entry/receipt.json)
- [1440px初始成果概览](screenshots/2026-11-04-case-journey/journey/00-initial-overview-1440.png)
- [1920px初始成果概览](screenshots/2026-11-04-case-journey/journey/00-initial-overview-1920.png)
- [390px初始成果概览](screenshots/2026-11-04-case-journey/journey/00-initial-overview-390-workface.png)
- [禁用步骤原因提示](screenshots/2026-11-04-case-journey/journey/00-disabled-step-reason.png)
- [1920px成果概览](screenshots/2026-11-04-case-journey/journey/10-completed-outcome-1920.png)
- [390px需求工作面](screenshots/2026-11-04-case-journey/journey/03-requirements-390-workface.png)
- [390px编制准备](screenshots/2026-11-04-case-journey/journey/06-preparation-390-workface.png)

未覆盖真实模型生成、真实后端业务校验、正式电子审签、旧生命周期后续工程设计/交付/复用全链；这些未被隔离浏览器结果宣称验证通过。旧 `rd-lifecycle-v2.browser.mjs` 完整文件未运行，其早期工作包选择器与当前 FlowDesigner 不一致；本轮仅验证受导航改变影响的旧案例准备/阶段确认分支。
