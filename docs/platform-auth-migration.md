# 神州问学鉴权迁移与接入说明

日期：2026-10-15。

本次迁移的直接对接方是**神州问学**：浏览器跳转到其登录入口，后端调用其令牌校验接口。参考代码没有实现 OA 登录接口，也不能证明神州问学上游已接通 OA；真实登录、账号映射和回跳参数仍需在目标环境联调。

## 参考来源与实际调用链

参考为流程卡服务 **1.3.10 Docker archive**，只读核对原始文件：

| 项目 | 值 |
| --- | --- |
| 文件名 | `agent-trial-doc-audit-service_1.3.10.tar.gz` |
| 文件大小 | `245910334` 字节 |
| SHA256 | `0fb2c9e897e08c1db5df11190c43e70fc2ad3d747e77572de520f0f1690e0781` |

SHA256 流式计算自整个压缩 tar 文件，不是 Docker image ID；计算过程未执行镜像内容。

只读提取目录：`basic-service/app/runtime/oa-migration/reference/app/flowcard/`。本次核对的是以下实际调用关系：

| 参考代码 | 身份使用位置 |
| --- | --- |
| `controller/__init__.py` → `controller/app.py` | 装配 FastAPI，安装 `services/auth.py` 的 `AuthASGIMiddleware` |
| `controller/pages.py` 的 `_page` → `get_current_user` → `_render_sidebar` | 显示平台姓名，姓名为空时显示 `userid`；未启用时显示本地模式；历史列表传入 `userid` 筛选 |
| `controller/routes.py` 的 `/prepare`、`/generate` | 将 `created_by`、`created_name` 写入任务 `_meta.json`，后续生成沿用归属 |
| `controller/jobs.py` 的 `_job_visible` | 比较 `created_by` 和当前 `userid`；路由中的历史、报告、下载入口调用它 |
| `controller/routes.py` 的 `/feedback/{job_id}`、`/admin` | 本人任务反馈写入 `feedback.by`；管理入口另外通过 `PROMPT_EDITORS` 名单判断 |

参考任务归属校验与本项目的任务路由是不同实现。本次身份用于研制任务书主站准入、侧栏显示和反馈归属，不能仅凭迁移登录就认定所有任务接口已具备参考服务的用户隔离。

## 登录协议与迁移后的行为

登录入口保持兼容：

```text
GET {JTB_AUTH_PLATFORM_BASE_URL}/oauth2/login?app_id={自定义应用编号}&redirect_uri={URL编码的返回地址}
```

平台回跳携带 `userid`、`token`，可携带 `appid`。后端向同一平台发起：

```http
POST /tenant-api/api/auth/check-app-token
Content-Type: application/json
```

```json
{"userid":"example-user","token":"<回跳令牌>","appid":123}
```

`123` 仅为 JSON 整数示例；实际始终使用服务端配置的自定义应用编号，回跳 `appid` 与配置不一致会被拒绝。仅 HTTP 2xx 且响应 `code` 为整数 `0` 时验证成功，例如：

```json
{"code":0,"data":{"name":"示例用户"}}
```

姓名先从响应 `data` 对象取，再从响应顶层取；每层依次尝试 `name`、`username`、`userName`、`nickname`、`realName`、`real_name`、`display_name`，去掉首尾空白。没有姓名时回退为已验证的 `userid`。

迁移保留接口和 Cookie 名称，同时收紧信任边界：

| 项目 | 参考服务 | 研制任务书实现 |
| --- | --- | --- |
| 登录开关 | `AUTH_ENABLED=true` 且 `APP_ID` 非空才拦截；缺编号会放行 | 默认关闭；启用但缺有效编号或明确的站点 origin 时，配置加载失败 |
| 已有 Cookie | `sv_token`、`sv_userid` 同时存在就放行 | 必须经平台验证；缺项、空值、伪造姓名 Cookie 不能作为身份 |
| 姓名 | 平台响应缺姓名时可用 URL 姓名兜底；写入 `sv_username` | 仅使用验证响应或已验证 `userid`；忽略 URL 姓名、`sv_username` 和客户端身份头 |
| 回跳地址 | 根据请求及转发头拼接 | 启用时固定使用 `JTB_AUTH_PUBLIC_URL`，不由 Host 或转发头选择回跳域 |
| 登录发起校验 | 无登录 state | 发起登录时生成随机 nonce，放入返回地址 `_jtb_auth_state` 和 10 分钟的 `sv_login_state` Cookie；回跳恒定时间比较，成功后清除 |

