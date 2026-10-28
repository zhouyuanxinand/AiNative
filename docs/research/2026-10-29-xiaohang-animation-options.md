# 小航人物动效：GitHub 方案核对

核对范围：官方仓库、README、源码/参数和 LICENSE。目标是在现有 React 18 / Vite 平台中保留小航形象，替换整张 PNG 晃动，支持拖动入口和右侧助手工作栏。本次未下载人物模型、未知程序或安装整套项目。

## 结论

本轮采用**自有角色精灵帧图 + 轻量播放器 + Pointer Events 拖动**最合适。这是针对当前单个人物、已有聊天和权限体系的工程判断：帧图直接保留附件形象，不必为了改善动效迁入另一套聊天产品，也不要求先制作骨骼模型。若之后增加多套动作、逐帧事件和大量角色，PixiJS `AnimatedSprite` 是已经核实的升级接口。[官方源码](https://github.com/pixijs/pixijs/blob/dev/src/scene/sprite-animated/AnimatedSprite.ts)

## 已核实的项目

| 项目 | 仓库事实与许可证 | 当前平台适配判断 |
|---|---|---|
| [PixiJS](https://github.com/pixijs/pixijs) | `AnimatedSprite` 接受纹理序列或带单帧时长的帧对象，提供播放、循环及帧切换回调；代码为 [MIT](https://github.com/pixijs/pixijs/blob/dev/LICENSE)。[源码](https://github.com/pixijs/pixijs/blob/dev/src/scene/sprite-animated/AnimatedSprite.ts) | 与 React 无绑定，可以在组件中管理创建/销毁。适合自有 spritesheet；一个小人物目前可先用浏览器原生播放，动作系统扩大时再引入。它提供播放器，不会自动把静态图片生成动作。 |
| [hacxy/l2d-widget](https://github.com/hacxy/l2d-widget) | 原 `oh-my-live2d` 当前已重命名、重写；README 明确要求迁移时按新 API 调整。`createWidget()` 管理模型加载、画布与交互，包含嘴部参数驱动和销毁接口，无前端框架依赖；代码为 [MIT](https://github.com/hacxy/l2d-widget/blob/main/LICENSE)。[README](https://github.com/hacxy/l2d-widget/blob/main/README.md) | 适合以后有正式小航 Live2D 模型的路线。不能把现有 PNG 或普通帧图直接当作 Cubism 模型；也不应按旧 oh-my-live2d 教程盲接当前版本。本次未核实其拖动 API，不声称原生拖动已可用。 |
| [stevenjoezhang/live2d-widget](https://github.com/stevenjoezhang/live2d-widget) | 网页 Live2D 挂件；README 有 `drag` 开关，默认 false。仓库不附人物模型；代码主体为 [GPL-3.0](https://github.com/stevenjoezhang/live2d-widget/blob/master/LICENSE)，Core 等部分另受 Live2D 许可约束。展示模型和动作不意味着可直接用于商业项目。[README](https://github.com/stevenjoezhang/live2d-widget/blob/master/README.md) | 可以参考人物拖动与挂件唤醒交互；不直接复制其模型或把它整体并入现有平台。 |
| [moeru-ai/airi](https://github.com/moeru-ai/airi) | 完整 AI 角色应用，README 列出 Live2D/VRM、眨眼、视线和待机眼动，以及网页和桌面运行方式；代码为 [MIT](https://github.com/moeru-ai/airi/blob/main/LICENSE)。仓库为多应用/多包结构。[README](https://github.com/moeru-ai/airi#readme)、[工作区配置](https://github.com/moeru-ai/airi/blob/main/package.json) | 值得参考“待机/思考/说话/交互”状态如何驱动表情；完整迁入的范围明显超过一个研发平台侧栏助手。自有小航仍需要相应资产，现成角色不能代替品牌素材。 |
| [bokuweb/react-rnd](https://github.com/bokuweb/react-rnd) | React 可拖拽/伸缩组件，支持受控位置、拖动结束回调、`bounds`、拖动手柄和取消区域；代码为 [MIT](https://github.com/bokuweb/react-rnd/blob/master/LICENSE)。`peerDependencies` 接受 React / React DOM >=16.3。[README](https://github.com/bokuweb/react-rnd#readme)、[package.json](https://github.com/bokuweb/react-rnd/blob/master/package.json) | 与当前 React 18 的声明范围相容，适合多个浮动窗口复用。当前仅需一个人物入口，继续用 Pointer Events 可避免新增依赖；吸边、点击/拖动阈值、位置记忆和键盘替代仍要按本平台要求实现，不能假设组件自动完成。 |

代码仓库许可证、Cubism SDK 许可、人物/动作素材授权是不同层次。Live2D 官方将“制作模型和动画资产”“使用 SDK 开发”“发布许可”分开说明，因此不能仅凭包装库的 MIT 判断整个角色方案的使用条件。本轮不引入 Cubism。[Live2D 官方说明](https://www.live2d.com/en/sdk/license/)

## 本轮实现建议与验收

以下为结合现有平台的实现判断，不是上述仓库承诺的效果：

1. 生成透明、统一网格的帧图。每帧保持角色比例、头部中心和脚底基线，局部动作包括眨眼、帽桨转动和短暂挥手；不要把角色整体旋转当作人物动作。
2. 帧序列声明每帧区域和时长。眨眼应短、睁眼待机应长，挥手完成后回到待机；不要让整套动作每秒机械地重演。
3. 位置外壳与帧播放器分开。拖动只更新外壳位置，超过阈值才进入拖动；松开后不误触打开对话。停靠边界应计算人物可见区域，避免头部或手臂被屏幕裁掉。
4. 鼠标、触屏和键盘均可移动。只保存非敏感位置偏好，视口变化重新约束位置。打开工作栏和收起人物时沿用现有会话与草稿。
5. 页面不可见时暂停，尊重减少动效偏好，加载失败回退静态小航。动画自然程度须实际逐帧和循环预览，生成出“16格”本身不等于动作合格。

可核验的主要文件：`web/src/components/assistant/XiaohangAssistant.tsx`、`web/src/components/assistant/xiaohang.css`、`web/public/assets/`。本研究不改变模型调用、项目权限、操作草案或任务书生成规则。
