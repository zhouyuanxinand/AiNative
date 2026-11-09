# 需求确认：按规范生成建议验证

## 实现范围

- 在需求确认表提供“按规范生成建议／重新核对规范”。使用当前编制模型，对已采用的需求逐项检索主产品规范，覆盖全部需求。
- 建议分为找到依据、指标差异、适用性待核对、未找到对应指标；引用保存来源文件版本、哈希和定位信息，沿用文档定位预览。
- 建议生成不改写原需求或实际结果。逐条采纳、不采纳、人工修订或澄清沿用现有审核流程。不同指标、单位或工况不能直接采纳为客户要求。
- 保存独立批次和历史，检查权限、来源变更、需求版本、并发和幂等回执；失败保留旧结果。已处理行及已采用澄清不会因处理下一行而失效。
- 本体 Agent、K-box、客户／产品画像在建议模块保留 TODO 接口扩展说明，本次未接入。原任务书模板装配、正文生成及质量门禁未修改。

## 定向验证

| 范围 | 结果 |
| --- | --- |
| `test_requirement_spec_recommendations.py` | 22 passed；逐项覆盖、引用真实性、完整多句、标题与下一行指标、差异、模型失败 |
| `test_requirement_spec_review.py` | 11 passed；独立批次、权限／并发、失败保留、逐行决定、澄清及过期处理 |
| `test_requirement_reviews.py`、`test_requirement_confirmation.py` | 19 passed；原有决定与确认门禁回归 |
| `test_evidence_locations.py` | 34 passed；含当前、历史批次和已审阅快照各自的 DOC 转换坐标 |
| `rd-requirement-decisions.browser.mjs` | passed；旧建议及决定交互兼容 |
| `rd-requirement-spec-review.browser.mjs` | passed；9 组交互检查，390px 窄屏无页面横向溢出 |
| 前端生产构建 | passed；保留原有较大 bundle 提示 |
| 最后一次前端调整后的 TypeScript 检查 | `npx tsc --noEmit` passed |
| Git 空白检查 | `git diff --check` passed；已有 LF/CRLF 提示 |

合计 86 项定向 Python 测试、2 个浏览器测试文件。未执行无筛选全量，未放宽断言或超时。

浏览器专项验证采用隔离接口数据，真实项目写入为 0。验证生成不改实际结果、草稿保护、失败与重试、批次绑定的采纳／不采纳、澄清跳转、已采用澄清状态、相同资料重新分析后保留有效决定、过期和只读限制。检查桌面及窄屏截图。记录在 `runtime/requirement-spec-review/ui/receipt.json`，截图同目录。此浏览器记录不是用户真实项目完成审批的证明。

## 真实液冷资料验证

- 从当前用户项目读取快照，包含 61 条已采用需求；主规范为“液冷产品规范案例（JONHON受控）.doc”，需求来自 YLZJ-BG-469 规格书。
- 使用 `azure/gpt-5.4` 真实调用 5 批，合计 116.84 秒。发现 DOC 转换文本中“指标标题一段、指标值下一段”的完整引用被误判为截断，定点修复该校验。
- 修复后复用本次保存的真实模型响应重跑引用和建议校验，没有重复调用模型。最终 6 条可采纳、1 条明确差异、41 条待核对、13 条未找到；48 条有规范原文证据。
- 对 6 条可采纳建议逐项检查，原指标值均保留。所有建议仍需使用者核对适用条件，不自动确认或审签。
- 原项目数据、已采用需求和源文件哈希均保持不变；未将测试建议写入用户项目。
- 结果及响应位于 `runtime/requirement-spec-review/revalidated-result.json`、`proposal-revalidated.json`、`accepted-value-spotcheck.json` 和 `batch-*-response.json`。初次校验结果不是修复后的结果，以 revalidated 文件为准。

## 本地服务与限制

- 本地后端已保留原配置重启，18372 的健康、会话、目录接口返回 200；18370 的项目页面返回 200。服务复核记录位于 `runtime/requirement-spec-review/service.json`。
- 用户刷新研发平台，在“需求确认”点击“按规范生成建议”即可对当前数据执行正式建议批次。
- 本轮没有生成正式任务书、没有执行正式审签，没有验证内网 Linux 实机或未接入的本体／画像服务。没有提交代码。
