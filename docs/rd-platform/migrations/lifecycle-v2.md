# 生命周期 v2 离线预检与历史续办

适用范围：P1/T7。模块 `basic-service/app/src/service/rd_platform/migration.py` 只处理已取得的项目副本及其文件引用；没有数据库连接、HTTP 写入口、自动迁移启动钩子或调度功能。预检通过、接受离线结果、允许写入实际数据是三个不同事项。本批只交付前两项能力，没有迁移真实项目。

## 本批裁定

- 无政策字段的旧记录按 `legacy_v1` 解释。只读预检不回填任何字段。
- 显式接受后只在返回的新副本中采用 `business_lifecycle.policy_version=v2`，增加缺失的空业务记录数组、项目版本和迁移回执。调用方传入的对象保持不变。
- 原 Case ID、stage、状态、来源、需求、决定、工作包、节点、Run ID、快照、模板、模型、成果和权限不改。采用 v2 不把旧 `design` 批量改为 `planning`。
- 全部历史采用结果从 `historical_unverified` 开始，当前批准/启动引用为空，不分配研发编号；迁移接受操作人没有因此获得工程资格。
- 缺少公认 legacy 启动契约时，不从旧 `stage.approved`、研发编号文字、生成文件或任意 `authorization` 字段推断有效启动。已有 `rd_activations` 及其需求基线、选型决定、报告包完整引用链可列为 `candidate_requires_policy_review`，仍须按目标政策复核。原记录及其编号、`review_mode`、`electronic_signature` 原样保留；旧 lifecycle 全值另保存在回执 `source_lifecycles` 中。
- 预检不授予本地演练开关。目标投影为 `formal_review` / `enterprise-review-unconfigured` / `local_review_enabled=false`；实际办理时仍由服务端已配置政策决定是否允许具名本地确认。`local_review` 记录不能升级为企业电子审签。
- 未执行 v1 任务书草稿仅返回 v2 新计划候选，必须另走新业务办理和采用命令。迁移模块不复制工作包、不重放生成、不分配新 Run。

## 输入与只读预检

使用内部导出的项目完整副本。文件应先复制到隔离目录并核对原始摘要，再将副本中的路径指向复制件；路径变化也属于预检输入。不要使用去掉文件路径的公开 API 投影代替内部导出；无法定位原件时会产生 `path_missing` 阻断。

```python
from service.rd_platform import migration

# detached_project 已从独立副本读取；此示例没有数据库写入。
preview = migration.inspect(detached_project, case_ids=["case-to-review"])
```

省略 `case_ids` 表示全部案例。报告包含：

| 字段 | 含义 |
|---|---|
| `source_version` / `source_digest` | 原项目版本及完整 JSON 摘要，覆盖输入、权限和旧快照 |
| `case_mappings` | 原政策/阶段、拟采用生命周期、原 ID、动作/资源/模板固定版本及快照摘要 |
| `unknown_facts` / `activation_evidence` | 启动依据缺失、不完整或需要政策复核的既有证据 |
| `draft_candidates` | 从未执行草稿的候选定义与所需办理步骤；不是已采用计划 |
| `active_runs` | 所选案例仍提交中/运行中的工作包、Run ID 和原项目 Owner |
| `files` | 文件路径、预期/实际 SHA-256、引用位置及验证结果 |
| `counts` | Case、工作包、Run、成果、来源、需求、澄清、决定和新业务记录总量 |
| `blockers` / `convertible` | 是否存在不能接受的差异 |
| `digest` | 包含以上内容的固定预检摘要，不包含当前时间或随机数 |

文件按 `(path, expected_sha256)` 去重计数；同一文件在来源和旧快照中的多处引用保留在 `references` 中。无路径的固定来源引用通过相同 ID 和摘要解析到原件。需求或比较对象的内容摘要不冒充文件摘要。预检只列出资源/模板身份，不复制执行器配置或凭证。

重复 ID、悬空需求/采用来源引用、文件缺失/缺少摘要/摘要不符、未知政策、执行结果不明均阻断接受。活动工作包或活动节点也阻断该案例迁移，即使上层状态出现不一致。其他未选中的活动案例可继续运行，原 Case/Run 对象不改变。

本模块核对项目副本所含工作包、节点和 Run 引用，不读取独立的 SQLite `runs`/`claims` 表。未来实际迁移前仍须在一致性备份中核对运行主账、租约、资源版本和权限；不能把单个 Project 预检当作数据库一致性验收。

## 显式接受与回执

