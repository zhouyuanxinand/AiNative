export type HelpResourceKind = 'video' | 'manual';

/** 侧栏固定入口；已发布资料由管理员维护，通过 API 加载。 */
export const HELP_RESOURCES = [
  {
    kind: 'video',
    title: '操作视频',
    description: '通过视频了解AI Native研发管理平台的操作流程。',
    path: '/help/video',
  },
  {
    kind: 'manual',
    title: '操作手册',
    description: '查阅AI Native研发管理平台的使用说明。',
    path: '/help/manual',
  },
] as const;
