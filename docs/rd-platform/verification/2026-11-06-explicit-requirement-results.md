# 需求确认：实际结果显式采用验证

日期：2026-11-06

分支：`codex/rd-platform-rebuild-20261031`。本次未提交代码。

## 最终行为

- 未确认需求的实际结果只读显示 `--`，原始指标与来源定位保留。
- 生成规范建议不赋值；仅采纳当前有效建议后赋值。
- 不采纳、无匹配建议、仅保存澄清答复均不视为完成；必须办理并明确采用澄清。
- 新的直接手工实际值命令被拒绝。已有本地草稿可查看、复制或放弃，不被静默应用或删除。
- v2 需求确认覆盖全部需求，不能用原文非空绕过。跨行操作保留其他有效决定；同一行多次澄清采用仍保持正确关联。
- 既有固定基线保留并标记“已确认基线”；不回写历史确认或生成快照。

## 验证范围与结果

遵循先复现失败用例、再完整验证受影响文件的要求；未运行无筛选全量测试。

| 范围 | 结果 |
| --- | --- |
| 后端 `test_requirement_reviews.py`、`test_requirement_confirmation.py`、`test_requirement_spec_review.py`、`test_selection_activation.py`、`test_project_workflow_templates.py` | 合计 88 项通过；最后新增边界修复后仅重跑完整 reviews 文件（35 项），其余复用本轮已通过结果 |
| 前端 `requirementActualResult.test.mjs`、`requirementConfirmation.test.mjs` | 19 项通过 |
| `rd-requirement-decisions.browser.mjs` | 完整文件通过，含明确采用、拒绝、澄清、草稿、失败恢复、筛选、账号隔离及窄屏 |
| `rd-requirement-spec-review.browser.mjs` | 完整文件通过，含旧识别建议边界、生成不赋值、采纳、过期来源及移动端 |
| `rd-requirement-confirmation-recovery.browser.mjs` | 完整文件通过，含拒绝后空值、答复与采用分离、未保存编辑、返回、服务器拒绝恢复及移动端确认 |
| `npm run build` | TypeScript 与 Vite 构建通过；保留现有较大 bundle 警告 |
| `git diff --check` | 通过，仅存在既有 LF/CRLF 提示 |

复查发现并定点修复的边界：占位文字不能算实际结果；同一行第二次澄清采用不能丢失批次关联；历史澄清缺少来源哈希时仍需验证当前活动来源。最后活动来源收紧通过新增红到绿单元测试，未重复已经通过的全部浏览器文件。

## 本地页面检查

浏览器技能的本机运行模块缺失，使用已配置的独立 Playwright 与本机 Chrome 验证。

- 现有真实项目已有确认基线，64 条已固定结果均保留并标记。检查为只读，没有清除基线或伪造采纳。
- 同一批真实原文数据在浏览器 GET 响应中回放未确认状态：64 条实际结果均为 `--`，无直接填写框，确认按钮禁用，旧提取建议没有成为规范证据；此回放不写数据库。
- 原文 `B0112-R008` 定位入口保留。
- 桌面及 900px 窄屏截图已检查；无页面异常与业务写入，前后项目版本及案例数据完全相同。
- 后端已以原运行配置重启，PID 44256；健康、会话和目录接口均 200。本地前端仍在 `http://127.0.0.1:18370`。

截图及回执：`runtime/explicit-requirement-results/`，其中 `live-baseline-preserved.png` 为真实项目，`live-confirmation.png` 与 `live-confirmation-narrow.png` 为未确认状态回放；`live-receipt.json` 记录只读数据检查。交互回归回执位于 `runtime/explicit-requirement-results/decisions/`、`runtime/requirement-spec-review/ui/` 和 `runtime/requirement-confirmation-recovery/`。

## 尚未覆盖及审计说明

没有发起新的模型调用或重跑任务书生成，也未验证内网浏览器。该次调整范围是需求确认和澄清采用。

Premium 静态审计严格模式仍非通过：当前 25 条，旧报告 24 条。唯一新增差异是未被本次修改的 `projectCreateDialog.css` 的 scrollbar 检查（文件已有标准属性及 Chromium 回退）；属于旧报告差异，本次没有据此修改无关页面。其余结果与旧报告相同。不声明整个平台样式已通过此审计。