没有 state 或 state 不一致的 `userid+token` 链接会先重新进入神州问学登录，不会直接建立该链接提供的身份。**平台必须原样保留 `redirect_uri` 已有的 query，再追加回跳参数**；若丢失 `_jtb_auth_state`，将无法完成登录。这一行为尚待内网联调确认。

验证成功后写入 `sv_appid`、`sv_token`、`sv_userid`；Cookie 为 HttpOnly、host-only、SameSite=Lax，默认有效 8 小时，配置的站点 origin 为 HTTPS 时启用 Secure。旧 `sv_username` 会清除。随后 302 到干净地址，清除 token、账号、应用编号、姓名和登录 state 参数，保留其他重复及中文查询参数；响应使用 `no-store`、`no-referrer`。

平台验证默认缓存 60 秒，每个服务进程最多 512 项，以 `userid + token + appid` 的哈希为键，不缓存原始 token；到期或凭据变化后重新验证。缓存有效期内沿用最近一次验证结果，可将缓存秒数设为 `0` 以每次验证。

业务 API 未登录返回 `401`，包含 `error`、`auth_required: true`、`login_url: "/auth/login"`；平台连接失败或 5xx 返回 `503`。健康检查 `/api/health`、静态资源公开可用。

`GET /api/current-user` 返回 `auth_enabled`、`authenticated`、`user`；已登录用户包含 `userid`、`name`、`display_name`、`source: "smartvision"`、`verified: true`，不返回 token。无凭证时可返回未登录状态，有无效 Cookie 时拒绝，平台故障时仍返回 503。`GET /auth/login` 重新登录并安全返回主站根路径。

## 启用配置

部署默认在应用构造时读取，每一项先按来源选择：进程环境 → 项目根 `.env` → 镜像内 `app/src/service/.env`；同一来源内优先使用带 `JTB_AUTH_` 前缀的变量，旧变量仅用于兼容。界面已保存的四项配置（开关、应用 ID、神州问学地址、回跳 origin）再覆盖部署默认，超时、缓存与 Cookie 期限继续使用部署配置。只读取鉴权配置，不改变模型凭证配置或进程环境；纯镜像启动也能读取固化的鉴权配置。

| 变量 | 兼容变量 | 默认值／要求 |
| --- | --- | --- |
| `JTB_AUTH_ENABLED` | `AUTH_ENABLED` | `false`；仅接受 `true` / `false` |
| `JTB_AUTH_APP_ID` | `APP_ID` | 无默认值；启用时必须是正整数自定义应用编号 |
| `JTB_AUTH_PLATFORM_BASE_URL` | `PLATFORM_BASE_URL` | `https://sv.dcsmartvision.com`；内网按部署填写 |
| `JTB_AUTH_PUBLIC_URL` | 无 | 启用时必填；研制任务书网站的浏览器访问 origin，包含协议、主机及必要端口，不含路径、query 或凭据 |
| `JTB_AUTH_TIMEOUT_SECONDS` | 无 | `10`；大于 0 |
| `JTB_AUTH_CACHE_SECONDS` | 无 | `60`；可设 `0`，不能为负数 |
| `JTB_AUTH_COOKIE_MAX_AGE` | 无 | `28800` 秒；正整数 |

替换下列占位符后可用于目标环境；示例不含真实凭据：

```dotenv
JTB_AUTH_ENABLED=true
JTB_AUTH_APP_ID=9192
JTB_AUTH_PLATFORM_BASE_URL=http://172.23.255.36
JTB_AUTH_PUBLIC_URL=<平台完整origin>
# 外网平台地址改为：https://sv.dcsmartvision.com
```

`JTB_AUTH_PUBLIC_URL` 是**研制任务书网站**地址，例如 `https://taskbook.example.org`，不是上面神州问学的登录域名。本地开发保持 `JTB_AUTH_ENABLED=false`，反馈姓名继续手填并标记为未验证。

