# 研制任务书现有代码证据与整体方案接入边界

核验日期：2026-10-28。范围：当前本地 AiNative 工作区的静态代码；未运行生成任务、未变更产品代码。本文区分“现有实现”和“建议补充”，不把方案能力当作已交付功能。

## 1. 已有生成流程应继续作为受控能力使用

现有入口接受技术要求、产品规范、模板、产品配置及映射，以及产品系列、组织范围、研制阶段、指标适用条件澄清和可选回归基线。主要处理顺序为：

```text
固定输入及运行参数
  → 输入格式规范化与证据
  → 语义分类、适用性和 source_id / target_slot 路由
  → 确定性模板填充
  → 按路由 copy_exact 复制原文
  → 图片处理、后处理
  → 覆盖率、指标、版式与语义完整性检查
  → 生成件及检查证据
```

现有代码明确要求 LLM 仅返回原文块路由，不生成或改写正式正文。`copy_exact` 是语义正文插入的约束，不表示整份文档完全没有确定性生成、指标比较、版式处理等步骤。

证据：

- [pipeline_cli.py:268](<D:/桌面/研发管理平台-主包 1021/AiNative/basic-service/app/src/pipeline_cli.py:268>)：入口与边界；392 行输入规范化，476 行语义计划，544 行确定性填充，593 行精确复制，689 行后处理，764 行之后 QA。
- [semantic_orchestrator.py:1351](<D:/桌面/研发管理平台-主包 1021/AiNative/basic-service/app/src/service/jonhon_taskbook/semantic_orchestrator.py:1351>)：原文块路由提示、来源 ID 和目标槽位校验、`operation=copy_exact` 限制。
- [taskbook_runs.py:83](<D:/桌面/研发管理平台-主包 1021/AiNative/basic-service/app/src/service/rd_platform/taskbook_runs.py:83>)：研发工作单元从固定包取输入，调用原 `taskbook_controller._run_job`；原控制器继续负责生成逻辑。

因此，整体平台可以包装调用、责任、输入版本、补齐、审签和交接；无需另建一条由智能体自由写任务书正文的流程。将该能力纳入 Workspace 资源治理属于后续集成设计，不是当前已经完成的部署事实。

## 2. 【人工填写】必须先分类，不能直接等同于缺失属性

| 实际情形 | 代码依据 | 对补齐方案的约束 |
|---|---|---|
| 指标分类、适用性或比较结论需人工确认 | `fill.py` 3345 行附近和 3556 行之后：人工复核时采用值置为标记，保留候选比较与原因 | 展示规范版本、规格、条件和冲突；不自动用任一候选替代正式指标 |
| 模板说明、占位、斜体提示等待设计处理 | `postprocess.py` 810 行之后的标题树及标记处理 | 查真实正文或表格位置，不能只看到标题标记就推断一个本体字段 |
| 潜在失效分析、进度、预算、运行场景、QFD 等工程内容 | `postprocess.py` 48 行之后人工填写章节集合，`fill.py` 1436 行潜在失效分析说明 | 历史案例和知识提供参考，当前项目工程判断及责任决定仍由相应人员完成 |
| 缺少可用事实或证据 | 当前文档待填位置、来源核对和覆盖检查共同判断 | 可检索已有资料或治理知识；没有证据时维持待补，不生成“看似完整”的数值 |

来源：[fill.py:3345](<D:/桌面/研发管理平台-主包 1021/AiNative/basic-service/app/src/service/jonhon_taskbook/fill.py:3345>)、[postprocess.py:48](<D:/桌面/研发管理平台-主包 1021/AiNative/basic-service/app/src/service/jonhon_taskbook/postprocess.py:48>)、[postprocess.py:810](<D:/桌面/研发管理平台-主包 1021/AiNative/basic-service/app/src/service/jonhon_taskbook/postprocess.py:810>)。

后处理可能把同一子树中的多个待填标记提升到最小公共父标题；明确的表格单元格标记保持原位。因此，补齐对象应绑定当前修订及实际段落/单元格，不应采用“一个红色标题对应一个属性”的假设。

