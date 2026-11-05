# 项目删除角标验收

日期：2026-11-04，Asia/Shanghai。分支 `codex/rd-platform-rebuild-20261031`，未提交或推送。

项目卡片右上角与项目详情操作区增加同一删除图标，接入负责人权限、版本并发检查及幂等 DELETE 接口。项目普通列表、读取、下载、助手和流程使用目录不再暴露逻辑删除后的项目；原来源文件、成果、执行记录及删除事件保留。后台有提交中/运行中任务或有效租约时禁止删除。

确认框列明项目名、流程数量、来源和成果访问影响。确认成功后移除列表，删除当前项目时清理 URL 并返回项目空间。取消不写入；403 保留项目及错误；409 显式重读最新范围并再次确认；网络与网关 5xx 不确定结果保留旧版本/旧幂等键，关闭后核对列表，不把错误当成成功。

## 实际验证

- 新增 `basic-service/app/tests/rd_platform/test_project_deletion.py`：14 passed，先观测缺少删除方法、权限字段及 HTTP 405 的 RED，再实现。覆盖负责人/成员/外部主体、版本、三种活动执行阻塞、幂等、资源保留、访问隔离及创建回执不恢复已删除项目。
- 四个直接受影响完整文件 `test_http.py`、`test_project_profile.py`、`test_store.py`、`test_project_workflow_templates.py`：98 passed。没有修改旧断言/超时，没有无筛选全量测试。
- `web/tests/rd-project-deletion.browser.mjs`：9 组通过、8 次夹具 DELETE、真实 API 请求 0、pageErrors=[]。包括键盘与取消焦点、权限/运行限制、处理中遮罩/Escape、详情成功返回、403、409、同键网络重试、已提交后网关 503 的关闭核对、末页与 390px。503 新增用例先失败，定点修复后重跑该完整文件通过。
- 共用确认框新增可选 confirmDisabled，默认行为未改。直接依赖的 `rd-project-workflow-entry.browser.mjs` 8 组与 `rd-workflow-template-lifecycle.browser.mjs` 6 组通过，覆盖原创建和模板治理确认流程。
- 最终 TypeScript 与 Vite 构建通过，保留现有大包体积提示；相关 git diff 无空白错误。
- 本地主服务已重载，18370 健康检查 200、ok=true、ready_for_generation=true。真实数据库只读核对：11 个项目，deleted_at 非空项目 0 个；本轮未真实删除任何用户项目。

截图与回执在 `screenshots/2026-11-04-project-deletion/`。已复核桌面确认框及窄屏角标、按钮位置；截图全部为隔离夹具，不能当作真实项目删除结果。

本轮未在内网实际部署，未调用模型生成，也未对源文件做物理清理。实际删除由用户点击角标并确认后办理。
