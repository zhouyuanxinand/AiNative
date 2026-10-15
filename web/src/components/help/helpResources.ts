export type HelpResourceKind = 'video' | 'manual';

/** 接入正式资料时填写 sourceUrl，使用同源或内网可访问的视频/PDF 地址。 */
export const HELP_RESOURCES = [
  {
    kind: 'video',
    title: '操作视频',
    description: '通过视频了解研制任务书平台的操作流程。',
    path: '/help/video',
    sourceUrl: '',
  },
  {
    kind: 'manual',
    title: '操作手册',
    description: '查阅研制任务书平台的使用说明。',
    path: '/help/manual',
    sourceUrl: '',
  },
] as const;
