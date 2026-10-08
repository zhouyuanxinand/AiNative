# 模板目录：动态更换模板

进入平台顶部的“模板目录”，按产品类型、质量管理体系或文件名查找现有模板。

1. 点击对应模板的“更换模板”。
2. 选择 DOCX 或 DOC 文件，可填写版本名称和更新说明。
3. 点击“上传并校验”，查看章节变化、指标表校验结果；可下载新模板核对。
4. 校验通过后点击“启用此版本”。之后提交的新任务会使用新版本，无需重启服务。

每次更换只作用于所选产品和质量管理体系。首次启用时自动保存原模板；“版本记录”支持下载历史模板和“恢复此版本”。已生成的文件不会改写，正在生成的任务保留其已选模板。

DOC 会在服务端转换为 DOCX，目录保留上传文件的原名，下载文件为 DOCX。服务端需要已配置的 Word 或 LibreOffice 转换环境；本机已验证 Word 转换。

校验检查当前规则所需章节能否唯一定位，以及指标表的列数、列顺序和填写行。缺失章节、重复目标章节或不兼容指标表会阻止启用，并显示具体原因。大幅调整章节结构时，需要同步调整产品的章节映射规则。校验不会自动改变业务规则，也不能代替对模板正文和版式的核对。

如果其他用户先更新了当前模板，系统会提示版本已变化；刷新版本信息后重新上传校验，避免覆盖他人的更新。

新增产品类型仍使用页面底部折叠的“新增产品模板与候选审批”，现有产品日常换模板使用上方入口。

## 存储与接口

相对 `basic-service/app`：

- 当前绑定：`src/service/config/template_catalog.yaml`。
- 启用的不可变模板：`src/service/jonhon_taskbook/resources/templates/versions/`。
- 上传原件、转换结果、版本记录及操作记录：`runtime/template_releases/template_versions/`（以运行配置为准）。

备份和迁移平台时应一并保存上述目录和配置。

| 接口 | 用途 |
| --- | --- |
| `GET /api/templates` | 目录及当前版本 |
| `POST /api/templates/versions` | 上传并校验，尚不启用 |
| `GET /api/templates/{product}/{domain}/versions` | 版本记录 |
| `POST /api/templates/versions/{id}/activate` | 启用或恢复指定版本，需要当前 `expected_revision` |
| `GET /api/templates/{product}/{domain}/download` | 下载当前模板 |
| `GET /api/templates/versions/{id}/download` | 下载指定版本 |