## 3. 生成后修订已经有可复用接口

| 已有接口 | 已有作用 |
|---|---|
| `GET /api/review/{jid}/document?revision_id=...` | 返回指定修订的正文投影、段落/表格定位和文件哈希 |
| `POST /api/review/{jid}/revisions` | 使用 `expected_revision_id` 和 `replace_text`、`insert_paragraph`、`delete_paragraph` 保存新 DOCX 修订；旧版已被替换时拒绝覆盖 |
| `POST /api/review/{jid}/revisions/upload` | 上传复杂编辑后的 DOCX，按预期父版本保存新修订 |
| `POST /api/review/{jid}/revisions/{revision_id}/check` | 针对该文件版本重新检查；研发集成场景仍要求独立工程审签 |
| `POST /api/review/{jid}/revisions/{revision_id}/annotations` | 保存某位置已核对/待核对及备注，不修改文档正文 |

证据：[review_controller.py:93](<D:/桌面/研发管理平台-主包 1021/AiNative/basic-service/app/src/controller/review_controller.py:93>)、[review_controller.py:146](<D:/桌面/研发管理平台-主包 1021/AiNative/basic-service/app/src/controller/review_controller.py:146>)、[review_document.py:375](<D:/桌面/研发管理平台-主包 1021/AiNative/basic-service/app/src/service/jonhon_taskbook/review_document.py:375>)、[review_store.py:276](<D:/桌面/研发管理平台-主包 1021/AiNative/basic-service/app/src/service/jonhon_taskbook/review_store.py:276>)、[review.ts:52](<D:/桌面/研发管理平台-主包 1021/AiNative/web/src/api/review.ts:52>)。

`check_review_revision` 对实际文件中的标记产生 `manual_fill` 问题，并附 `element_id`；报告绑定修订 ID 和 SHA-256，默认 `delivery_approved=False`。基础检查成功不等于工程通过。[review_checks.py:145](<D:/桌面/研发管理平台-主包 1021/AiNative/basic-service/app/src/service/jonhon_taskbook/review_checks.py:145>)

现有待核对列表由文字特征、人工标注和检查问题共同形成。某位置标为“已核对”会影响该列表显示，但并不删除 DOCX 中的标记、补入内容或替代机器检查。不能把“待核对数为零”作为任务书内容完整或已批准的证明。[TaskbookReviewPage.tsx:112](<D:/桌面/研发管理平台-主包 1021/AiNative/web/src/components/review/TaskbookReviewPage.tsx:112>)

当前原生任务书工作面已嵌入该核对页面，并提供所选正文锚点回调。后续补齐候选适合在同一工作面展开，避免复制出第二份正文或独立的任务书流程。[TaskbookDocumentPanel.tsx:33](<D:/桌面/研发管理平台-主包 1021/AiNative/web/src/components/rd/taskbook/TaskbookDocumentPanel.tsx:33>)

## 4. 新增本体证据还需要正式消费契约

当前十五类业务覆盖核验要求：修订 ID 与哈希相符，确认人及理由存在，依据必须属于固定输入包中的 `source_id@version`；“有依据”必须定位该修订实际正文或表格，标题和占位文字不能充数。此模块定位和记录证据，不负责改写正文。[taskbook_coverage.py:28](<D:/桌面/研发管理平台-主包 1021/AiNative/basic-service/app/src/service/rd_platform/taskbook_coverage.py:28>)

固定包里的 `reference` 资料可作为核验引用，但运行适配器明确跳过该角色，不把它直接交给原生成引擎注入正文。不能把“上传参考资料”解释为“现有算法自动采用本体值”。[taskbook_runs.py:108](<D:/桌面/研发管理平台-主包 1021/AiNative/basic-service/app/src/service/rd_platform/taskbook_runs.py:108>)

在已核验的任务书、修订和覆盖模块中，未发现本体补齐候选的专门接口。建议补充的内容包括：

