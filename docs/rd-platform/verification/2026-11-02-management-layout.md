# 管理筛选栏布局复核

本轮依据 `docs/superpowers/plans/2026-11-02-real-taskbook-flow-layout.md`，仅调整局部工具栏布局与标签，不改业务状态或生成逻辑。

## 根因及修复

- 研发管理与运营管理复用 `PlatformManagement`。原 `.rd-management-filter{margin:0}` 优先级低于 `.rd-shell .rd-field{margin-bottom:17px}`；Flex 底对齐计算包括外边距，造成搜索框与下拉实际顶部相差 19px（另有 2px 控件高度差）。修复前真实浏览器断言复现：搜索 y=244.78125、下拉 y=225.78125。
- 搜索增加真实可见标签，与筛选字段使用相同结构；工具栏作用域清除字段底距和 Select 自带上边距，两个控件统一 42px。未改变全站表单间距。
- 同类检查发现 Workspace 类型下拉继承 `width:100%`，使桌面目录筛选强制换行；局部改为搜索弹性宽、类型 160px，手机仍为上下等宽排列。
- 工作包拉取栏原按钮用固定上偏移 26px，不能跟随 Select 的实际几何；改为 Flex 底部对齐与相同 42px 高度。任务书绑定记录由专有类提供卡片内边距、正文间距和长指纹换行，不再套用仅面向 details/summary 子结构的无内边距展示。
- 流程目录搜索/刷新与项目目录工具栏的中心线本已一致，未为不同按钮等级修改其布局。

## 验证

`web/tests/rd-management-layout.browser.mjs` 访问实际本地服务，未模拟 API，未产生业务写请求：

- 桌面 1600×1000：研发与运营控件顶部均为 218.78125px、高度均 42px；标签顶部也对齐。
- 窄屏 390×520：控件各宽 326px，上下排列，页面无横向溢出。
- 下拉展开与触发器同宽/同左边界；清空搜索立即生效并回焦点；知识管理独立搜索仍显示。
- Workspace 桌面筛选同行，手机筛选等宽换行。
- 浏览器异常 0，业务写入 0。
- `rd-workspace-ux-polish.browser.mjs` 通过：标签、配置错误恢复、取消、失败保值与手机布局。
- `rd-taskbook-layout.browser.mjs` 通过：使用实际 TaskbookPreparation/WorkpackagePanel 组件及隔离显示数据，未发起任何业务命令；拉取栏 select/button 的顶部同为 157.46875px、高42px，绑定卡片文字距边框17px，390px下按钮等宽换行且长指纹无横溢出。此为组件布局夹具，不冒充真实生成步骤。
- `npm --prefix web run build` 通过（TypeScript + Vite，149 模块）；保留原有 JS 大于 500kB 的构建警告。
- 受改文件 `git diff --check` 通过。

截图及矩形回执：`screenshots/2026-11-02-taskbook-full-flow/layout/`，包含研发、运营、知识、Workspace 桌面/窄屏/下拉展开状态。已实际查看研发桌面、手机和 Workspace 桌面、手机截图。

这项验证为真实页面布局与只读交互复核，不代替根流程的生成验收。390px 矮窗口下原有可拖动小航浮窗仍会覆盖少量内容；普通点击与滚动仍能操作筛选，本次没有修改其独立拖动与展开行为。

## 真实阻断后追加：大量证据渐进展示

首次真实 Run 保存的109条待处理义务此前逐条默认输出JSON，导致工作包页面巨长。新 `WorkpackageEvidence` 默认仅显示原因和真实数量；完整台账展开后按记录显示标题、位置、原因和状态，每条原始对象仍可展开读取。没有删除或截断后台数据。

`CompletionEvidence` 默认预览3条待补项，其余名称完整保留在折叠列表。每轮核查仍保留所有接受/拒绝/查询证据，列表区域拥有可见滚动条和键盘焦点；展开不会把138条记录全部铺到整页。服务端返回 `local_checks` 时显示“本地核查”，旧记录缺少该键时不编造数值。

`rd-completion-evidence.browser.mjs` 用 `runtime/2026-11-02-real-flow/project-blocked.json` 回放：109条义务、109条剩余、138条轮次核查全部保留，最后一项原始对象深度相等；桌面摘要小于300px，展开/关闭与390×520键盘滚动通过，无浏览器错误、无业务写请求。这是已保存证据回放，不是第二次生成成功的证据。截图在 `layout/evidence-replay/`。

追加修改后 `rd-derivation-ux.browser.mjs`、`rd-taskbook-layout.browser.mjs` 和生产构建通过（150模块，保留原包体积警告）。组件布局夹具已将非真实枚举existing改为direct，截图重新生成。
