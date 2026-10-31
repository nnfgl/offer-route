import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { api, ApiError } from '../../../lib/api';
import type { Session } from '../../../lib/api';
import './interview.css';

type Report = {
  summary: string;
  evidence: { source: string; excerpt: string }[];
  data: {
    score: number; max_score: number; notice: string;
    dimensions: { name: string; score: number; basis: string; suggestion: string }[];
    training_items: { skill: string; task: string; source_task_id: string; status: 'pending' }[];
  };
};
type Interview = {
  id: string; role: string; experience: string; status: 'active' | 'completed'; created_at: number;
  turns: { question: string; answer: string | null }[]; report: Report | null;
};

export function InterviewScreen({ session, onExpired }: { session: Session; onExpired: () => void }) {
  const [history, setHistory] = useState<Interview[]>([]);
  const [current, setCurrent] = useState<Interview | null>(null);
  const [role, setRole] = useState('Python 后端工程师');
  const [experience, setExperience] = useState('');
  const [answer, setAnswer] = useState('');
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  function fail(cause: unknown) {
    if (cause instanceof ApiError && cause.status === 401) { onExpired(); return; }
    setError(cause instanceof Error ? cause.message : '操作失败，请重试');
  }
  useEffect(() => {
    let active = true;
    setLoading(true); setError('');
    api<Interview[]>('/interviews').then(data => { if (active) setHistory(data); })
      .catch(cause => {
        if (!active) return;
        if (cause instanceof ApiError && cause.status === 401) onExpired();
        else setError(cause instanceof Error ? cause.message : '加载失败，请重试');
      })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [retry, onExpired]);
  function remember(data: Interview) {
    setCurrent(data);
    setHistory(previous => [data, ...previous.filter(item => item.id !== data.id)]
      .sort((a, b) => b.created_at - a.created_at).slice(0, 50));
  }
  async function start(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError('');
    try {
      remember(await api<Interview>('/interviews', {
        method: 'POST', headers: { 'X-CSRF-Token': session.csrf_token },
        body: JSON.stringify({ role, experience }),
      }));
      setAnswer('');
    } catch (cause) { fail(cause); } finally { setBusy(false); }
  }
  async function open(id: string) {
    setBusy(true); setError('');
    try { remember(await api<Interview>(`/interviews/${id}`)); setAnswer(''); }
    catch (cause) { fail(cause); } finally { setBusy(false); }
  }
  async function submit(event: FormEvent) {
    event.preventDefault(); if (!current) return;
    setBusy(true); setError('');
    try {
      remember(await api<Interview>(`/interviews/${current.id}/answers`, {
        method: 'POST', headers: { 'X-CSRF-Token': session.csrf_token },
        body: JSON.stringify({ round: current.turns.length, answer }),
      }));
      setAnswer('');
    } catch (cause) { fail(cause); } finally { setBusy(false); }
  }
  return <section className="interview-panel" aria-labelledby="interview-title">
    <div className="section-heading"><h2 id="interview-title">模拟面试与复盘</h2>
      {current && <button className="quiet-button" disabled={busy} onClick={() => { setCurrent(null); setError(''); }}>返回面试列表</button>}
    </div>
    <p>三轮文字面试，围绕你的经历展开追问。当前使用规则反馈，无需 API Key；建议填写模拟经历。</p>
    {error && <div className="error-message" role="alert">{error}
      {current && <button className="quiet-button" disabled={busy} onClick={() => open(current.id)}>重新加载当前面试</button>}
    </div>}
    {busy && <p role="status">正在保存或加载面试…</p>}
    {!current ? <>
      <form onSubmit={start}>
        <label>目标岗位<input required maxLength={100} value={role} onChange={e => setRole(e.target.value)} /></label>
        <label>项目经历<textarea required minLength={10} maxLength={5000} rows={4} value={experience} onChange={e => setExperience(e.target.value)} placeholder="描述一个项目背景、你的职责与工作内容（至少 10 字）" /></label>
        <button className="primary-button" disabled={busy || !role.trim() || experience.trim().length < 10}>开始模拟面试</button>
      </form>
      <h3>最近的面试记录</h3>
      {loading ? <p role="status">正在加载面试记录…</p> : <>
        <button className="quiet-button" disabled={busy} onClick={() => setRetry(n => n + 1)}>刷新记录</button>
        {!history.length && <p>暂无面试记录。</p>}
        <ul className="interview-history">{history.map(item => <li key={item.id}>
          <button className="quiet-button" disabled={busy} onClick={() => open(item.id)}>
            {item.role} · {item.status === 'completed' ? '查看复盘' : `继续第 ${item.turns.length} 轮`} · {new Date(item.created_at * 1000).toLocaleString()}
          </button>
        </li>)}</ul>
      </>}
    </> : <>
      <h3>{current.role}</h3><p className="interview-experience">经历：{current.experience}</p>
      <ol className="interview-turns">{current.turns.map((turn, index) => <li key={index}>
        <h3>第 {index + 1} / 3 轮</h3><p>{turn.question}</p>
        {turn.answer !== null && <p className="interview-answer">{turn.answer}</p>}
      </li>)}</ol>
      {current.status === 'active' && <form onSubmit={submit}>
        <label>你的回答<textarea required maxLength={5000} rows={6} value={answer} onChange={e => setAnswer(e.target.value)} /></label>
        <button className="primary-button" disabled={busy || !answer.trim()}>{current.turns.length === 3 ? '提交并生成复盘' : '提交回答，继续追问'}</button>
      </form>}
      {current.report && <section aria-label="面试复盘">
        <h3>面试复盘</h3><p>{current.report.summary}</p>
        <p>表达线索得分：{current.report.data.score} / {current.report.data.max_score}</p>
        <p className="planned-note">{current.report.data.notice}</p>
        {current.report.data.dimensions.map(dimension => <article className="interview-feedback" key={dimension.name}>
          <h4>{dimension.name} · {dimension.score ? '发现线索' : '待补充'}</h4>
          <p>依据：{dimension.basis}</p><p>建议：{dimension.suggestion}</p>
        </article>)}
        <h4>待训练项</h4>
        {current.report.data.training_items.length ? <ul>{current.report.data.training_items.map(item => <li key={item.skill}>{item.skill}：{item.task}</li>)}</ul> : <p>本次规则未发现缺失维度，请继续核实技术内容与证据。</p>}
      </section>}
    </>}
  </section>;
}
