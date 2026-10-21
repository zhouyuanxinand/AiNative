"""Public, dependency-free application logout confirmation page."""

LOGGED_OUT_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>已退出本应用 · 研制任务书平台</title>
  <style>
    :root { color-scheme: light; font-family: -apple-system, BlinkMacSystemFont,
      "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      color: #1d1d1f; background: #f5f5f7; }
    * { box-sizing: border-box; }
    body { margin: 0; min-height: 100vh; display: grid; place-items: center; padding: 24px; }
    main { width: min(100%, 480px); padding: 36px; border: 1px solid #dedee3;
      border-radius: 14px; background: #fff; }
    .brand { margin: 0 0 28px; color: #6e6e73; font-size: 14px; }
    h1 { margin: 0 0 16px; font-size: 24px; line-height: 1.4; }
    .description { margin: 0 0 28px; color: #6e6e73; font-size: 15px; line-height: 1.8; }
    a { display: inline-flex; align-items: center; justify-content: center; min-height: 44px;
      padding: 10px 18px; border-radius: 10px; background: #0071e3; color: #fff;
      font-size: 14px; line-height: 1.5; font-weight: 500; text-decoration: none; }
    a:hover { background: #0077ed; }
    a:active { background: #0068d1; }
    a:focus-visible { outline: 2px solid #0071e3; outline-offset: 4px; }
    @media (max-width: 480px) { main { padding: 28px 24px; } }
  </style>
</head>
<body>
  <main>
    <p class="brand">研制任务书平台</p>
    <h1>已退出本应用</h1>
    <p class="description">当前浏览器的研制任务书登录会话已清除。</p>
    <a href="/">重新进入应用</a>
  </main>
</body>
</html>"""
