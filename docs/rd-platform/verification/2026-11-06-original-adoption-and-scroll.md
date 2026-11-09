# 规范结果与表格操作位置验证

## 完成行为

- 已找到规范依据：自动显示有效规范建议指标，保留“办理澄清”；在最终统一确认时写入需求修订与基线，不伪造逐项采纳记录。
- 适用性待核对：提供采纳、不采纳与办理澄清。采纳从当前已采用资料分析读取原始指标，不采用模型建议替代值；不采纳后实际结果保持未确定。
- 采纳和不采纳成功后停留原行；失败也不跳到顶部，显示就地错误提示。保存期间禁用行操作，保持按钮布局。
- 明确打开澄清后可“返回对应需求”，返回时保留未保存的澄清草稿。
- 历史流程和新版流程的前后端确认规则同步，旧拒绝记录不能被规范自动结果覆盖。

## 根因与定位

1. CaseWorkspace 的通用错误处理会对顶部错误栏执行 scrollIntoView。长表中部操作失败时，行纵坐标由 390.55 变为 2951.34，滚动位置由 2546 变为 92。
2. 不采纳提交成功的回调会主动打开页底澄清表单。
3. 请求期间移除全部“办理澄清”按钮，导致行布局改变。

现在单行决定错误使用不改变阅读位置的消息提示，不采纳成功不再自动导航；请求期间保持按钮挂载并禁用。

## 验证范围

仅验证受影响文件，没有执行无筛选全量测试。

- 前端实际结果测试：13 项通过。
- 前端确认门禁测试：最新完整文件 15 项通过；包含历史流程对齐修复，先定点验证 4 项。
- 后端：test_requirement_spec_review.py（41）、test_requirement_confirmation.py（9）、test_requirement_reviews.py（37）、test_case_records.py（29），共 116 个不同用例通过。前两份复用此前完整结果，历史流程修改后复验后两份。
- 浏览器：rd-requirement-spec-review.browser.mjs、rd-requirement-inline-edit.browser.mjs、rd-requirement-decision-scroll.browser.mjs 全部通过。
- 40 行长表验证中部、底部的成功、503 失败、重试、项目流程切换返回、澄清返回与草稿保留；目标行相对视口的偏移小于 0.22px。
- 前端生产构建通过；现有单包体积超过 500 kB 的提示仍存在。受影响文件 diff --check 通过。

浏览器使用真实前端与隔离接口数据，没有修改真实项目，没有调用真实模型，也未重新生成 DOCX。本次验证不代表内网浏览器或模型服务实测。

## 浏览器证据

- [表格操作位置记录](../../../artifacts/requirement-decision-scroll/receipt.json)
- [表格操作后截图](../../../artifacts/requirement-decision-scroll/after-row-decisions.png)
- [规范操作记录](../../../artifacts/original-adoption-spec/receipt.json)
- [规范结果截图](../../../artifacts/original-adoption-spec/01-generated-proposals.png)
- [行内编辑截图](../../../artifacts/original-adoption-inline/requirement-inline-edit-desktop.png)
