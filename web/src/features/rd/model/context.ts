import type { RdDetail } from '../api/rd';

export interface RdWorkbenchContext { detail: RdDetail; run: (action: string, payload: Record<string, unknown>, key: string) => Promise<void>; disabled: boolean }
