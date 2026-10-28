# 开发与验证

## 环境和启动

后端使用 Python 3.13，前端使用 Node.js 22.6 及以上。沿用现有环境时无需重新安装依赖。首次准备：

```powershell
python -m venv basic-service/.venv
basic-service/.venv/Scripts/python.exe -m pip install -r basic-service/requirements-dev.txt
npm --prefix web ci
```

Linux/macOS 使用 `basic-service/.venv/bin/python`。复制根 `.env.example` 为私有 `.env` 并填写所需配置；密钥不进 Git。角色、本地 mock 和模型配置说明见 [研发管理交接](rd-platform-v1.md) 与 [模型配置](model-configuration-migration.md)。

本地研发管理平台沿用 `./start-demo.ps1 -Port 18130`；它提供 mock 身份与持久化示例项目。现有 `start.ps1`、`run_.sh`、Docker/Compose 入口也保持兼容。页面布局和任务书生成流程没有因目录重构改变。

前端热更新：`npm --prefix web run dev`，访问 Vite 输出地址，业务 API 默认代理到 18130，管理 API 到独立的 18131。静态页面交付：`npm --prefix web run build`，产物在 `web/dist`。

## 常用检查

以下命令在仓库根运行；`scripts/check.py` 会优先选用已有后端虚拟环境，并固定子进程工作目录。也可用脚本绝对路径从其他目录运行。

| 命令 | 范围 |
| --- | --- |
| `python scripts/check.py` | 前端测试/类型检查/构建，再完整后端离线测试 |
| `python scripts/check.py frontend` | 前端 Node 测试及含 TypeScript 检查的构建 |
| `python scripts/check.py backend` | 完整后端 pytest；不排除历史失败 |
| `python scripts/check.py rd` | 研发项目与小航的快速后端回归 |
| `npm --prefix web test` | 前端行为与纯函数测试 |
| `npm --prefix web run typecheck` | 只检查 TypeScript |

后端直接运行同样可用：

```powershell
basic-service/.venv/Scripts/python.exe -m pytest
basic-service/.venv/Scripts/python.exe -m pytest basic-service/app/tests/assistant -q
basic-service/.venv/Scripts/python.exe -m pytest --collect-only -q
```

`pytest.ini` 提供统一根目录、导入路径和测试目录。不要把业务实现复制到测试中，也不要从一个 `test_*.py` 导入另一个测试；公共场景放 `tests/support`。

## 浏览器与跨层验证

浏览器检查是可选依赖，不作为应用运行依赖安装：

```powershell
basic-service/.venv/Scripts/python.exe -m pip install -r basic-service/requirements-browser.txt
basic-service/.venv/Scripts/python.exe -m playwright install chromium
```

Python 浏览器脚本优先采用 `PLAYWRIGHT_CHROMIUM_EXECUTABLE`，Windows 其次使用已安装的 Edge，其他情况使用 Playwright Chromium。`TEST_BASE_URL` 可指定已启动服务；小航 Python 浏览器默认 18130，历史 JS 页面脚本默认 Vite 5173。

```powershell
python scripts/check.py browser --list
python scripts/check.py browser --case assistant.browser.py
python scripts/check.py browser --case assistant-launcher.browser.py
python scripts/check.py browser --case assistant-animation.browser.py
python scripts/check.py e2e --list
python scripts/check.py e2e --case rd_assistant_browser_smoke.py
python scripts/check.py e2e --case rd_taskbook_browser_smoke.py
```

`browser` 脚本依赖启动好的页面，关键业务/模型请求由用例拦截；`e2e` 脚本自己启动隔离的 HTTP 服务和 SQLite。后者不写用户现有项目。证据统一写入忽略的 `basic-service/app/runtime`。

统一入口会为 JS 浏览器脚本自动查找项目 Python Playwright 的 `playwright/driver/package/index.mjs`，复用同一浏览器安装；也支持通过 `PLAYWRIGHT_MODULE` 和 `PLAYWRIGHT_CHROMIUM_EXECUTABLE` 覆盖。截图默认写入忽略的 `app/runtime/browser-checks`，可用 `SCREENSHOT_DIR` 指定其他目录。它们保留各自页面/身份前置条件，目录迁移不等于所有历史用例都适用于当前业务入口。

## 真实服务联调

```powershell
python scripts/check.py live --list
python scripts/check.py live --case assistant-live.browser.py
```

`live` 不属于默认检查，必须明确指定用例。这些脚本使用真实模型或服务，应阅读脚本前置条件再运行；`rd_assistant_live_probe.py` 的操作只针对临时合成项目。不要把外网凭证写入 fixture 或把真实环境数据复制进仓库。

最近一次结构重构的已验证范围和保留的历史失败见 [验证记录](structure-refactor-validation.md)。

## 修改与交付

先根据 [架构说明](architecture.md) 找到业务归属，修改模块与对应测试。前端重构验证类型、构建和浏览器交互；项目命令验证权限、版本冲突、幂等、审签与发布；生成内核的改动需要运行完整任务书回归。

提交前检查 `git diff --check` 和 `git status --short`。`.gitignore` 不会取消已经跟踪的文件，使用 `git ls-files --cached --ignored --exclude-standard` 检查是否已有应排除的文件；不要通过全仓库 `git rm --cached` 重建索引。提交前核对模板、测试、锁文件、脚本仍可跟踪，真实配置、SQLite、日志、报告及构建产物不可跟踪。
