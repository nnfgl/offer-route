import { useEffect, useState } from 'react';
import { api } from '../../lib/api';
import type { Session, Workspace } from '../../lib/api';
import { InterviewHub } from '../agents/interview/InterviewHub';

const descriptions: Record<string, string> = {
  job: '拆解招聘要求，明确目标岗位需要的能力。',
  diagnosis: '对照项目经历，找到已有优势与待补足的能力。',
  training: '用实际任务积累成果，让每一步训练都有依据。',
  interview: '围绕个人经历展开追问，逐步提升表达与应答。',
};

export function WorkspaceScreen({ session, onLogout }: { session: Session; onLogout: () => void }) {
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [retry, setRetry] = useState(0);
  const [interviewOpen, setInterviewOpen] = useState(false);
  const [voiceRunning, setVoiceRunning] = useState(false);
  useEffect(() => {
    let active = true;
    setError('');
    api<Workspace>('/workspace').then(data => { if (active) setWorkspace(data); })
      .catch(cause => { if (active) setError(cause.message); });
    return () => { active = false; };
  }, [retry]);
  async function logout() {
    setBusy(true); setError('');
    try {
      await api('/auth/logout', { method: 'POST', headers: { 'X-CSRF-Token': session.csrf_token } });
      onLogout();
    } catch (cause) { setError(cause instanceof Error ? cause.message : '退出失败，请重试'); }
    finally { setBusy(false); }
  }
  return <div className="workspace">
    <header className="workspace-header"><a className="brand" href="/"><span className="brand-mark">↗</span> OFFER ROUTE</a><button className="quiet-button" onClick={logout} disabled={busy}>{busy ? '正在退出…' : '退出登录'}</button></header>
    <main className="workspace-main"><span className="eyebrow muted">YOUR CAREER WORKSPACE</span>
      <h1>你好，{session.user.display_name}。</h1><p className="workspace-intro">账户已经准备就绪。接下来，向理想岗位一步步靠近。</p>
      <div className="account-banner"><span className="status-dot" /><div><strong>你的个人工作台</strong><p>{session.user.email}</p></div><span className="account-tag">账户已登录</span></div>
      <div className="section-heading"><h2>你的成长路线</h2><span>四个阶段，一个目标</span></div>
      <p className="planned-note">模拟面试已开放，其他模块正在建设中。</p>
      {error && <div className="error-message" role="alert">{error} <button className="quiet-button" onClick={() => setRetry(value => value + 1)}>重试加载</button></div>}
      {!workspace && !error && <p role="status">正在加载工作台…</p>}
      <div className="module-grid">{workspace?.modules.map((item, index) => <article className="module-card" key={item.id}>
        <span className="module-number">0{index + 1}</span><span className="planned-badge">{item.status === 'available' ? '可以开始' : '即将开放'}</span><h3>{item.title}</h3><p>{descriptions[item.id]}</p>
        {item.id === 'interview' && item.status === 'available' ? <button className="quiet-button module-entry" disabled={voiceRunning} aria-expanded={interviewOpen} onClick={() => setInterviewOpen(value => !value)}>{interviewOpen ? '收起模拟面试' : '进入模拟面试'}</button> : <span className="module-arrow" aria-hidden="true">↗</span>}
      </article>)}</div>
      {interviewOpen && <InterviewHub session={session} onExpired={onLogout} onRunningChange={setVoiceRunning} />}
    </main><footer className="workspace-footer">目标清晰，成长有据。<span>OFFER ROUTE / 2026</span></footer>
  </div>;
}
