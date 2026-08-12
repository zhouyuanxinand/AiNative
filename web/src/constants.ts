/** localStorage 键名与 UI 常量——与原 SPA 完全一致，不修改任何键名。 */

export const DRAFT_KEY = 'jtb.controlled.ui.draft.v1';
export const AUTO_DRAFT_KEY = 'jtb.controlled.ui.autodraft.v1';
export const RUNNING_JOB_KEY = 'jtb.controlled.ui.runningJob.v1';
export const UI_MODE_KEY = 'jtb.controlled.ui.mode.v1';
export const PANEL_WIDTH_KEY = 'jtb.controlled.ui.panelWidths.v1';

export const STEP_KEYWORDS: Record<number, string[]> = {
  2: ['规则填充', '模板扫描', '封面'],
  3: ['LLM', '语义补填', '🤖'],
  4: ['后处理', '红字', '高亮', '图片媒体'],
  5: ['QA', '门禁', '覆盖率'],
  6: ['✅ 完成'],
};

export const PANEL_WIDTH_LIMITS = {
  left: { min: 220, max: 320 },
  right: { min: 360, max: 560 },
} as const;

export type PanelKind = 'left' | 'right';
export type UIMode = 'compact' | 'expert';
export type ReviewTab = 'result' | 'history' | 'status';
export type ManagementKind = 'rules' | 'templates';
export type WorkspaceView = 'generate' | 'rules' | 'templates';

/** 6 步流程的标签文本。 */
export const FLOW_STEPS = ['业务选择', '文件预检', '语义路由', '模板装配', '质量门禁', '交付完成'] as const;