```python
result = migration.apply(
    detached_project,
    preview,
    expected_version=preview["source_version"],
    accepted_digest=preview["digest"],
    idempotency_key="reviewed-offline-batch-001",
    actor="named-migration-operator",
)
candidate_project = result["project"]
receipt = result["receipt"]
```

`accepted_digest` 必须明确提供且匹配原报告。模块重新读取文件、重做预检并完整比较报告，拒绝报告修改、预检后输入/文件变化和错误版本。失败不修改入参，也不留下部分迁移对象。

回执记录具名接受主体、意图摘要、原/目标版本、所选 Case、旧 lifecycle、文件清单摘要、原事实摘要和前后总量。只有总量相等且除生命周期/回执/版本外的事实逐项相同时才返回成功。

将回执随返回副本一起保存，才具备跨进程重试依据。收到结果后丢失响应时，使用返回副本与同一预检、原 `expected_version`、原摘要、原主体和幂等键重试，返回原回执，不复制成果。相同键而接受意图不同返回 409。幂等检查先于版本检查；迁移后的后续业务写入不会被原重试恢复成旧状态。以新键重复迁移已为 v2 的案例会被阻断。

模块返回的是离线候选。将候选写入活动库需要另行明确范围、事务版本检查和文件/主账复核；本模块不提供绕过项目命令权限的导入接口。

## 历史对象的后续办理

| 原状态 | 离线采用结果 | 后续办理 |
|---|---|---|
| 已完成 | 保留完成状态、旧成果和旧阶段，历史启动待核 | 查看和复核旧成果；新业务需求新建 v2 Case |
| 从未执行的草稿 | 原草稿不变，列出 `taskbook` v2 / `planning` 候选 | 先确认需求、形成选型决定、独立启动，再采用新流程/新计划 |
| 失败/取消 | 原失败/取消状态、已生成成果和 Run 不变 | 核对失败原因、未决外部结果及旧成果；授权后另建新计划，不重放旧 Run |
| submitted/running | 不能接受该案例转换 | 原 Owner 按原快照完成/取消并对账后，再重新预检 |
| 有独立启动记录 | 保留记录，完整引用链仅列为待政策复核候选 | 核查适用制度、主体资格、对象版本和签署性质，禁止因迁移自动批准 |
| 无独立启动记录 | `historical_unverified`，不分配研发编号 | 依据当前需求走完整新业务流程，不能用任务书成果倒推出批准 |

原 Case 的旧阶段不会因迁移回退。处于 `design` 等后期阶段的旧案应新建 v2 Case 续办，关联原来源和历史成果；原始文件继续按原摘要保留。新 Case 的来源采用、需求确认、选型决定、启动和新计划采用均走现有领域命令，不在此模块批量改阶段。历史 `definition_version=1` 草稿不会成为 v2 策划工作包；`historical_unverified` 也不能通过新工作包准入。

## 回退与对账

1. 保存独立的原副本、文件清单、预检及接受回执，并以 `source_digest` 和文件摘要核对；代码提交不能替代数据备份。
2. 尚无实际数据写入时，丢弃离线候选即可；本模块没有改动原副本或文件。
3. 若未来已采用 v2 但尚未产生新业务写入，允许按获准范围切回旧读取投影。依据回执的原版本、原 lifecycle 和原快照核对，不重新计算历史生成结果。
4. 一旦形成新的来源、决定、启动、计划、成果或权限变化，禁止用旧数据库覆盖当前数据库。先导出当前事实、按 ID 与摘要对账，再形成有独立版本/幂等回执的逆向迁移或补偿方案。旧事实与新事实都必须保留。
5. 逆向迁移需要处理新记录引用、并发版本、活动 Run Owner 和未决外部结果；本模块未实现自动逆向写入，不能仅凭 `source_lifecycles` 覆盖当前 lifecycle。

## 验证范围

`python -m pytest basic-service/app/tests/rd_platform/test_lifecycle_migration.py -q`

行为测试覆盖完成/草稿/运行/提交/失败/取消、真实领域命令生成的本地启动记录及缺失/失效证据、固定文件引用、篡改/缺失文件、未知执行结果、重复 ID、悬空引用、选择范围、显式摘要、版本冲突、同键异意图、幂等重试、旧事实/权限/快照/成果总量保持和报告不泄露执行器配置。

未执行：生产库迁移、正式企业启动证据资格验收、外部资源/租约主账迁移、自动逆向写入。预检和测试通过不能替代这些接受条件。
