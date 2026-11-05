# Ant Design 平台统一改造验收

日期：2026-11-03；分支 `codex/rd-platform-rebuild-20261031`。本轮代码未提交。当前本地入口为 http://127.0.0.1:18370/ 。

## 实现结果

- 实际安装并锁定 `antd@5.29.3`、`@ant-design/icons@5.6.1`，React 18 共用 `PlatformTheme`。AntD Token 同时驱动原有领域组件；中文 locale、本地静态资源，不依赖 CDN。
- 深色 216px 导航、64px 顶栏、白色工作面、统一蓝色操作、14px 正文和 6/8px 圆角。首页、项目目录、研发/知识/运营/系统管理、资源工作台、管理员和操作资料页面共用这一体系。
- 通用业务按钮、共享选择器、反馈及确认弹窗使用真实 Button / Select / Modal；首页使用 Card，流程目录使用 Tag。特定业务画布、文件/日期控件和部分原生设置弹窗保留其行为，消费同一主题。未宣称每个 HTML 控件都已替换。
- 动作模板从卡片进入完整画布；流程模板目录、版本操作、画布与历史保持一体工作区。只读首次显示全部节点；桌面画布高度 360–480px，窄屏保留缩放和平移。单节点团队按真实固定执行图展示，不虚构多个专家。
- 管理筛选和拉取工作包的输入/按钮统一高度；窄屏纵向堆叠。新建项目 Modal 的 portal 表单全宽、可滚动；危险操作恢复红色语义。小航入口桌面缩至 72px，窄屏收至 48px。
- 本轮未调整生成引擎、审批、版本冻结、管理员权限、API 数据含义，也未触发新的任务书生成。

设计依据为 [Ant Design 数据展示](https://ant.design/docs/spec/data-display/) 与 [Ant Design 5 主题定制](https://5x.ant.design/docs/react/customize-theme/)。

## 验证范围

仅执行明确受影响的文件和界面，未运行无筛选全量。既有业务断言和超时保持。界面写操作使用隔离 API fixture；真实平台截图访问拦截非 GET API，没有新增项目或正式业务决定。

| 范围 | 实际结果 |
| --- | --- |
| TypeScript 与生产构建 | `npm run build` 通过，JS/CSS 编译目标 `chrome104` |
| 共享控件 | `antd-shared-controls.browser.mjs` 5 组通过：分组/禁用/键盘/未知值/FormData、Modal 焦点/嵌套/遮罩/拖出/忙碌、原生 dialog portal、390px |
| 既有反馈和弹窗关闭 | `feedback.browser.mjs`、`dialog-dismissal.browser.mjs` 通过，保留 CRUD、409、输入恢复、未保存及忙碌保护 |
| 最后集成复核 | `antd-integration-review.browser.mjs` 通过：新建表单全宽、390px 实际滚到底部、空白关闭与继续填写、危险按钮颜色；零真实写入/页面错误 |
| 动作详情和生命周期 | `rd-action-template-detail.browser.mjs` 5 组、`rd-workflow-template-lifecycle.browser.mjs` 6 组通过 |
| 直接画布 | `rd-flow-canvas-direct.browser.mjs` 8 组通过：增删改查、受保护节点、复制、撤销、缩放拖动、取消、连线、只读适应 |
| 实际流程页 | `rd-flow-antdesign-visual.browser.mjs` 通过：实际 1/5/7 节点图完整、1024/390px 无页面横向溢出，9 张截图，零写入/错误 |
| 平台壳与目录 | 隔离布局检查通过：管理工具同排 32px、折叠 64px、三列资源、只读与错误态；实际首页/研发/知识/运营/系统/资源 9 张截图，零写入/错误 |
| 任务书办理布局 | `rd-taskbook-layout.browser.mjs` 通过，实际组件 fixture：拉取下拉框与按钮同 y=158.97、高 32px；390px 等宽堆叠；记录内边距与长指纹无溢出 |
| 管理端与帮助 | `admin.browser.mjs`、`help-resources.browser.mjs` 各完整一次通过：导航、草稿、权限、资料管理、预览、滚动、窄屏与当前研发顶栏帮助入口 |
| 差异检查 | `git diff --check` 通过，仅 Windows 行尾提示 |

## 发现并修正

1. 新建项目弹窗改由 body portal 承载，原 `.rd-shell` 祖先限定失效。表单规则已扩展至 `.platform-feedback-modal`，桌面和390px实际量测通过。
2. `danger-text` 原危险链接样式被 AntD 接管后丢失。PlatformButton 显式映射为 danger，删除反馈和移除管理员的实际样式均为红色。
3. 任务书拉取按钮残留 42px 旧最小高度，而新 Select 为32px。首轮该文件对齐断言失败，定点改为32px后整个受影响文件通过。
4. 直接画布测试在设置缩放后立即滚动，与下一动画帧居中回调竞争。先等待缩放两帧完成，再执行原滚动/拖动断言，完整8组通过；未放宽超时或删断言。
5. 帮助测试尾部原来断言旧独立任务书首页控件；改为当前研发首页账号、工作台及顶部帮助入口的等价导航检查。保留宽屏溢出、API 隔离及滚动检查。

## 截图与分项记录

- 平台实际页面：`screenshots/2026-11-03-antd-platform/shell-actual/`（含 receipt.json）。
- 管理端及帮助：`screenshots/2026-11-03-antd-platform/admin/`、`help/`（隔离 API fixture）。
- 流程实际页面：`screenshots/2026-11-03-antd-flow/actual/`（含 receipt.json）。
- 共享控件、最终集成与任务书布局：`screenshots/2026-11-03-ant-design/shared-controls/`、`integration-review/`、`taskbook-layout/`。
- 分项报告：`2026-11-03-ant-design-shared-controls.md`、`2026-11-03-ant-design-flow.md`。

![研发管理筛选对齐](screenshots/2026-11-03-antd-platform/shell-actual/management-desktop.png)

![流程模板画布](screenshots/2026-11-03-antd-flow/actual/04-workflow-template-canvas.png)

## 限制与未覆盖项

- 浏览器运行使用本机 Chromium；`chrome104` 构建目标和 vh 回退不等于内网 Chrome 104 实机验收，也未据此宣称 Word 2007 兼容。
- 本轮没有重跑任务书内容生成、企业正式审签或所有后端测试；沿用先前相应验证结果，不把样式验收解释为生成门禁通过。
- 静态 premium 审计为 report 模式：原21条仍在，新增1条为 PlatformButton 的 spread props 转发无法被扫描识别。实际 htmlType/onClick/disabled 已由共享与管理浏览器测试验证。StyledSelect 的 AntD `<Select>` 也被不区分大小写的扫描误认作 native select。报告没有标记为静态全绿；历史管理/审阅原生控件等条目保留。
- 构建存在单 JS chunk 大于500KB提示（当前约1.04MB、gzip338KB），构建成功；未通过提高警告阈值掩盖提示。
