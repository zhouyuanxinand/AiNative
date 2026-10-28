/** In-memory project intent. Identity and all permissions are verified again by the server. */
interface GenerationContext { project_id: string; task_id: string; baseline_id: string; confirmed: boolean }
let context: GenerationContext | null = null;
const intents = new Map<string, string>();

export function readRdContext(search: string): { project_id: string; task_id: string } | null {
  const query = new URLSearchParams(search);
  const project_id = query.get('rd_project'); const task_id = query.get('rd_task');
  if (!project_id && !task_id) return null;
  if (!project_id || !task_id || project_id.length > 100 || task_id.length > 100) throw new Error('项目任务上下文不完整，请从研发项目重新进入。');
  return { project_id, task_id };
}

export function setRdGenerationContext(value: GenerationContext | null) { context = value; }

export function runningJobRecord(jid: string, search: string) {
  return { jid, ts: Date.now(), rd_context: readRdContext(search) };
}

export function runningJobMatchesContext(saved: { rd_context?: { project_id?: string; task_id?: string } | null }, search: string): boolean {
  const requested = readRdContext(search);
  if (!requested) return !saved.rd_context;
  return saved.rd_context?.project_id === requested.project_id && saved.rd_context?.task_id === requested.task_id;
}

export function prepareRdGeneration(form: FormData, search: string): string | undefined {
  const requested = readRdContext(search);
  if (!requested) return undefined;
  if (!context) throw new Error('请等待项目任务读取完成，或返回项目检查任务状态。');
  if (context.project_id !== requested.project_id || context.task_id !== requested.task_id) throw new Error('项目任务上下文不一致，请重新进入。');
  if (!context.confirmed) throw new Error('请先核对上传资料与当前需求基线，并勾选确认。');
  form.set('rd_project', context.project_id); form.set('rd_task', context.task_id);
  form.set('rd_baseline_id', context.baseline_id); form.set('rd_inputs_confirmed', 'true');
  const fields = Array.from(form.entries(), ([key, value]) => [key, typeof value === 'string' ? value : `${value.name}:${value.size}:${value.lastModified}`]);
  fields.sort(([a], [b]) => a.localeCompare(b));
  const fingerprint = JSON.stringify(fields);
  let key = intents.get(fingerprint);
  if (!key) {
    const bytes = globalThis.crypto.getRandomValues(new Uint8Array(16));
    key = `rd-generation-${Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('')}`;
    intents.set(fingerprint, key);
  }
  return key;
}

export function completeRdGeneration(key?: string) {
  if (key) for (const [fingerprint, value] of intents) if (value === key) intents.delete(fingerprint);
}
