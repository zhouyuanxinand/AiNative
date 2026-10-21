# 神州问学鉴权迁移与接入说明

更新日期：2026-10-21；保留 2026-10-15 首次迁移的参考记录。

本次迁移的直接对接方是**神州问学**：浏览器跳转到其登录入口，后端调用其令牌校验接口。参考代码没有实现 OA 登录接口，也不能证明神州问学上游已接通 OA；真实登录、账号映射和回跳参数仍需在目标环境联调。

## 参考来源与实际调用链

2026-10-21 按用户要求，以 `agent-auto-input-audit-service.zip` 内的正式实现为本次对齐基准，
只读检查压缩包，未执行其中代码。此前提供的独立 `auth_interceptor.py`、`auth_controller.py`
用于辅助对照；它们不覆盖压缩包中实际启用的实现：

| 参考文件 | 核对结果与本项目采用方式 |
| --- | --- |
| 压缩包 `basic-service/app/src/common/smartvision_auth.py` | 对齐 `login_mode=auto`、直接 `userid/token` 回跳、关闭系统代理、匹配应用编号的完整 Cookie 放行、缺姓名补查、`sn` 优先、中文姓名编码、会话 Cookie 和 307 跳转 |
| 压缩包身份与退出接口 | 新增 `/api/auth/me`、`POST /api/system/logout` 和 `/logged-out`；保留本项目 `/api/current-user`，不复制参考应用的角色名单、权限管理或业务接口 |
| 独立 `auth_interceptor.py`、`auth_controller.py` | 辅助核对登录平台接口和姓名字段；不将其旧 Cookie 名称或业务权限配置作为本项目默认值 |
| 压缩包 `web/nginx/nginx.conf` | 使用 `$http_host` 保留发布端口，并处理上游协议；本项目保留实际 Host，只接收上游明确的 `https` 协议标记，不使用原始 `X-Forwarded-Host` 选择回跳主机 |

参考包中的应用编号属于其他应用，不作为本项目默认值。本项目内网编号为 `127`，外网测试编号
已确认为 `9086`；旧说明中的 `9192` 不再作为外网配置指导。平台地址与应用编号固定，变化的是
研制任务书网站的发布端口，回跳应根据发起登录时的访问地址生成。

2026-10-15 首次迁移参考为流程卡服务 **1.3.10 Docker archive**，只读核对原始文件：

| 项目 | 值 |
| --- | --- |
| 文件名 | `agent-trial-doc-audit-service_1.3.10.tar.gz` |
| 文件大小 | `245910334` 字节 |
| SHA256 | `0fb2c9e897e08c1db5df11190c43e70fc2ad3d747e77572de520f0f1690e0781` |

SHA256 流式计算自整个压缩 tar 文件，不是 Docker image ID；计算过程未执行镜像内容。

只读提取目录：`basic-service/app/runtime/oa-migration/reference/app/flowcard/`。首次核对的是以下实际调用关系：

| 参考代码 | 身份使用位置 |
| --- | --- |
| `controller/__init__.py` → `controller/app.py` | 装配 FastAPI，安装 `services/auth.py` 的 `AuthASGIMiddleware` |
| `controller/pages.py` 的 `_page` → `get_current_user` → `_render_sidebar` | 显示平台姓名，姓名为空时显示 `userid`；未启用时显示本地模式；历史列表传入 `userid` 筛选 |
| `controller/routes.py` 的 `/prepare`、`/generate` | 将 `created_by`、`created_name` 写入任务 `_meta.json`，后续生成沿用归属 |
| `controller/jobs.py` 的 `_job_visible` | 比较 `created_by` 和当前 `userid`；路由中的历史、报告、下载入口调用它 |
| `controller/routes.py` 的 `/feedback/{job_id}`、`/admin` | 本人任务反馈写入 `feedback.by`；管理入口另外通过 `PROMPT_EDITORS` 名单判断 |

参考任务归属校验与本项目的任务路由是不同实现。本次身份用于研制任务书主站准入、侧栏显示和反馈归属，不能仅凭迁移登录就认定所有任务接口已具备参考服务的用户隔离。

## 登录协议与迁移后的行为

登录入口与压缩包一致，显式带自动登录模式：

```text
GET {JTB_AUTH_PLATFORM_BASE_URL}/oauth2/login?app_id={自定义应用编号}&redirect_uri={URL编码的返回地址}&login_mode=auto
```

