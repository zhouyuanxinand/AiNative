# 批量资料与流程卡片验证

2026-11-04。本轮实施先写计划，范围为折叠建项参数、批量资料分类上传、系列识别/补充、项目流程卡片。原任务书引擎保持 tech/spec 各一份正式输入；同类其他文件保留为带原分类的 reference。

## 定点验证

| 验证范围 | 结果 |
| --- | --- |
| 后端初轮批量上传/分类、系列与四个受影响旧文件 | 142 passed |
| 复核后仅重跑 test_source_series.py + test_batch_sources.py 完整文件 | 56 passed（含新增边界；与初轮有重叠，不相加） |
| sourceUploadQueue.test.mjs | 11 passed |
| projectCaseCardModel.test.mjs | 10 passed |
| rd-batch-source-upload.browser.mjs | 完整5组 |
| rd-source-analysis.browser.mjs | 完整7组 |
| rd-project-case-cards.browser.mjs | 完整3组 |
| rd-series-confirmation.browser.mjs | 完整5组 |
| rd-project-workflow-entry.browser.mjs | 完整14组 |
| TypeScript | tsc --noEmit 通过 |
| 生产构建 | vite build 通过；仍有现有大于500kB chunk体积提示 |

后端初轮四个旧文件为 test_store、test_http、test_source_analysis、test_parameter_provenance，91项；其通过结果复用。最后复核仅复现新增失败，然后完整验证两个实际修改的文件。没有运行无筛选全量，也未改旧断言或放宽超时。项目创建浏览器第一轮14组交互已过，末尾因新增全局天气GET缺少夹具失败；补齐显式天气fixture后只重跑本文件14组通过。

## 交互与证据

- 新建默认折叠，F/非中央研究院正确提交；修改值参与幂等请求且未知结果锁定，桌面/390px无横溢出。
- 批量分类迟到响应不覆盖手动调整；拖动/下拉、主文件替换取消、422后保留、网络未知同key和version重试、长文件名窄屏布局通过。
- 系列从需求文件明确字段/文件名提取并保存不同证据；普通扫描名、日期版本名、占位词、项目文案与规范系列不能冒充需求系列。缺失时需求确认表单校验、失败保留、成功仅提交series、已有采用值隐藏编辑、离开保护通过。
- 卡片展示当前真实节点与执行，不把历史失败/成果混入当前；无记录明确缺值。继续、成果、流程、更多资料依据均可进入实际工作面。
- 浏览器全为隔离API夹具，不上传或修改用户真实项目、不调用真实模型。截图用于布局及交互核对，不代表任务书生成全链或正式交付验收。

## 本地服务

当前 127.0.0.1:18372 健康检查200，rd/session显示local_mode=true；运行中的OpenAPI已包含 sources/batch 与 sources/classify。前端18370可连接，Vite自动载入改动。检查时服务已由同工作树其他工作重载，未重复停止进程。

## 截图

- [展开建项选项](screenshots/2026-11-04-batch-sources-case-cards/creation/11-更多编制选项展开.png)
- [批量上传桌面](screenshots/2026-11-04-batch-sources-case-cards/upload/batch-desktop.png)
- [批量上传390px](screenshots/2026-11-04-batch-sources-case-cards/upload/batch-mobile.png)
- [项目流程卡片](screenshots/2026-11-04-batch-sources-case-cards/cards/01-case-cards-1440.png)
- [系列确认回执](screenshots/2026-11-04-batch-sources-case-cards/series/receipt.json)

尚未覆盖：真实模型文件名分类服务、真实DOC/DOCX全链生成、内网/Chrome104和Word2007。卡片浏览器指出全局小航在390px仍可能遮住右下内容，角色可拖动或贴边收起；本轮未改并行维护的助手布局。未提交 Git。
