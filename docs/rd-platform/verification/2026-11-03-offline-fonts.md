# 离线字体交付核验

日期：2026-11-03。字体与静态资源已完成，未提交代码。

## 来源与授权

- 主字体：Adobe **思源黑体简体中文 Source Han Sans CN VF 2.005**，官方源 commit `a4f7cf94edfb9d7ffbdfc4841de276358bd7e0f2`，源 SHA-256 `f971e3bff46f76b49e1d5510556c2297c618ec4b491a295a4e741cdd38257799`。衍生分片的内部 family / PostScript 名改为 **RD Sans / RDSans**，避免使用 `Source` 保留字体名称；原版权及 OFL 记录仍保留。可变字重250–900，支持400/500/600等实际字重。
- 数据字体：IBM **Plex Mono Regular/Medium**，官方 commit `71f558992315a12ca1f06a2215d57962a1992162`。两份WOFF2保持上游原文件，**RD Mono**仅为CSS别名。
- 两者采用 **SIL Open Font License 1.1**；完整上游许可证随 `web/public/fonts/` 分发，原始来源URL、字节数与SHA-256列于 `manifest.json`。OFL允许使用、嵌入、再分发和修改，实际分发保留原版权及许可证，修改字体遵循保留名称约束。

官方依据：[Source Han Sans 许可证](https://github.com/adobe-fonts/source-han-sans/blob/master/LICENSE.txt)、[IBM Plex 许可证](https://github.com/IBM/plex/blob/master/LICENSE.txt)。

## 体积与覆盖

| 项目 | 核验结果 |
| --- | --- |
| 主字体片数 | UI优先片1份＋CJK片28份 |
| 优先片 | 390,668字节、2,291码位；HTML同源preload |
| 主字体覆盖 | 并集30,926码位，等于原始CN字体全部映射码位；分片交集为0 |
| 全部WOFF2 | 31份，含2份Mono，总9,484,392字节 |
| fonts.css | 21,897字节，本地`/fonts/`路径、unicode-range按需加载、font-display:swap |
| fonttools依赖 | 仅使用独立`runtime/font-build-venv`构建，不进入业务Python环境或前端运行依赖 |

优先片是加载顺序安排，未限制后续产品名称或资料字符。源字体内其余字符仍可按需加载；源字体本身不覆盖的Unicode字符使用系统后备字体，不宣称覆盖全部Unicode。

## 直接完成的验证

1. 读取全部29份思源WOFF2，确认内部family为RD Sans、cmap并集30,926且没有重叠；UI片确认wght范围250–900、原copyright存在、保留名称没有留在改名前的primary family/PS字段。
2. 31份字体文件SHA-256均与生成manifest一致；源文件下载时逐份验证固定hash。
3. 生产构建后逐文件比较 `web/public/fonts/` 与 `web/dist/fonts/`：31份WOFF2、2份许可证、README与manifest共35份文件字节一致，dist内所有字体hash正确。字体核验代理未另起构建；根代理后续修正样式并最终构建后，再次核对35份资源SHA256全部一致，证据为 `screenshots/2026-11-03-refined-theme/typography/build-font-copy.json`。
4. `git diff --check` 通过。正常字体重建重新生成所有片；仅恢复同一次中断构建时可显式使用`--resume-pinned-build`，并校验已有片的cmap、内部名与字重轴后复用。构建脚本不触及业务资料。

根代理的实际浏览器核验另已确认：400/500/600字重、Mono及中文罕字样本由自定义字体渲染（CDP），初始主页请求2份同源字体且无外部字体请求；阻断字体资源时页面保持可读。浏览器截图与完整平台验收由根代理汇总，静态核验不替代内网Chrome104实机验收。

重建说明与各源URL见 `web/public/fonts/README.md`；工具为 `web/scripts/build-fonts.py`，默认验证固定上游hash；上游或子集规则更新后应完整重建，不能使用中断恢复选项沿用旧片。
