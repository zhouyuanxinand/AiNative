import type { RdDetail } from '../api/rd';

export const memberName = (detail: RdDetail, id: string) => { const member = detail.members.find(item => item.user_id === id); return member?.display_name || id; };
export const taskName = (detail: RdDetail, id: string) => detail.tasks.find(item => item.id === id)?.title || id;
export const baselineName = (detail: RdDetail, id: string) => { const baseline = detail.baselines.find(item => item.id === id); return baseline ? `B${baseline.number}` : id; };
