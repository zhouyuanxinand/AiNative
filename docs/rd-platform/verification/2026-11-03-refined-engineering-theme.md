# 免费字体与专业工程工作台改造验收

2026-11-03；分支 `codex/rd-platform-rebuild-20261031`，未提交代码。本地查看：http://127.0.0.1:18370/ 。

## 页面改造

继续使用 Ant Design，主色换为矿物蓝 #236a83，导航石墨灰 #142632、工作背景 #eff3f6。低饱和选中底加细色边，替代大面积亮蓝；工作面以白色、细边线和轻阴影分层。标题24/20/16px、正文14px、说明12/13px，桌面32px页边距、24px面板内边距，窄屏保持12/16px。

统一首页、项目办理、研发/知识/运营/系统、资源工作台、流程目录与画布、管理员和操作资料页面。动作卡片区分名称/说明/入口/状态，模板目录与固定版本工作面分区更明确。保留当前业务操作、权限、版本、取消和未保存保护。

## 字体与离线部署

- 中文使用 **思源黑体 CN VF 2.005** 的本地衍生分片，内部名 **RD Sans**；可变字重250–900。技术数据使用 **IBM Plex Mono**，CSS别名 **RD Mono**，代码内中文回退至 RD Sans。
- 两者为 SIL Open Font License 1.1 开源字体，可按许可证免费使用及随软件分发。原版权、完整许可证、官方来源commit/hash、衍生改名说明均位于 `web/public/fonts/`。依据：[Adobe字体许可](https://github.com/adobe-fonts/source-han-sans/blob/master/LICENSE.txt)、[IBM字体许可](https://github.com/IBM/plex/blob/master/LICENSE.txt)。
- 思源29片完整保留原字体30,926映射码位，片间不重叠。UI优先片390,668字节；加两份Mono共31个WOFF2，总9,484,392字节，通过unicode-range按需加载。不是只保留当前界面出现的文字。
- 首页实测最初仅请求UI片与另一份标点片，共643,668字节；新增生僻字时再加载对应片。资源全在同源 `/fonts/`，无需客户端安装、CDN或外网字体服务。UIFont同源preload，所有字体font-display:swap。
- 实际浏览器CDP确认：首页标题、400/500/600字重和“镍铬钽铌、褚龚、℃、Ω”等样本由RD Sans实际渲染；编号由IBM Plex Mono实际渲染。不是仅凭CSS字体列表判断。阻断字体资源时仍有可见系统字体回退。

重建与静态复制核验：[离线字体报告](2026-11-03-offline-fonts.md)。字体构建工具只在独立临时环境使用，不加入业务运行依赖。

## 已验证范围

| 检查 | 结果与证据 |
| --- | --- |
| 实际字体、同源与失败回退 | 通过；`screenshots/2026-11-03-refined-theme/typography/receipt.json`，零外部字体请求、零业务写入、零页面错误 |
| 首页/研发/运营/知识/系统/资源 | 10张实际截图；32px筛选同高、标签对齐、清空聚焦、216/64px侧栏、390px无页面横向溢出；`screenshots/2026-11-03-refined-theme/shell/receipt.json` |
| 流程目录、固定版本和只读画布 | 9张实际截图，1/5/7节点完整、1024/390px无横向溢出、版本历史可访问；`screenshots/2026-11-03-refined-engineering/flow-actual/receipt.json` |
| 直接画布操作 | `rd-flow-canvas-direct.browser.mjs` 原8组完整一次通过，字体就绪后量测；原断言和超时保留，零API请求/页面错误 |
| 任务书办理布局 | `rd-taskbook-layout.browser.mjs` 通过：拉取下拉框与按钮均32px且同y166.19，390px等宽堆叠、记录内边距和长指纹无溢出 |
| 新建项目及危险操作 | `antd-integration-review.browser.mjs` 通过：桌面/390px输入全宽、窄屏可滚到底部、遮罩关闭、未保存恢复、危险按钮红色；零真实写入 |
| 管理员与帮助 | `admin.browser.mjs`、`help-resources.browser.mjs` 各完整一次通过；隔离API fixture验证导航、草稿、错误恢复、资料管理、长手册滚动及媒体读取 |
| 构建与差异 | 最终 `npm run build` 通过，1596模块；`git diff --check`通过。dist包含全部字体及许可证 |

遵循定点验证偏好，没有运行无筛选全量。字体变化后的截图量测发现并修复：模板筛选4px错位、原生管理链接仍38px、窄屏系统标题因旧flex规则居中。先复现和修改对应CSS，再复验完整受影响只读检查；未放宽断言/超时。调浅PrimaryBg只更新对应截图，没有重跑已通过的直接交互测试。

真实平台检查拦截API写请求。管理和帮助用例的上传/删除为隔离fixture；当前本地Workspace拥有合法编辑权限，截图保留该状态但未执行写入。未生成新任务书或写入正式业务决定。

## 截图

![首页](screenshots/2026-11-03-refined-theme/shell/home-desktop.png)

![动作模板目录](screenshots/2026-11-03-refined-engineering/flow-actual/01-action-directory.png)

![流程模板画布](screenshots/2026-11-03-refined-engineering/flow-actual/04-workflow-template-canvas.png)

![窄屏](screenshots/2026-11-03-refined-theme/shell/home-390.png)

分项说明：[平台壳](2026-11-03-refined-shell.md)、[流程工作台](2026-11-03-refined-flow.md)、[字体](2026-11-03-offline-fonts.md)。管理员、帮助及弹窗截图另存 `screenshots/2026-11-03-refined-theme/{admin,help,dialog}/`。

## 限制

本机Chromium的实际检查不代表内网Chrome104实机验收，构建仍保留chrome104目标与旧视口单位回退。本轮没有重跑任务书内容生成、Word兼容或全部后端测试。原有约1.04MB JS主包的分块提示仍在，未通过提高警告阈值隐藏；字体为独立静态资源按需加载。