这里的自定义应用编号与模型服务 App ID 分属两条链路。用户已确认研制任务书的自定义应用编号为 `9192`，目前仍需确认部署后的浏览器访问 origin。参考镜像的 `APP_ID=84` 仅代表参考流程卡应用，不能默认复制给研制任务书；参考模型调用使用 `LLM_APP_ID`，本项目模型设置使用 `MODEL_APP_ID` / `JTB_LLM_APP_ID`。已有模型编号 `1000000111`、`1000000033` 不作为登录应用编号。

## 部署后从设置填写地址

侧栏齿轮进入服务设置，再打开“统一登录设置”。应用 ID 使用 `9192`；当前可保持关闭且回跳地址留空。部署地址确定后填写：

- 神州问学地址：实际登录平台的 origin，例如外网 `https://sv.dcsmartvision.com` 或内网 `http://172.23.255.36`。
- 回跳地址：用户访问研制任务书的 origin，例如 `http://服务器地址:18130`，包含协议、主机及端口，不含路径或参数。

启用开关时必须具备有效应用编号与回跳地址。点击“保存登录设置”后，当前运行策略不变，重启平台后才采用新配置；模型凭证使用另外的保存操作。

配置独立保存在 `basic-service/app/runtime/auth_settings.sqlite3`，使用 `JTB_AUTH_SETTINGS_DB` 可指定路径。主服务和反馈管理服务必须共用该路径；Compose 既有 runtime 卷会持久保存它。设置使用版本校验，多页冲突返回 409，失败保留输入。客户端只能提交四个配置项和版本，不能提交 token。

已启用登录的主站不能修改这组设置，避免普通登录用户关闭鉴权；运维可从私有 `18131` 反馈管理页的“统一登录设置”入口调整，保存后重启。私有端不声称展示主站的实时运行策略，不提供自动重启操作。

## 反馈保存与管理边界

主站启用鉴权后，反馈的显示姓名由服务端身份覆盖，客户端不能提交或修改 `identity`。身份部分只保存 `userid`、首次姓名 `name`、`source`、`verified`，不保存 token。幂等提交绑定稳定账号，姓名变化或管理员更正显示文字后，同账号重试仍返回原记录；其他账号不能复用同一提交标识。

SQLite 在事务内为旧表增加 `identity TEXT NOT NULL DEFAULT '{}'`：旧记录保持 `{}`，不虚构验证身份；新的手工反馈标记 `source: "manual"`、`verified: false`。管理员可以修正显示姓名，但原始身份快照和提交摘要保持不变。

`18131` 仍是独立私有反馈管理服务。主站登录表示身份已识别，不表示拥有管理员权限；参考服务的 `PROMPT_EDITORS` 授权规则也没有自动成为本项目的管理权限。

## 验证范围与接入确认

本地针对性测试覆盖平台校验、姓名可信来源、伪造 Cookie/请求头、应用编号隔离、nonce 回跳、查询参数清理、缓存及反馈身份迁移。另以三个真实本地服务进程和 Chrome 验证完整跳转、SSE、反馈入库及管理页查看/修改，登录平台是本地模拟服务。**未连接真实神州问学或 OA，不能据此声称真实登录已验证**。

nginx 页面的请求会先进入后端，避免静态入口绕过回跳校验；访问日志只保留路径。容器入口通过 `src.common.nginx_logs` 转发并脱敏 nginx 两路输出，因此上游连接失败等错误不会把回跳 query 直接写到容器日志。该包装层使用真实 Python 子进程验证输出和停机流程；本机 Docker daemon 未启动，尚未运行镜像内的 nginx 验证。

已有版式编辑服务的取文件与回存回调只在精确方法、路径上免除浏览器登录 Cookie 要求，继续使用原有签名 token 校验。打开编辑会话、查询会话、保存版本等业务接口仍要求统一登录，不能将整个审阅 API 加入白名单。

目标环境还需确认本应用编号及授权、平台校验接口可达、用户字段和中文姓名实际返回、平台注册的返回 origin，以及 nonce query 原样往返。接入代理和服务访问日志须避开完整回跳 query，避免在清理浏览器地址前记录 token。
