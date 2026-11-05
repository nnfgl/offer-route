import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { api, ApiError } from '../../../lib/api';
import type { Session } from '../../../lib/api';
import { TrainingScreen } from '../training/TrainingScreen';
import { InterviewHub } from '../interview/InterviewHub';
import '../training/training.css';
import './career.css';

type RouteSummary = { id: string; title: string; created_at: number };
type Evidence = { source: string; excerpt: string };
type Practice = { session_id: string; skill: string; prompt: string; answer: string | null };
type Route = RouteSummary & {
  revision: number; phase: string; next_stage: string | null;
  attempts: { id: string; stage: string; status: string; message: string }[];
  job_id: string | null; diagnosis_id: string | null; training_id: string | null;
  profile: {
    requirements: { id: string; text: string; quote: string; priority: string }[];
    diagnosis: { summary: string; gaps: { matched_requirement: string }[] } | null;
    verified: (Evidence & { requirement_id: string })[];
    required_count: number; verified_required_count: number;
    interview: { summary: string; mode: 'text' | 'voice'; evidence: Evidence[] } | null;
    practices: Practice[];
    usage: { attempts: number; prompt_tokens: number; completion_tokens: number };
  };
};

const stages: Record<string, string> = { job: '岗位分析', diagnosis: '能力诊断', training: 'SQL 实战训练', interview: '模拟面试', completed: '已完成面试复盘' };
const statuses: Record<string, string> = { running: '执行中', completed: '已完成', skipped: '可跳过', failed: '失败', needs_input: '材料不足' };
const priority: Record<string, string> = { required: '必需', preferred: '加分', unspecified: '未标明' };
const sample = {
  title: 'Python 后端工程师',
  job: '必需：熟悉 Python 开发\n必需：熟悉 SQL 数据库查询与聚合\n加分：了解 Redis 缓存',
  resumeTitle: '模拟简历 · 后端实习',
  resume: '在校园图书项目中负责 Python 接口实现，编写单元测试并维护文档。',
};

