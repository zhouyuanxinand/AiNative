# 语义 URL、网站图标与小航定位基础

## 目标与范围
本轮实现浏览器图标、全站研发页面的规范地址，以及小航可复用的页面引用契约。保留项目、流程和工作包的稳定 ID；不重写任务书生成、审批或权限逻辑。现有小航对话持久化继续使用；本轮不将浏览记录自动解释成长期业务事实，也不自动提交业务操作。

## 发现
- platformNavigation.ts 仍以查询串表达页面，useDirectoryState 将各目录全部默认值写入 URL，切页后旧参数继续残留。
- 小航已支持受控 target 导航、账号/项目/流程隔离的历史和版本标记，尚无统一页面引用。
- 主后端仅注册少数 SPA 页面；单端口 nginx 将页面请求送后端做 OA 回跳，不能改为绕过鉴权的静态兜底。
- favicon 被显式设置为空 data URL。

## 地址约定
| 页面 | 规范地址 |
| --- | --- |
| 我的工作、项目空间 | /work、/projects |
| 研发管理、客户画像、产品画像 | /research、/research/customers、/research/products |
| 流程管理 | /flows（各目录和固定版本保留有意义的子路径或少量查询参数） |
| 知识、运营、资源、设置 | /knowledge、/operations、/workspace、/settings |
| 项目 | /projects/:projectId |
| 流程工作面 | /projects/:projectId/flows/:caseId/:page |
| 工作面 page | overview、materials、requirements、selection、preparation、execution、delivery、reuse、decision、process、evidence、history |
| 保留独立入口 | /admin、/help/manual、/help/video、/logs、/review/:jobId |

仅当前目录的非默认筛选/分页写入地址；回到目录的筛选状态由已有状态与浏览器历史承接，不能靠污染所有页面 URL 保存。旧 /?rd_view=… 和 /rd/projects/… 继续解析并 replace 为规范地址。页面地址不包含凭证、用户名、文件正文或滚动偏移。

## 实施顺序
1. 扩展统一导航编解码器与目录状态适配：规范路径、旧链接迁移、当前页参数白名单、返回状态恢复；修正硬编码跳转链接。
2. 补后端 SPA 白名单入口，保留 nginx/OA 校验链；不存在的 API 不得落入 HTML。
3. 新增小航页面引用 v1：稳定 routeId、projectId/caseId、可选工作包 ID。导航必须通过既有前端 guard，后端收到的上下文须校验所属项目/流程且保留版本。提供可复用页面目录/解析函数和接入说明，不能允许模型任意执行 URL 或调用写操作。
4. 设计工程蓝底、白色连接结构的原创 SVG 图标，兼顾 16/32 像素辨识，提供 PNG/ICO 回退，所有 SPA 页面使用同一资产。
5. 定向验证及截图：导航纯函数/应用入口/后端 SPA 与助手上下文测试；浏览器旧地址迁移、刷新、前进后退、跨目录返回、工作面恢复和图标响应；检查真实本地项目只读页面。

## 重点验收
- 项目列表不能携带流程管理和研发管理的默认参数。
- 复制某流程工作面地址后刷新能定位同一对象，不能覆盖为另一项目的最近位置。
- 目录返回、未保存草稿、浏览器前进后退继续生效。
- 小航页面引用不含主机端口，重部署后仍可解析；引用不能替代鉴权或业务证据。
- 只运行上述受影响测试文件，失败先定点复现；不执行无筛选全量。