平台回跳携带 `userid`、`token`，可携带 `appid`。后端向同一平台发起：

```http
POST /tenant-api/api/auth/check-app-token
Content-Type: application/json
```

```json
{"userid":"example-user","token":"<回跳令牌>","appid":123}
```

`123` 仅为 JSON 整数示例；实际始终使用服务端配置的自定义应用编号，不接受回跳参数切换应用。
HTTP 客户端设置 `trust_env=False`，此校验调用不使用 `HTTP_PROXY`、`HTTPS_PROXY` 等系统代理
环境变量；超时继续由 `JTB_AUTH_TIMEOUT_SECONDS` 控制。仅 HTTP 2xx 且响应 `code` 为整数
`0` 时验证成功，例如：

```json
{"code":0,"data":{"sn":"示例用户"}}
```

姓名先从响应 `data` 对象取，再从响应顶层取；每层优先 `sn`，再依次尝试 `name`、`realName`、`real_name`、`trueName`、`nickName`、`nick_name`、`displayName`、`display_name`、`user_name`、`username`、`userName`、`nickname`，去掉首尾空白。没有姓名时回退为已验证的 `userid`。不从 URL 姓名参数建立身份。

本次按压缩包对齐登录行为，同时保留本项目的配置与代理边界：

| 项目 | 压缩包基准 | 研制任务书实现 |
| --- | --- | --- |
| 登录模式 | `login_mode` 默认 `auto` | 固定发送 `login_mode=auto` |
| 已有 Cookie | token、userid 存在且 appid 与配置一致时放行 | 同样放行本应用完整 Cookie，不向平台逐请求或定期复核 |
| 姓名 | 优先平台 `sn`，姓名 Cookie 缺失时补查 | 对齐并保留原有姓名字段兼容；姓名按百分号编码保存和解码 |
| Cookie 名称 | `p02_sv_appid/token/userid/username` | 使用 `jtb_sv_appid/token/userid/username`，避免同主机其他应用的 Cookie 互相覆盖 |
| Cookie 期限与跳转 | 浏览器会话 Cookie，307 | 对齐；HttpOnly、host-only、SameSite=Lax，HTTPS 入口启用 Secure |
| 回跳地址 | 根据请求及转发头拼接 | 非空 `JTB_AUTH_PUBLIC_URL` 保持固定回跳；留空时使用允许主机的当前 Host、端口与协议，不使用原始 `X-Forwarded-Host` |
| 登录发起校验 | 无登录 state | 对齐，不再生成或要求 `_jtb_auth_state`／`sv_login_state` |
| 角色与管理 | 使用参考应用的角色服务与授权名单 | 不迁移其他应用角色管理；当前普通登录用户返回 `is_admin: false`、`is_dev: false`，私有反馈管理入口保持原边界 |

平台直接带回 `userid+token` 即可进入校验，不再因缺少额外 state 而重新登录。业务查询参数
继续随回跳保留；清理身份参数时保留重复及中文参数，并将 `appid` 规范为服务端配置的编号。
不能依靠 URL 姓名、客户端身份头或其他应用 Cookie 指定当前用户。

验证成功写入四个 `jtb_sv_*` Cookie，随后 307 到清理身份参数后的地址；响应使用
`no-store`、`no-referrer`。Cookie 不设置固定的 Max-Age；旧版 8 小时 Cookie 设置不再用于
新登录。已有会话按参考包方式放行，旧版“每 60 秒重新校验平台令牌”不再是正常会话行为。

`GET /api/auth/me` 提供参考包兼容的账号、姓名、`is_admin` 和 `is_dev` 字段，不返回 token。
现有 `GET /api/current-user` 保留 `auth_enabled`、`authenticated`、`user` 的响应结构，
已登录身份仍用于侧栏与反馈归属；无凭证时此接口可以返回未登录状态供现有前端判断。
其他受保护业务 API 未登录返回 `401`。健康检查、静态资源以及 `/logged-out` 保持公开。

`POST /api/system/logout` 清除本应用 Cookie，侧栏退出入口随后进入 `/logged-out`；
该页面不自动发起统一登录，用户可主动重新登录。退出不撤销问学／OA 会话，也不清除
参考应用的 `p02_sv_*` Cookie。`GET /auth/login` 可重新发起登录并返回主站根路径。

