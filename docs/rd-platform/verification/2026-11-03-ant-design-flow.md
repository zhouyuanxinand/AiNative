# 流程管理 Ant Design 界面验收

日期：2026-11-03。范围为流程目录、动作模板完整画布、流程模板生命周期界面；不改变权限、固定版本读取、业务数据或工作包执行逻辑。

## 本轮改造

- 流程页操作按钮与状态标记使用真实 Ant Design Button、Tag，沿用统一 PlatformTheme 颜色。
- 目录使用紧凑的白色工作面，移除资源卡片固定高度，保留完整标题、说明与操作入口。
- 流程模板目录和画布合成一个有边界的工作面，版本操作与历史记录使用紧凑工具行和浅灰分区标题。
- 动作模板保持完整只读画布，成员和输入输出按需展开；单动作仍显示一个实际节点，多步骤仍按固定版本展示。
- 流程与动作详情的桌面画布高度限制为 `clamp(360px,45vh,480px)`，缩短长页面首屏的空白画布，节点继续由既有适应逻辑完整展示。
- 1050px 以下目录和画布改为上下排列；390px 页面可纵向浏览，没有横向页面溢出。窄屏默认缩放显示全流程总览，阅读节点细节需要放大画布。

## 定点验证

没有全量重跑，也没有放宽等待时间或移除原有行为断言。两份隔离浏览器用例加载真实 PlatformTheme；Select 通过键盘展开实际 AntD combobox。

| 验证 | 结果 | 证据 |
| --- | --- | --- |
| `rd-action-template-detail.browser.mjs` | 5 组通过；固定版、重试、返回状态、搜索竞态、合法空图及非法图检查保留；0 写入、0 页面错误 | `screenshots/2026-11-03-antd-flow/action-detail/receipt.json` |
| `rd-workflow-template-lifecycle.browser.mjs` | 6 组通过；脏草稿取消、409 保留与重试、403 收回权限、旧版本刷新、历史对比及窄屏保留；无真实业务写入 | `screenshots/2026-11-03-antd-flow/failure-paths/receipt.json` |
| `rd-flow-canvas-direct.browser.mjs` | 8 组通过；真实 PlatformTheme 下直接新增/编辑/复制/删除/撤销、圆点连线、四边箭头、缩放与滚动拖动、Esc、禁用/只读、390px 及只读适应保持原断言；0 API 请求 | `screenshots/2026-11-03-antd-flow/direct-canvas/receipt.json` |
| `rd-flow-antdesign-visual.browser.mjs` | 实际本地 18370 页面只读检查通过；实际 1 节点/5 节点动作图、7 节点流程图全部处于画布边界内；1024px 与 390px 无横向溢出；0 写入、0 页面错误 | `screenshots/2026-11-03-antd-flow/actual/receipt.json` |
| 本轮文件 `git diff --check` | 通过；仅 Windows 行尾提醒 | 本地命令输出 |

实际页面检查拦截所有非 GET API。生命周期保存/冲突测试均为隔离接口夹具，不是企业电子审签或真实发布验收。本轮没有再次执行任务书生成。

直接画布首轮 7/8 通过：滚动偏移用例在缩放下一帧恢复视口中心之前设置测试滚动，偏移被随后回调覆盖。测试现等待缩放帧结束后再设置已有滚动，双向滚动、拖动距离和取消断言完整保留；复验 8/8 通过。未修改产品缩放逻辑。

## 实际页面截图

已逐张查看目录、单/多节点画布、流程模板、版本回溯和窄屏截图。目录截图等待“刷新项目”按钮恢复后采集，避免把项目读取占位作为稳定界面。画布高度与平台浮动助手缩小后已重采实际页面；此轮实际只读适应检查仍全部通过。

- `screenshots/2026-11-03-antd-flow/actual/01-action-directory.png`
- `screenshots/2026-11-03-antd-flow/actual/02-single-action-canvas.png`
- `screenshots/2026-11-03-antd-flow/actual/03-five-step-action-canvas.png`
- `screenshots/2026-11-03-antd-flow/actual/04-workflow-template-canvas.png`
- `screenshots/2026-11-03-antd-flow/actual/05-workflow-history.png`
- `screenshots/2026-11-03-antd-flow/actual/06-workflow-1024px.png`
- `screenshots/2026-11-03-antd-flow/actual/07-workflow-390px.png`
- `screenshots/2026-11-03-antd-flow/actual/08-resource-directory.png`
- `screenshots/2026-11-03-antd-flow/actual/09-report-directory.png`

限制：浏览器验收使用当前本机 Chromium，不等同于内网 Chrome 104 的实机验收。窄屏完整总览并不代表每个节点文字在总览比例下可直接阅读，可使用缩放和平移。