export function CareerScreen({ session, onBack, onExpired }: {
  session: Session; onBack: () => void; onExpired: () => void;
}) {
  const [history, setHistory] = useState<RouteSummary[]>([]);
  const [route, setRoute] = useState<Route | null>(null);
  const [materials, setMaterials] = useState({ title: '', job: '', resumeTitle: '', resume: '' });
  const [panel, setPanel] = useState<'training' | 'interview' | null>(null);
  const [voiceRunning, setVoiceRunning] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const requestId = useRef<string | null>(null);
  const headers = { 'X-CSRF-Token': session.csrf_token };

  useEffect(() => {
    let active = true;
    api<RouteSummary[]>('/career-routes').then(items => { if (active) setHistory(items); })
      .catch(cause => {
        if (!active) return;
        if (cause instanceof ApiError && cause.status === 401) onExpired();
        else setError(cause instanceof Error ? cause.message : '历史路线加载失败');
      });
    return () => { active = false; };
  }, [onExpired]);

  async function act(action: () => Promise<void>) {
    setBusy(true); setError('');
    try { await action(); }
    catch (cause) {
      if (cause instanceof ApiError && cause.status === 401) onExpired();
      else setError(cause instanceof Error ? cause.message : '操作失败，请重试');
    } finally { setBusy(false); }
  }

  async function runSteps(start: Route, retry = false) {
    let current = start;
    while (current.next_stage && (retry || current.attempts.at(-1)?.status !== 'failed')) {
      retry = false;
      current = await api<Route>(`/career-routes/${current.id}/advance`, {
        method: 'POST', headers, body: JSON.stringify({ revision: current.revision }),
      });
      setRoute(current);
    }
  }

  async function start(event: FormEvent) {
    event.preventDefault();
    await act(async () => {
      requestId.current ??= crypto.randomUUID();
      const created = await api<Route>('/career-routes', {
        method: 'POST', headers,
        body: JSON.stringify({
          request_id: requestId.current, job: { title: materials.title, source_text: materials.job },
          resume_title: materials.resumeTitle, resume_text: materials.resume,
        }),
      });
      requestId.current = null;
      setRoute(created);
      setHistory(items => [created, ...items.filter(item => item.id !== created.id)].slice(0, 50));
      await runSteps(created);
    });
  }

  function edit(key: keyof typeof sample, value: string) {
    requestId.current = null;
    setMaterials(previous => ({ ...previous, [key]: value }));
  }

  async function refresh(id: string) {
    await act(async () => setRoute(await api<Route>(`/career-routes/${id}`)));
  }

  function closePanel() {
    setPanel(null);
    if (route) void refresh(route.id);
  }

  async function savePractice(event: FormEvent<HTMLFormElement>, practice: Practice) {
    event.preventDefault();
    if (!route) return;
    const answer = new FormData(event.currentTarget).get('answer');
    await act(async () => {
      setRoute(await api<Route>(`/career-routes/${route.id}/practices/${practice.session_id}`, {
        method: 'POST', headers, body: JSON.stringify({ skill: practice.skill, answer }),
      }));
    });
  }

  if (panel === 'training' && route?.training_id) {
    return <TrainingScreen session={session} taskId={route.training_id} onBack={closePanel} />;
  }
  if (panel === 'interview' && route?.job_id && route.diagnosis_id) {
    return <div className="workspace"><main className="workspace-main">
      <button className="quiet-button" disabled={voiceRunning} onClick={closePanel}>← 返回求职路线</button>
      <InterviewHub session={session} onExpired={onExpired} onRunningChange={setVoiceRunning}
        context={{ title: route.title, job_analysis_id: route.job_id, diagnosis_id: route.diagnosis_id }} />
    </main></div>;
  }

  const last = route?.attempts.at(-1);
  return <div className="workspace"><main className="workspace-main training-screen career-screen">
    <button className="quiet-button" disabled={busy} onClick={onBack}>← 返回工作台</button>
    <h1>求职路线</h1>
    <p>从岗位和简历出发，依次完成能力诊断、实战训练与面试复盘。</p>
    {error && <div className="error-message" role="alert">{error}</div>}
    {busy && <p role="status">正在处理路线，请稍候…</p>}
    {!route ? <section>
      <div className="section-heading"><h2>创建求职路线</h2>
        <button className="quiet-button" disabled={busy} onClick={() => { requestId.current = null; setMaterials(sample); }}>填入示例</button>
      </div>
      <form onSubmit={start}>
        <label>目标岗位<input required minLength={2} maxLength={120} disabled={busy} value={materials.title} onChange={event => edit('title', event.target.value)} /></label>
        <label>岗位要求<textarea required minLength={20} maxLength={20000} rows={5} disabled={busy} value={materials.job} onChange={event => edit('job', event.target.value)} /></label>
        <label>简历标题<input required minLength={2} maxLength={120} disabled={busy} value={materials.resumeTitle} onChange={event => edit('resumeTitle', event.target.value)} /></label>
        <label>简历内容<textarea required minLength={20} maxLength={20000} rows={6} disabled={busy} value={materials.resume} onChange={event => edit('resume', event.target.value)} /></label>
        <button className="primary-button" disabled={busy}>创建并运行路线</button>
      </form>
    </section> : <>
      <section aria-label="路线进度">
        <div className="section-heading"><h2>{route.title}</h2>
          <button className="quiet-button" disabled={busy} onClick={() => refresh(route.id)}>刷新进度</button>
        </div>
        <p>当前阶段：{stages[route.phase]}</p>
        <ol>{route.attempts.map(step => <li key={step.id}>{stages[step.stage]} · {statuses[step.status]}{step.message && ` · ${step.message}`}</li>)}</ol>
        {route.next_stage && <button className="primary-button" disabled={busy} onClick={() => act(() => runSteps(route, true))}>{last?.status === 'failed' ? '重试当前步骤' : '继续路线'}</button>}
        {!route.next_stage && last?.status === 'failed' && <p>当前步骤已达到重试上限。可在检查材料或模型配置后创建新路线。</p>}
        {route.training_id && !route.next_stage && <button className="quiet-button" disabled={busy} onClick={() => setPanel('training')}>{route.phase === 'training' ? '完成 SQL 练习' : '查看 SQL 练习'}</button>}
        {(route.phase === 'interview' || route.phase === 'completed') && <button className="primary-button" disabled={busy} onClick={() => setPanel('interview')}>{route.phase === 'completed' ? '打开面试记录' : '进入关联面试'}</button>}
        <button className="quiet-button" disabled={busy} onClick={() => setRoute(null)}>新建路线</button>
      </section>
      <section aria-label="岗位能力档案">
        <h2>岗位能力档案</h2>
        {route.profile.required_count > 0
          ? <p>必需要求的训练验证覆盖 {route.profile.verified_required_count} / {route.profile.required_count}。每条证据对应已通过的练习。</p>
          : <p>当前岗位没有明确标记的必需要求。</p>}
        {route.profile.diagnosis && <p>{route.profile.diagnosis.summary}</p>}
        <ul>{route.profile.requirements.map(item => <li key={item.id}>
          <strong>{item.text}</strong> · {priority[item.priority]} · {route.profile.verified.some(evidence => evidence.requirement_id === item.id) ? '已通过训练验证' : '待训练验证'}
          <blockquote>{item.quote}</blockquote>
        </li>)}</ul>
        {route.profile.verified.map(item => <p key={item.source}>训练证据 · {item.excerpt}</p>)}
        {route.profile.interview && <>
          <h3>{route.profile.interview.mode === 'text' ? '文字面试复盘' : '语音面试复盘'}</h3>
          <p>{route.profile.interview.summary}</p>
          {route.profile.interview.evidence.map((item, index) => <blockquote key={`${item.source}-${index}`}>{item.excerpt}</blockquote>)}
        </>}
        <p>记录的模型用量 · 调用 {route.profile.usage.attempts} 次 · 输入 {route.profile.usage.prompt_tokens} tokens · 输出 {route.profile.usage.completion_tokens} tokens</p>
      </section>
      {route.profile.practices.length > 0 && <section aria-label="面试后练习">
        <h2>面试后练习</h2>
        {route.profile.practices.map(practice => <form key={`${practice.session_id}-${practice.skill}`} onSubmit={event => savePractice(event, practice)}>
          <h3>{practice.skill} · {practice.answer ? '已提交' : '待练习'}</h3><p>{practice.prompt}</p>
          <label>练习回答<textarea name="answer" rows={3} required minLength={10} maxLength={5000} disabled={busy} defaultValue={practice.answer ?? ''} /></label>
          <button className="quiet-button" disabled={busy}>保存练习回答</button>
        </form>)}
      </section>}
    </>}
    <section><h2>历史路线</h2>
      {history.length === 0 && <p>暂无保存的路线。</p>}
      {history.map(item => <button key={item.id} className="quiet-button training-history" disabled={busy} onClick={() => refresh(item.id)}>{item.title} · {new Date(item.created_at * 1000).toLocaleString()}</button>)}
    </section>
  </main></div>;
}