## 启用配置

部署默认在应用构造时读取，每一项先按来源选择：进程环境 → 项目根 `.env` → 镜像内 `app/src/service/.env`；同一来源内优先使用带 `JTB_AUTH_` 前缀的变量，旧变量仅用于兼容。界面已保存的四项配置（开关、应用 ID、神州问学地址、回跳 origin）再覆盖部署默认，回跳主机扩展列表与超时继续使用部署配置。只读取鉴权配置，不改变模型凭证配置或进程环境。

| 变量 | 兼容变量 | 默认值／要求 |
| --- | --- | --- |
| `JTB_AUTH_ENABLED` | `AUTH_ENABLED` | 源码默认 `false`，发布镜像默认 `true`；仅接受 `true` / `false` |
| `JTB_AUTH_APP_ID` | `APP_ID` | 默认内网 `127`；外网测试为 `9086`；启用时必须是正整数自定义应用编号 |
| `JTB_AUTH_PLATFORM_BASE_URL` | `PLATFORM_BASE_URL` | 默认内网 `http://172.23.255.36`；外网测试为 `https://sv.dcsmartvision.com` |
| `JTB_AUTH_PUBLIC_URL` | 无 | 默认留空，自动使用当前主站 origin；非空时固定使用该 HTTP(S) origin，包含必要端口，不含路径、query 或凭据 |
| `JTB_AUTH_CALLBACK_HOSTS` | 无 | 默认空；逗号分隔的额外回跳主机，仅填主机名或 IP，不含协议、端口或通配符 |
| `JTB_AUTH_TIMEOUT_SECONDS` | 无 | `10`；大于 0 |

旧 `JTB_AUTH_CACHE_SECONDS`、`JTB_AUTH_COOKIE_MAX_AGE` 仍可读取以兼容已有配置，但不再
决定本次对齐后的会话放行与 Cookie 生命周期。部署无需继续设置这两项。

内网使用固定应用 ID 与平台地址，发布端口每次从主站访问地址取得：

```dotenv
JTB_AUTH_ENABLED=true
JTB_AUTH_APP_ID=127
JTB_AUTH_PLATFORM_BASE_URL=http://172.23.255.36
JTB_AUTH_PUBLIC_URL=
```

外网测试使用另一组应用配置，回跳方式仍可自动：

```dotenv
JTB_AUTH_ENABLED=true
JTB_AUTH_APP_ID=9086
JTB_AUTH_PLATFORM_BASE_URL=https://sv.dcsmartvision.com
JTB_AUTH_PUBLIC_URL=
```

源码直接运行且没有配置覆盖时，默认 `JTB_AUTH_ENABLED=false`，其余预填内网值；未启用时反馈姓名继续手填并标记为未验证。

Dockerfile 明确将内网示例中的四项写为镜像 `ENV`，包括空的回跳地址，从而覆盖包内 `.env` 中的本地外网测试鉴权值。现有离线交付仍将 `.env` 放入镜像供模型配置使用，登录默认值由镜像环境变量确定。部署时显式注入的 `JTB_AUTH_*` 和界面已保存配置仍可覆盖默认值。Compose 使用部署目录的 `env_file: .env` 注入进程环境，因此现场文件中的外网测试值仍会生效，应切换为对应部署配置。

自动模式只允许当前神州问学平台主机、`localhost`、`127.0.0.1`、`::1`，以及 `JTB_AUTH_CALLBACK_HOSTS` 中的额外主机；允许主机的发布端口可以变化。例如内网访问 `http://172.23.255.36:32253/` 时回跳使用该端口，下次部署访问 `http://172.23.255.36:32689/` 时自动改用新端口。使用其他主机时，可设置 `JTB_AUTH_CALLBACK_HOSTS=taskbook.example.org`；不允许的自动回跳主机返回 `400`，不会进入平台登录。

手动模式的 `JTB_AUTH_PUBLIC_URL` 是**研制任务书网站**的完整 origin，例如 `https://taskbook.example.org:9443`；神州问学地址是登录平台入口，两者分别配置。旧的非空固定地址保持兼容，不会被自动清空。固定地址不随访问端口变化，部署端口变化后需要修改。

