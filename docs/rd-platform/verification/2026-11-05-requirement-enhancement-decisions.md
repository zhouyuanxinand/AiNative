# 2026-11-05 需求增强与逐项确认验证

## 提交与实施顺序

- 分支：`codex/rd-platform-rebuild-20261031`。
- 按用户要求先将既有代码提交至本地：`06268f6`（feat: integrate R&D project workflows and requirement review workspace），未推送远端。
- 随后编写 [本轮开发计划](../../superpowers/plans/2026-11-05-requirement-enhancement-decisions.md)，再实施本轮修改。本轮修改尚未提交。

## 已实现

1. 第一步保留原文指标，分别展示自有组件指标占位、有引用依据的 AI 推荐、来源与澄清状态；全部需求可纵向浏览，并支持全屏核对、搜索和原位返回。勾选建议不会立即写入，采用识别结果时只写入明确选择的行。
2. 第二步“需求确认”采用六列表：类别／指标、原始指标、AI 推荐、AI 来源、操作、实际结果。逐项采纳、不采纳及人工结果分别记录；拒绝建议、填写“不适用”需说明原因。原文不随决定修改。
3. 草稿按账号、角色、项目、业务流程与需求隔离，关联分析、来源版本和需求修订。失败可重试，刷新可恢复；过期草稿不会覆盖新版本。确认后只读。
4. 未处理的有效建议、占位结果及已登记但未闭合的必需澄清，不能通过需求确认。包括“待澄清。”、“待确认（客户未反馈）”等占位写法。

## 实际验证范围

后端仅验证受影响文件，按失败用例定位修复后复核对应完整文件；复用已通过结果，未执行无筛选全量测试：

| 文件 | 结果 |
| --- | --- |
| test_requirement_enhancements.py | 12 通过 |
| test_source_analysis.py | 22 通过 |
| test_analysis_selection.py | 2 通过 |
| test_requirement_reviews.py | 10 通过 |
| test_case_records.py | 29 通过 |
| test_requirement_confirmation.py | 9 通过 |

浏览器验证：
- `rd-source-analysis.browser.mjs` 通过：全量浏览、全屏返回、来源核对、按行选择、模型保存与分析失败重试、资料删除及窄屏布局。
- `rd-requirement-decisions.browser.mjs` 通过：采纳／拒绝／人工结果、不适用原因、保存失败、刷新恢复、账号隔离、过期草稿、确认后只读和窄屏布局。
- `rd-navigation-history.browser.mjs` 通过：页面导航与返回。
- 上述浏览器业务验证使用隔离接口数据，不修改用户现有项目，不代表真实模型服务端到端验收。
- 另运行的旧 `rd-case-journey.browser.mjs` 停在第 200 行：断言期待 4 项资料分析参数，当前为 2 项。基线 `06268f6` 已为 2 项（其余参数已迁至新建项目）；保留原断言，未以放宽断言或超时掩盖失败。

构建与运行：
- `npm run build` 通过（TypeScript 与 Vite）；仍有大于 500 KB 的 bundle 提示。
- `git diff --check` 通过。
- 已仅重启本工作树后端，沿用原运行环境；`/api/rd/session`、`/api/rd/catalog` 返回 200，前端代理请求返回 200。
- 本地入口：<http://127.0.0.1:18370>。

## 证据与边界

- 第一阶段浏览器记录：`runtime/requirement-enhancement/receipt.json`；截图见同目录。
- 第二阶段截图：`runtime/requirement-decisions/screenshots/requirement-decisions.png`。
- 重启回执：`runtime/requirement-enhancement/service.json`。
- 本轮未调用真实模型生成新任务书，未重复 Word 2007 或原任务书生成引擎回归。
- 自有组件指标仍等待本体／K-box 真实数据，不填充虚构能力值。无有效依据的推荐会被舍弃并形成处理提示；尚无“每一项无效推荐自动生成客户澄清任务”的实现。