- 候选绑定项目、任务、运行、当前修订、文件哈希及实际位置。
- 保存本体概念/属性/规则版本，以及治理知识版本、来源、值、单位、条件、适用范围和有效性；这些是待设计字段，不是当前 API 承诺。
- 人员可以采用、编辑、拒绝或发起澄清；采用记录与知识发布时间、文档修订、工程审签分别留证。
- 为生成后新增证据设计版本化证据集合及消费规则，再将它接入覆盖核验；不得原位改写已经固定的输入包或伪造旧包引用。
- 改变文件后重新定位锚点、核验覆盖及工程复核；旧版定位不能直接沿用到新版。

## 5. 两条不同的后续路径

**普通补齐优先走生成后修订。** 本体与治理知识给出有来源的候选 → 工程人员在当前任务书待办位置核对 → 使用现有修订 API 形成新 DOCX → 重新检查与核验 → 独立审签。该路径复用现有生成结果；完整落地还需上一节的新增证据契约。

**原输入变更才考虑重新生成。** 技术要求、规范、模板、采用范围等确需变更时，明确影响与新版本，建立新的固定输入包，再按现有引擎重跑。不得将每次本体补齐都强制转为重新生成，也不得把资料纠错静默写回旧包。

已有指标澄清是另一个窄接口：只补充规格和适用条件，禁止直接填入指标值；原生运行可在同一固定包下记录父运行及澄清答案并重新调用原流程。它不是通用正文补齐接口，也不意味着任意输入变化都允许复用旧包。[taskbook_controller.py:1838](<D:/桌面/研发管理平台-主包 1021/AiNative/basic-service/app/src/controller/taskbook_controller.py:1838>)、[taskbook_runs.py:40](<D:/桌面/研发管理平台-主包 1021/AiNative/basic-service/app/src/service/rd_platform/taskbook_runs.py:40>)

## 6. 放回整体方案中的位置

研制任务书是改型/新研启动后的一类工程工作包成果。研发管理平台负责它的责任人、输入采用、修订、工程决定及下游交接；本体规定语义和约束；K-box 提供合格的可复用知识与证据；Workspace 管理获准调用的能力及版本。这个用例能够验证四平台协作，但不能代替选型、设计、验证、变更、交付和知识复用的完整业务范围。

本次仅核验代码与编写研究笔记；以上接入建议尚未实施，也没有以本次静态核验代替端到端运行验收。

## 7. 当前集中承载三平台相关能力，后续经API下沉

2026-10-28用户进一步明确：当前任务书代码将其余三平台相关功能集中在一个应用，后续待平台提供API再解耦下沉。定向核读支持这一定位：当前代码已有相关基础能力，独立平台尚未接入不代表这些能力全部缺失。下表的目标归属是迁移方向，不是当前已经完成的部署关系。