这里的自定义应用编号与模型服务 App ID 分属两条链路。参考流程卡镜像的 `APP_ID=84` 和审核服务参考包的 `SMARTVISION_AUTH_APP_ID=86` 均不用于本项目；参考模型调用使用 `LLM_APP_ID`，本项目模型设置使用 `MODEL_APP_ID` / `JTB_LLM_APP_ID`。已有模型编号 `1000000111`、`1000000033` 不作为登录应用编号。

## 页面设置与旧配置迁移

侧栏齿轮进入服务设置，再打开“统一登录设置”：

- “使用内网配置”填入 `127` 和 `http://172.23.255.36`；“使用外网配置”填入 `9086` 和 `https://sv.dcsmartvision.com`。两者都会选中“自动跟随访问地址”，保持启用开关原值。
- “自动跟随访问地址”不需要填写发布端口；“手动指定地址”要求填写主站完整 origin，不能包含路径或参数。
- 按需打开“启用统一登录”，点击“保存登录配置”，然后重启平台。保存不会立即改变正在运行的会话或策略；模型凭证使用另外的保存操作。

**已经保存的数据库配置优先于镜像和进程环境变量。** 旧部署如保存过固定回跳地址，需要在页面切换一次“自动跟随访问地址”并保存、重启；升级镜像或仅清空环境变量不会覆盖旧配置。需要改用新的内网／外网应用编号时也应在这里保存相应预设。主站已启用登录时，通过私有反馈管理入口操作。

本次 Cookie 从旧 `sv_*` 更名为本应用的 `jtb_sv_*`。旧 Cookie 不作为新会话的登录凭据，
升级后需要重新登录一次。其他应用的 `p02_sv_*` 不会被读取或写入。应用编号切换后也需要
建立对应编号的新会话；不能用一个环境的 Cookie 直接进入另一个环境。

配置独立保存在 `basic-service/app/runtime/auth_settings.sqlite3`，使用 `JTB_AUTH_SETTINGS_DB` 可指定路径。主服务和反馈管理服务必须共用该路径；Compose 既有 runtime 卷会持久保存它。设置使用版本校验，多页冲突返回 409，失败保留输入。客户端只能提交四个配置项和版本，不能提交 token。

已启用登录的主站不能修改这组设置，避免普通登录用户关闭鉴权；运维可从私有 `18131` 反馈管理页的“统一登录设置”入口调整，保存后重启。私有端不声称展示主站的实时运行策略，不提供自动重启操作。

## 动态端口与反向代理

自动回跳从主站请求的协议和实际 Host 取得 origin，保留 Host 中的发布端口；应用不直接读取 `X-Forwarded-Host` 或 `Forwarded` 来选择主机。随包 nginx 使用 `Host $http_host` 转发，因此不能替换成会丢失外部端口的 `$host` 或容器内部地址。

容器 nginx 直接提供 HTTP 时使用实际 `$scheme`。只有直接连接 nginx 的来源 IP 在可信列表中，且协议头为 `X-Forwarded-Proto: https`，才保留外部 HTTPS；其他来源或值都回退到实际协议。默认仅信任 `127.0.0.1` 和 `::1`，不信任任意内网地址，也不使用 `X-Forwarded-For` 判断可信来源。后端通过受信任的 loopback nginx 取得处理后的协议。

上层 HTTPS 网关终止 TLS、再用 HTTP 访问容器时，将包含实际网关 IP 的配置目录只读挂载到 `/etc/nginx/taskbook-trusted-proxies.d/`。目录内的 `*.conf` 每行采用 `IP 1;`，例如：

```nginx
# gateway.conf：替换为 nginx 实际看到的网关连接来源 IP。
192.0.2.10 1;
2001:db8::10 1;
```

这些是精确 IP 条目，不支持 CIDR、主机名或通配符。无挂载目录、空目录或没有匹配文件时，默认配置仍可启动。可在部署配置中挂载 `./trusted-proxies:/etc/nginx/taskbook-trusted-proxies.d:ro`；首次配置或修改网关 IP 后，在容器内执行 `nginx -t`，再执行 `nginx -s reload` 或重启容器。Docker/NAT 场景应使用 nginx 实际看到的连接来源，并确保该入口只有受信任网关能以该来源访问；不能把共享出口 IP 下的普通客户端一并视为可信。仅改变发布端口无需修改这份 IP 列表。

