# 项目空间外层卡片验证

日期：2026-11-05。分支：`codex/rd-platform-rebuild-20261031`。

## 范围与原因

用户截图是项目空间列表。此前丰富的是进入项目后的流程卡片，外层仍沿用简行预览，因而没有呈现新增数据。按用户确认，外层改为项目总览，内层继续展示流程明细。

新增 `ProjectOverviewCard`，显示客户、产品、流程总数、已完成和需关注数量、项目负责人、最近更新时间及已有研发目标。统计遍历全部流程，复用内层当前状态口径；预览只展示前两条，保留查看全部、继续办理、查看项目、删除入口。缺失资料明确标注，时间使用服务端项目更新时间。

首轮视觉检查发现新卡片误用了旧 `.rd-project-overview` 类，旧双栏和定义列表样式造成卡片分栏、统计换行。已将外层独立为 `.rd-project-overview-card`，不影响旧样式消费者。

## 实际验证

- 完整运行 `web/tests/rd-project-case-cards.browser.mjs`，7 组检查通过。保留原内层断言和 15000ms 超时。
- 外层覆盖全部 4 个流程、1 个完成、1 个关注，含不在两条预览中的流程；未绑定历史失败不污染关注数。
- 覆盖空项目、缺失客户/产品/负责人/更新时间、搜索未预览流程、清空搜索、查看全部、标题与查看项目导航、继续办理、删除取消。
- 1440 和 390 宽度检查标题与资料纵向排列、三项统计同排、页面无横向溢出；查看保存的桌面、窄屏及原内层截图。
- 原内层进度、当前资料、执行引用、受阻原因、缺值及导航检查通过。
- 浏览器回执：页面错误 0，未预期请求 0，写请求 0；所有 API 使用隔离测试数据，真实 API 与模型请求均为 0。
- `web/node_modules/typescript/bin/tsc --noEmit` 通过；相关改动 `git diff --check` 通过。

## 证据

- [测试回执](../../../runtime/project-overview-cards/after/receipt.json)
- [桌面外层](../../../runtime/project-overview-cards/after/06-project-overview-1440.png)
- [窄屏外层](../../../runtime/project-overview-cards/after/07-project-overview-390.png)
- [窄屏缺值](../../../runtime/project-overview-cards/after/08-project-overview-missing-390.png)
- [样式修复前失败](../../../runtime/project-overview-cards/layout-before/failure.json)

## 未覆盖

未运行无筛选全量，未调用真实模型、创建或删除真实项目，也未重跑任务书生成。移动端现有小航浮层可能覆盖右下部分内容，未在本次卡片改动中调整。

测试准备时发现：把同输入修订但未绑定的失败工作包放入待办理案例，旧工作面选择可能进入编排页，而卡片模型已排除此历史执行。本次保留原导航测试数据，将历史执行放到隐藏预览的案例验证聚合口径；没有声称修复默认工作面选择差异。
