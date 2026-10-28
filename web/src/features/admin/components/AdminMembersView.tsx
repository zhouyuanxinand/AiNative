import { useEffect, useRef, useState, type FormEvent } from 'react';
import { addAdminMember, getAdminMembers, removeAdminMember, type AdminMember, type AdminMembers } from '../../../shared/auth/adminAccess';
import { FeedbackConfirmDialog } from '../../../shared/ui/FeedbackDialog';
import { feedbackTime } from '../../feedback/components/feedbackPresentation';
import { useAdminUnsavedChanges } from './adminDrafts';

export function AdminMembersView({ active, canManage }: { active: boolean; canManage: boolean }) {
  const [data, setData] = useState<AdminMembers | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [draft, setDraft] = useState('');
  const [adding, setAdding] = useState(false);
  const [formError, setFormError] = useState('');
  const [notice, setNotice] = useState('');
  const [remove, setRemove] = useState<AdminMember | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState('');
  const [revision, setRevision] = useState(0);
  const alive = useRef(true);
  const mutation = useRef<AbortController>();
  const field = useRef<HTMLInputElement>(null);
  const listTitle = useRef<HTMLHeadingElement>(null);
  const pending = useRef(false);
  useAdminUnsavedChanges(canManage && Boolean(draft.trim()));

  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; mutation.current?.abort(); };
  }, []);

  useEffect(() => {
    if (!active) return;
    const controller = new AbortController();
    setLoading(true); setError('');
    getAdminMembers(controller.signal).then(result => {
      if (!controller.signal.aborted) setData(result);
    }).catch(cause => {
      if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : '管理员名单读取失败，请重试。');
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [active, revision]);

  async function add(event: FormEvent) {
    event.preventDefault();
    if (pending.current || !canManage) return;
    const username = draft.trim();
    if (!/^[A-Za-z0-9_.@-]{1,128}$/.test(username)) {
      setFormError('请填写 OA 登录账号，限 1–128 位字母、数字或 _ . @ -，不要填写中文姓名。');
      field.current?.focus(); return;
    }
    pending.current = true; setAdding(true); setFormError(''); setNotice('');
    const controller = new AbortController(); mutation.current = controller;
    try {
      const result = await addAdminMember(username, controller.signal);
      if (!alive.current || controller.signal.aborted) return;
      setDraft(''); setNotice(`已授权 ${result.member.username}。该账号完成 OA 登录后即可进入管理员页面。`);
      setRevision(value => value + 1); field.current?.focus();
    } catch (cause) {
      if (alive.current && !controller.signal.aborted) setFormError(cause instanceof Error ? cause.message : '添加管理员失败，请重试。');
    } finally { if (alive.current) { pending.current = false; setAdding(false); } }
  }

  async function confirmRemove() {
    if (!remove || pending.current || !canManage || remove.is_owner) return;
    const username = remove.username;
    pending.current = true; setDeleting(true); setDeleteError(''); setNotice('');
    const controller = new AbortController(); mutation.current = controller;
    try {
      await removeAdminMember(username, controller.signal);
      if (!alive.current || controller.signal.aborted) return;
      setRemove(null); setNotice(`已移除 ${username} 的管理员权限。`);
      setRevision(value => value + 1); requestAnimationFrame(() => listTitle.current?.focus());
    } catch (cause) {
      if (alive.current && !controller.signal.aborted) setDeleteError(cause instanceof Error ? cause.message : '移除管理员失败，请重试。');
    } finally { if (alive.current) { pending.current = false; setDeleting(false); } }
  }

  return <div className="admin-members">
    {canManage ? <form className="admin-member-form" noValidate onSubmit={event => void add(event)} aria-label="添加管理员">
      <div><label htmlFor="admin-member-username">OA 登录账号</label>
        <input ref={field} id="admin-member-username" value={draft} maxLength={128} autoComplete="off" autoCapitalize="none" spellCheck={false}
          placeholder="例如：zhangsan" disabled={adding} required aria-invalid={Boolean(formError)}
          aria-describedby={`admin-member-hint${formError ? ' admin-member-error' : ''}`} onChange={event => { setDraft(event.target.value); setFormError(''); }} />
      </div>
      <button type="submit" className="feedback-button primary" disabled={adding || deleting}>{adding ? '正在授权…' : '添加管理员'}</button>
      <p id="admin-member-hint" className="admin-member-hint">填写已有 OA 登录账号，不是中文显示姓名；此操作只授予管理权限，不创建 OA 账号或密码。</p>
      {formError && <p id="admin-member-error" role="alert" className="feedback-error">{formError}</p>}
    </form> : <p className="admin-member-readonly">当前名单只读。仅 wangxue 可以添加或移除管理员。</p>}
    {notice && <p role="status" className="feedback-notice">{notice}</p>}
    <div className="admin-member-list-heading"><div><h3 ref={listTitle} tabIndex={-1}>已授权账号</h3><p>名单中的账号仍需通过 OA 身份验证。</p></div>
      <button type="button" className="feedback-button" disabled={loading} onClick={() => setRevision(value => value + 1)}>刷新名单</button></div>
    {error && <div className="feedback-error" role="alert"><p>{error}</p><button type="button" className="feedback-link" onClick={() => setRevision(value => value + 1)}>重试加载名单</button></div>}
    {loading ? <p className="feedback-empty" role="status">正在读取管理员名单…</p> : !error && data && <>
      <div className="admin-member-table-scroll"><table className="admin-member-table" aria-label="管理员权限名单"><thead><tr>
        <th scope="col">OA 登录账号</th><th scope="col">权限</th><th scope="col">授权时间（北京时间）</th><th scope="col">授权人</th>{canManage && <th scope="col">操作</th>}
      </tr></thead><tbody>{data.items.map(member => <tr key={member.username}>
        <td data-label="OA 登录账号"><strong>{member.username}</strong></td><td data-label="权限">{member.is_owner ? '主管理员' : '管理员'}</td>
        <td data-label="授权时间"><time dateTime={member.created_at}>{feedbackTime(member.created_at)}</time></td><td data-label="授权人">{member.created_by || '系统初始化'}</td>
        {canManage && <td data-label="操作">{member.is_owner ? <span className="admin-member-protected">初始账号，不可移除</span> :
          <button type="button" className="feedback-link danger-text" disabled={adding || deleting} aria-label={`移除管理员 ${member.username}`} onClick={() => { setRemove(member); setDeleteError(''); }}>移除</button>}</td>}
      </tr>)}</tbody></table></div>
      <p className="admin-member-count">共 {data.items.length} 个已授权账号</p>
    </>}
    {remove && <FeedbackConfirmDialog title="移除管理员权限" confirm="确认移除" danger visible={active} pending={deleting} error={deleteError}
      onCancel={() => setRemove(null)} onConfirm={() => void confirmRemove()}>
      <p>确认移除 {remove.username} 的管理员权限？该账号将无法继续访问用户反馈、运行日志和管理员名单。</p>
    </FeedbackConfirmDialog>}
  </div>;
}
