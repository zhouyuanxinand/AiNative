# 研发工作台壳与管理页面精修验收

2026-11-03；分支 `codex/rd-platform-rebuild-20261031`。本轮未提交。

修改范围为 `rdApplicationShell.css`、`RdAccountDock.css`、`platformHome.css`、`platformManagement.css`、`workspacePanel.css` 五份样式。统一石墨导航、细选中色边、矿物蓝操作、32px桌面页边距与24px面板、24/20/16标题层级、低对比表头及数据间距；继续消费根 PlatformTheme 和离线字体，不改业务逻辑。

## 实测

- `tsc --noEmit` 通过；五份文件 `git diff --check` 通过，仅行尾提示。
- `runtime/refined-shell-visual.mjs` 实际访问18370，等字体就绪后采集10张截图：home/management/operations/knowledge/system/workspace桌面，以及home/management/system/workspace390px。
- 研发与运营筛选标签同 y=202.09，搜索/下拉框同 y=228.09、height=32px。下拉键盘、清空后焦点恢复通过。
- 390px筛选全宽上下排列，页面没有横向溢出；216px导航/64px折叠验证通过。
- 管理端原生链接动作与AntD按钮均32px；手机系统标题与面板左边界对齐。
- 捕获0个API写请求、0个页面错误。当前本地Workspace实际拥有编辑权限，截图显示其合法编辑区，但没有写入资源或项目。

## 视觉复核发现

第一次查看系统390px截图，发现旧 `.rd-page-title` 的列布局与 `align-items:center` 组合导致单独的系统标题居中；已在900px以下改为stretch。另发现原生管理链接受旧高优先级按钮规则影响仍为38px，已修正作用域使其32px。分别定点修改后复验完整受影响只读脚本；原断言与超时未放宽。

最后根主题调浅PrimaryBg/InfoBg后，仅更新system/workspace的桌面和390px四张截图，没有重跑已通过断言。

证据目录：`screenshots/2026-11-03-refined-theme/shell/`，包括 `receipt.json`。本机Chromium截图不替代内网Chrome104实机；本轮没有运行全量测试或任务书生成。
