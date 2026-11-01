# P0/P1 执行记录

计划：`docs/superpowers/plans/2026-11-01-rd-platform-phase1.md`，T0–T8。

用户已授权先提交现有改动，再执行本批开发；2026-11-01 补充决定：本地测试由项目负责人确认，明确标为非正式电子审签，正式部署另配企业制度。

- 基线提交：`31da6df4cbfd5114c14d5700e981a71fd7bb95b2`，分支 `codex/rd-platform-rebuild-20261031`。
- 提交前生产构建与 310 项后端检查通过；提交后工作区清洁。
- T0：完成来源、模板、Profile、mapping、规则和引擎摘要登记；15 项桥接测试、215 项原模板专项通过。Word 16 只读打开原件不等于 Word 2007 验收。
- T1–T4：已实现新案例 v2、历史 legacy_v1 兼容、固定需求确认、选型报告决定、独立研发启动、planning 内 taskbook V2 和范围批准。后续工程关口有明确命令，旧 advance_stage 不能绕过。
- T5：来源事实、冲突和有效性接线完成；同值来源换版须显式采用，历史引用保留，未知阶段不填默认值。定向与既有资料分析 28 项通过，相关选型/策划 22 项通过。
- T6：沿用蓝白工作台、共享弹窗、工作包画布与离开保护。浏览器覆盖重试保草稿、同键重试、负责人权限、QA 阻断、乱序提交、窄屏滚动、历史未核实状态及来源刷新。
- T7：32 项测试通过；仅交付离线副本预检/显式接受工具，没有执行真实数据迁移。
- T8：HTTP 首链、完整 RD 回归和真实液冷生成已执行。实机 Word 2007、完整工程内容符合、正式工程签署未验收；下面列明边界。

Ruling: 本地负责人确认通过服务端显式开关启用，OA 模式和未配置企业政策不能沿用本地确认 — 遵循用户制度决定 — 若环境误配，服务端额外拒绝。

Ruling: v2 禁止旧 advance_stage；后续专业关口使用明确的 confirm_engineering_stage 并复用原专业证据校验 — 防绕过且保留后续办理 — 所有业务推进仍由服务端判定。

Ruling: 迁移预检不把历史成果推导为批准，应用仅改离线副本并保留旧运行快照；活动 Run 不转移 — 避免双主账或重复生成 — 新政策办理需按领域命令形成真实引用。

## 最终验证

| 验证 | 结果及范围 |
|---|---|
| 完整 `basic-service/app/tests/rd_platform` | 345 passed，119.01 秒；两项既有依赖弃用提示 |
| 原任务书专项（T0） | 215 passed；模板、封面、表格字体、环境、Word XML 结构 |
| 前端生产构建 | TypeScript / Vite 通过；单包约 504 KB，保留体积提示 |
| 成果状态与画布单元测试 | 9 passed；含创建顺序不同于提交顺序的任务书选取 |
| `rd-lifecycle-v2.browser.mjs` | 隔离 API 夹具通过，1–4 流程及 9 张截图；没有伪装成实际模型或正式审批 |
| `rd-source-analysis.browser.mjs` | 只读参数、来源、采用、过期、同值刷新、无需求提案可采用通过 |
| `rd-flow-management.browser.mjs` | 四目录、画布/列表、缩放、可选节点、保存失败重试、窄屏通过 |
| `start.ps1` / Git | PowerShell AST 解析、diff --check 通过 |
| 原引擎保护 | 本批无 `pipeline_cli.py` / `jonhon_taskbook/` / 受控资源变更 |

审查关闭了五类实际缺陷：工程参考资料污染选型摘要；较早成果绕过在途任务书；同值资料换版无法刷新依据；新决定缺少 legacy 字段导致页面崩溃；历史待核记录显示假批准。前后端均按真实提交时间选择任务书版本。

## 真实液冷样本

真实调用链仍为 `executors.execute → engine_bridge.generate → src.pipeline_cli.run_pipeline`。使用两份用户旧 DOC、液冷管路 / 军品 / 改型 II / S / YLZJ / 非中央研究院参数，以及 smartvision `azure/gpt-5.4`（5505）。实际模板、Profile、mapping 摘要与 T0 一致。

- 实际生成复核 DOCX SHA-256：`222d3df72036a15610d509c24a68d9fb0bd22f159ccb61e989f0405dcc4c4cec`；Word 16 只读打开和 37 页 PDF 导出成功，不等于 Word 2007 验收。
- 业务停在 planning，工作包 blocked，delivery review_required；真实范围核对命令返回 422，版本未变，没有制造范围批准。
- 两份 DOC 转换仍需逐页核对；完成清单 276 项中 92 项未闭合。配置 QA 虽通过，完整来源检查开关为 false，因此不声称内容已全部满足或通过正式交付。
- 来源规范样例型号与 469 的适用性未确认，38 项比对如实保留 unknown；本地批准范围只允许隔离策划试运行。
- 本次 11 表/49 媒体，历史运行的 29 表/100 媒体涉及不同映射和历史参考内容处理，不以数量直接判断等价。完整内容符合仍待工程核对，后续本体 Agent 补齐与模板推导属于 P3。

运行文件不入源码库：`runtime/rd-phase1-real-validation/verification.md`、`verification.json`、`YLZJ_P1_real_generation_REVIEW_REQUIRED.docx`、`word16-preview.pdf`。浏览器截图位于 `runtime/rd-lifecycle-v2-browser/`；01、02、03、04 分别对应输入、需求确认、选型、任务书策划。

## 本地运行和后续范围

已在 `http://127.0.0.1:18370` 研发前端接入更新后 18372 后端，OA 关闭，显式设置 `JTB_RD_LOCAL_REVIEW=1`；目录回执含 taskbook V1/V2。正式服务默认不开本地确认；OA 模式额外禁止该确认政策。通用启动脚本支持 `start.ps1 -LocalReview`，仍受服务端 OA 与负责人资格校验。

实际业务旧数据未迁移。离线迁移候选不自动成为生产对象，也不授予历史工程批准。后续 P2–P5（专家团/目录授权、完整编排器、本体 Agent、K-box/Workspace 真接口及正式制度）仍按总计划另批实施。本批没有合并或推送远端。
