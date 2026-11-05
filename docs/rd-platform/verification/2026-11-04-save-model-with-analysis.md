# 选择模型后直接分析：验收记录

分支：codex/rd-platform-rebuild-20261031。

## 结果

移除独立“保存模型设置”按钮和先保存模型的阻断提示。选择模型后点击分析，项目页在同一操作锁内先保存改变的模型，再使用保存返回的项目版本分析。保存失败保留选择且不分析；分析失败后重试分析，保持原幂等键，不重复保存。未上传文件仍阻止分析，改变模型后不能采用旧结果。

模型名称、账号隔离的最近五项、桌面同行和窄屏换行行为保留。用户仅选择模型时不请求保存；点击分析才保存。

## 验证范围

- web/tests/rd-model-picker.browser.mjs：完整文件 10 组通过。保存与分析改由点击分析触发；保留厂商名称、默认值、最近五项、去重、账号/origin 隔离、目录失败和迟到身份响应检查。14 次夹具保存（含失败）、13 次夹具分析；1440px 控件均为 32px、底边差 0，390px 正常换行。
- web/tests/rd-source-analysis.browser.mjs：原资料分析/采用/分页/重试流程与新增 3 组全部通过；检查保存失败零分析、保存成功后使用新版本、分析失败只重试分析原键、连续点击锁、待上传文件和旧结果保护。6 次夹具命令、6 次夹具分析。
- TypeScript 检查和 Vite 生产构建通过；现有大于 500kB 的包体积提示仍存在。
- 两个浏览器文件均无页面异常或未预期 API 请求，未更改原超时。最初模型组件验证捕捉到旧独立保存按钮仍存在的失败，修改后通过。

只验证上述受影响文件与构建，未执行全量测试，未调用真实模型、修改真实项目或重跑任务书生成流程。生产后端和生成引擎未改动。未提交代码。

## 证据

- [模型及最近使用回执](screenshots/2026-11-04-save-model-with-analysis/model-picker/receipt.json)
- [完整页面回执](screenshots/2026-11-04-save-model-with-analysis/source-analysis/receipt.json)
- [桌面](screenshots/2026-11-04-save-model-with-analysis/source-analysis/model-change-save-and-analyze-success.png)
- [窄屏](screenshots/2026-11-04-save-model-with-analysis/source-analysis/model-change-save-and-analyze-narrow.png)
- [保存失败](screenshots/2026-11-04-save-model-with-analysis/source-analysis/model-save-failure.png)
