# 小航逐帧动画资产

运行方案参考与GitHub仓库对比见 [动画实现调研](2026-10-29-xiaohang-animation-options.md)。

使用内置 `image_gen` 生成，未使用 CLI/API fallback，未重绘为 SVG，未用 Python 或其他工具改写图片像素。原有 `xiaohang.png` 保留为降级图。

最终资产：`web/public/assets/xiaohang-idle-sprite.png`；原生 RGBA PNG，1254 × 1254，透明通道 0–255，4列 × 4行，共16帧。源文件由内置工具保存于 `C:/Users/周园鑫/.codex/generated_images/01a1833d-f3f7-78e1-9904-6ba5884fa36d/exec-6ac1005c-116f-4228-9c8e-3b6c49dea9d3.png`，再原样复制至项目。

注册元数据：`web/public/assets/xiaohang-idle-sprite.json`。每帧 `rect` 是整图绝对像素矩形，`anchor` 是整图绝对坐标的双脚底部中点。它们通过只读透明通道分析得到：选取每格主要连通主体，外围保留4px边缘，以最低10px的双脚范围计算锚点。没有改动图片颜色或透明度。

图生模型未能保证像素级网格注册，直接用机械400%背景切帧会有轻微位移。播放器应依照每帧 `rect` 采样，以 `anchor.x/y` 对齐中心和地面，并按 `anchor.y - rect.y` 统一身高。不要根据挥手时的整幅宽度居中，也不要把整个人物旋转摇摆。

实际动作（0开始）：0–1双手放下待机；2半闭眼；3闭眼；4手开始离开髋部；5手在腰间；6手在胸前；7抬至肩部；8抬至脸旁；9–11腕部小幅挥动；12手开始降低至胸前；13降至腰部；14几乎放下；15恢复双手放下、睁眼的初始姿态。建议待机在0、1、15间长停留，偶发播放2→3→2→1；鼠标关注或定时招呼播放4→…→15，避免无停顿持续快速挥手。

保留了蓝白衣服、白色头盔、蓝色帽桨、大眼睛、手套、靴子与JONHON胸前标记。逐帧存在少量手绘细节和抗锯齿差异，放大时仍可见局部青色边缘；适合约100–140px高的界面人物，不当作精密品牌原画或4K视频素材。螺旋桨只有逐帧角度变化，未声称真实3D旋转。

共生成三版，前两版不被产品引用。首版图形过满并跨越格线；第二版增加透明留白，但抬手中间姿态不足；第三版补上腰/胸/肩中间姿态，选为最终版本。

## 最终生成参数与提示词

- `transparent_background: true`
- `referenced_image_paths`：第二版动作图（保持角色及布局）与项目既有 `xiaohang.png`（身份参考）
- 单个原生sprite atlas；生成后仅复制和读取尺寸/透明度/注册坐标

最终提示词：

> Edit the existing 4x4 animation atlas. KEEP the same 16 Xiaohang mascot figures, blue and white identity, front view, scale, frame centers, propeller, logo, boots and transparent gutters. Change ONLY the animation poses so the action has gentle in-between frames, and clean cyan edge artifacts. This is a production animation atlas on true transparent background, square, EXACT 4 equal columns and 4 equal rows, 16 cells. Never crop a figure. Every complete figure occupies at most 75% of its own cell height; ample transparent space above/below. Maintain the same head center and feet baseline within every cell. No outlines of cells, no numbers, no captions, no floor or shadow. Local body movement only, no floating or whole-body rotation. IMPORTANT frame instructions by reading order: 1) neutral smiling eyes open, both hands DOWN beside hips; 2) same arms DOWN, subtle propeller rotation; 3) same arms DOWN, eyes HALF CLOSED; 4) same arms DOWN, eyes CLOSED in quick relaxed blink; 5) eyes OPEN, right glove starts lifting a little from hip; 6) right elbow bends, right glove at WAIST height, not at face; 7) glove at CHEST height; 8) glove at SHOULDER height; 9) glove next to CHEEK, palm toward viewer; 10) wrist waves gently outward; 11) wrist waves gently inward; 12) wrist returns to center at shoulder, eyes open; 13) glove lowering at CHEST height; 14) glove lowering at WAIST height; 15) glove almost DOWN at hip; 16) exact starting pose both hands fully DOWN, eyes OPEN. The right glove must visibly travel progressively up and then down, not jump straight from hip to cheek. The original white-gloved hands remain small round cartoon gloves, not human realistic fingers. Character chest and boots stay fixed. Use clean opaque shape edges with clean anti-aliasing, no bright cyan spill, no pixel scattering, no neon noise. Keep same flat softly shaded 2D rendering and face as reference, do not redesign.