| 现有代码证据 | 当前本地实现 | 后续职责及接入方向 |
|---|---|---|
| [requirement_classifier.py:64](<D:/桌面/研发管理平台-主包 1021/AiNative/basic-service/app/src/service/jonhon_taskbook/requirement_classifier.py:64>)、[rule_editor.py:482](<D:/桌面/研发管理平台-主包 1021/AiNative/basic-service/app/src/service/jonhon_taskbook/rule_editor.py:482>) | 类别定义、语义角色、来源分类与目标标题规则，以及规则校验、版本和历史 | 本体平台提供批准的语义、规则与映射固定版；规则执行仍可由获准能力承担 |
| [indicator_taxonomy.py:25](<D:/桌面/研发管理平台-主包 1021/AiNative/basic-service/app/src/service/jonhon_taskbook/indicator_taxonomy.py:25>)、[spec_applicability.py:328](<D:/桌面/研发管理平台-主包 1021/AiNative/basic-service/app/src/service/jonhon_taskbook/spec_applicability.py:328>) | 指标名称、别名、分类，按规格与条件筛选适用候选；词表不供给指标值 | 本体治理词义、条件关系和规则；研发记录当前项目的适用判断与采用 |
| [spec_extractor.py:660](<D:/桌面/研发管理平台-主包 1021/AiNative/basic-service/app/src/service/jonhon_taskbook/spec_extractor.py:660>) | 从当前规范抽取指标、原文、章节、表格、单位、条件与型号等结构化内容 | K-box管理可复用规范的治理与查询；抽取算法可封装为Workspace技能，由K-box治理Job调用。项目临时输入不因此自动发布为正式知识 |
| [failure_database.py:232](<D:/桌面/研发管理平台-主包 1021/AiNative/basic-service/app/src/service/jonhon_taskbook/failure_database.py:232>)、[failure_mode_matcher.py:171](<D:/桌面/研发管理平台-主包 1021/AiNative/basic-service/app/src/service/jonhon_taskbook/failure_mode_matcher.py:171>) | 失效知识记录、事件与快照；按产品与系列匹配，留来源行、记录版及接受/拒绝原因 | K-box供给治理后的知识和证据；本体给规则，Workspace可承载匹配执行。历史失效条目不直接等于当前项目FMEA |
| [requirement_classifier.py:789](<D:/桌面/研发管理平台-主包 1021/AiNative/basic-service/app/src/service/jonhon_taskbook/requirement_classifier.py:789>)、[semantic_orchestrator.py:1488](<D:/桌面/研发管理平台-主包 1021/AiNative/basic-service/app/src/service/jonhon_taskbook/semantic_orchestrator.py:1488>) | 需求分类、文档角色核对、作用域判断、章节与原文块路由，输出受约束计划 | Workspace管理分类和规划能力的固定版，经受控运行接口执行；保持禁止自由写正文的约束 |
| [llm_client.py:1470](<D:/桌面/研发管理平台-主包 1021/AiNative/basic-service/app/src/service/jonhon_taskbook/llm_client.py:1470>)、[semantic_retrieval.py:188](<D:/桌面/研发管理平台-主包 1021/AiNative/basic-service/app/src/service/jonhon_taskbook/semantic_retrieval.py:188>) | 模型请求、重试、JSON处理，以及可选embedding/rerank的模板槽位候选 | Workspace能力执行与模型网关支撑。这里检索的是当前模板槽位，不能作为企业知识库检索已完成的证据 |
| [semantic_schema.py:8](<D:/桌面/研发管理平台-主包 1021/AiNative/basic-service/app/src/service/jonhon_taskbook/semantic_schema.py:8>) | 已有SourceBlock、TemplateSlot、SemanticPolicy等结构，包含来源哈希、跨度与复制约束 | 作为跨平台契约的基础，接入远程来源时保留身份、位置与内容结构；不是完整企业本体治理平台 |
| [pipeline_cli.py:268](<D:/桌面/研发管理平台-主包 1021/AiNative/basic-service/app/src/pipeline_cli.py:268>)、[semantic_orchestrator.py:1747](<D:/桌面/研发管理平台-主包 1021/AiNative/basic-service/app/src/service/jonhon_taskbook/semantic_orchestrator.py:1747>) | 组织输入、分类规划、确定性填充、copy_exact、后处理和QA | 保留生成算法和研发业务编排，按职责替换合适的规则读取、知识查询及智能调用；整条pipeline不直接等同于Workspace |

未来API应与现有固定输入、来源块与内容哈希、规则与知识版本、运行状态和失败语义对齐。研发保留项目采用、文档修订、工程审签、计划发布和真实接收；共享定义、知识及能力的管理逐项归入所属平台。可以先用本地实现推进业务，按平台就绪程度接入，业务页面无需随物理部署拆分。

当前集中实现尚不代表三平台的跨应用治理、资源评测发布、授权撤回和运营体系已经完成。后续需要对齐实际API并验证固定案例的分类、路由、复制、媒体处理和QA等价性。本轮只修正架构说明，未改生成代码或新增远程调用。
