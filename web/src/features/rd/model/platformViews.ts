export type PlatformView = 'overview' | 'requirements' | 'tasks' | 'artifacts' | 'approvals';
export const platformViews = {
  overview: { title: '我的工作', path: '/', description: '按项目分工办理当前工作，核对路线、固定输入与交接责任。' },
  requirements: { title: '需求中心', path: '/requirements', description: '汇总项目需求、澄清状态与验收依据，所有修订回到项目基线管理。' },
  tasks: { title: '研发任务', path: '/tasks', description: '按执行人与审核人分工，跟踪当前基线下的研发任务。' },
  artifacts: { title: '成果中心', path: '/artifacts', description: '查看固定成果版本、自动检查结果与工程批准记录。' },
  approvals: { title: '审签待办', path: '/approvals', description: '核对固定文件和当前需求基线，由指定的独立审核人作出决定。' },
};