可信网关必须删除或覆盖客户端提交的协议转发头，按实际外部协议重新设置，并保留带发布端口的 Host。这样 HTTPS 回跳和 Secure Cookie 与浏览器入口一致。无法配置可信网关来源的部署，也可将 `JTB_AUTH_PUBLIC_URL` 设为浏览器实际访问的完整 HTTPS origin；固定模式下发布端口变化需要同步更新该值。

主站回跳使用主站端口，不使用反馈管理端口。动态回跳不替代问学平台自身的应用授权或回跳地址注册要求；平台是否允许新发布端口，仍须在目标环境确认。

## 反馈保存与管理边界

主站启用鉴权后，反馈的显示姓名由中间件建立的当前身份覆盖，客户端不能在反馈请求中提交或修改 `identity`。首次登录由平台校验建立身份，后续匹配的本应用 Cookie 按参考包方式沿用身份，不代表每次反馈都重新向平台校验。身份部分只保存 `userid`、首次姓名 `name`、`source`、`verified`，不保存 token。幂等提交绑定稳定账号，姓名变化或管理员更正显示文字后，同账号重试仍返回原记录；其他账号不能复用同一提交标识。

SQLite 在事务内为旧表增加 `identity TEXT NOT NULL DEFAULT '{}'`：旧记录保持 `{}`，不虚构验证身份；新的手工反馈标记 `source: "manual"`、`verified: false`。管理员可以修正显示姓名，但原始身份快照和提交摘要保持不变。

`18131` 仍是独立私有反馈管理服务。主站登录表示身份已识别，不表示拥有管理员权限；参考服务的 `PROMPT_EDITORS` 授权规则也没有自动成为本项目的管理权限。

## 验证范围与接入确认

本次对齐的回归范围包括登录 URL 的 `login_mode=auto`、无 state 直接回跳、校验请求关闭
系统代理、完整会话 Cookie 放行、缺姓名补查、姓名编码、应用编号隔离、会话 Cookie、307
跳转、身份查询和退出。动态端口、`sn` 优先级、回跳主机限制、固定地址兼容、反馈身份绑定
及设置页的两组预设仍需保持通过。以本次实际执行的测试结果为准，不沿用旧版 nonce／定期
校验测试的结论来证明新会话行为。

首次迁移记录包括三个真实本地服务进程和 Chrome 下的完整跳转、SSE、反馈入库及管理页查看／修改，当时登录平台为本地模拟服务。

2026-10-21 本次对齐执行了 216 项后端相关测试，以及退出、身份与反馈浏览器回归、TypeScript／Vite 构建。Vite 使用实际开发服务器和模拟后端验证凭据回跳转交、发布端口保留和正常页面热更新。官方 Windows nginx 1.26.3 下的 3 次配置检查和 13 次实际代理请求验证了可信网关协议处理；未运行 Linux 镜像。

同日使用新的 Chrome 会话连接真实外网 `https://sv.dcsmartvision.com`，应用 `9086` 自动回跳到 `http://127.0.0.1:18130/`，完成登录、侧栏退出、公开退出页和重新登录。两次平台校验均返回 `code: 0`，显示姓名来自 `data.sn`，不是账号编号兜底，退出后用户接口返回未登录。该次联调两次平台返回的 `uid` 不同、`sn` 相同；应用按平台回传账号记录，并未将姓名当成稳定账号。指定员工 OA 账号的映射与稳定性仍需现场确认。

nginx 页面的请求会先进入后端，避免静态入口绕过回跳校验；访问日志只保留路径。容器入口通过 `src.common.nginx_logs` 转发并脱敏 nginx 两路输出，因此上游连接失败等错误不会把回跳 query 直接写到容器日志。该包装层使用真实 Python 子进程验证输出和停机流程；本机 Docker daemon 未启动，尚未运行镜像内的 nginx 验证。

已有版式编辑服务的取文件与回存回调只在精确方法、路径上免除浏览器登录 Cookie 要求，继续使用原有签名 token 校验。打开编辑会话、查询会话、保存版本等业务接口仍要求统一登录，不能将整个审阅 API 加入白名单。

内网 `127` 还需确认应用授权、校验接口可达、员工账号字段和平台注册的返回 origin，以及带动态发布端口的完整登录、退出和重新登录流程；外网自动登录联调不能代替内网员工 OA 账号验证。接入代理和服务访问日志须避开完整回跳 query，避免在清理浏览器地址前记录 token。
