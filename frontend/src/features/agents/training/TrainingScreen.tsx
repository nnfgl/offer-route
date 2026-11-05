import { useEffect, useRef, useState } from 'react';
import { api } from '../../../lib/api';
import type { Session } from '../../../lib/api';
import '../job/job.css';
import './training.css';

type Diagnosis = { id: string; status: string; resume_title: string; job_title: string };
type Gap = { requirement_id: string; skill_id: string; description: string; excerpt: string };
type Task = {
  id: string; title: string; status: string; diagnosis_id: string;
  task_payload: { prompt: string; tables: Record<string, string[]>; diagnosis_evidence: Gap };
};
type Submission = {
  id: string; attempt_no: number; answer_text: string; status: string;
  evaluation_payload: { feedback: string; passed_cases: number; checked_cases: number; evidence: { excerpt: string }[] };
};
const message = (error: unknown) => error instanceof Error ? error.message : '操作失败，请重试';
const status: Record<string, string> = { planned: '待开始', active: '训练中', completed: '已完成', archived: '已归档', pending: '校验中', passed: '通过', failed: '未通过', error: '校验异常' };

export function TrainingScreen({ session, onBack, taskId }: {
  session: Session; onBack: () => void; taskId?: string;
}) {
  const [diagnoses, setDiagnoses] = useState<Diagnosis[]>([]);
  const [diagnosisId, setDiagnosisId] = useState('');
  const [gaps, setGaps] = useState<Gap[]>([]);
  const [requirementId, setRequirementId] = useState('');
  const [history, setHistory] = useState<Task[]>([]);
  const [task, setTask] = useState<Task | null>(null);
  const [submissions, setSubmissions] = useState<Submission[]>([]);
  const [answer, setAnswer] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [gapsLoading, setGapsLoading] = useState(false);
  const [reload, setReload] = useState(0);
  const request = useRef<{ id: string; task: string; answer: string } | null>(null);
  const headers = { 'X-CSRF-Token': session.csrf_token };

  useEffect(() => {
    let active = true;
    setLoading(true); setError('');
    if (taskId) {
      Promise.all([api<Task>(`/training/tasks/${taskId}`), api<Submission[]>(`/training/tasks/${taskId}/submissions`)])
        .then(([latest, attempts]) => {
          if (!active) return;
          setTask(latest); setSubmissions(attempts); setAnswer(attempts.at(-1)?.answer_text ?? '');
        })
        .catch(cause => { if (active) setError(message(cause)); })
        .finally(() => { if (active) setLoading(false); });
      return () => { active = false; };
    }
    Promise.all([api<Diagnosis[]>('/diagnoses'), api<Task[]>('/training/tasks')])
      .then(([records, tasks]) => { if (active) { setDiagnoses(records.filter(item => item.status === 'completed')); setHistory(tasks); } })
      .catch(cause => { if (active) setError(message(cause)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [reload, taskId]);
  useEffect(() => {
    let active = true;
    setGaps([]); setRequirementId(''); setError('');
    if (!diagnosisId) { setGapsLoading(false); return; }
    setGapsLoading(true);
    api<{ gaps: Gap[] }>(`/training/diagnoses/${diagnosisId}/gaps`)
      .then(data => { if (active) setGaps(data.gaps.filter(item => item.skill_id === 'sql' || item.skill_id === 'sql.join_aggregation')); })
      .catch(cause => { if (active) setError(message(cause)); })
      .finally(() => { if (active) setGapsLoading(false); });
    return () => { active = false; };
  }, [diagnosisId]);
  async function create() {
    setBusy(true); setError('');
    try {
      const created = await api<Task>('/training/tasks', { method: 'POST', headers, body: JSON.stringify({ diagnosis_id: diagnosisId, requirement_id: requirementId }) });
      setTask(created); setAnswer(''); setSubmissions([]); request.current = null;
      setHistory(await api<Task[]>('/training/tasks'));
    } catch (cause) { setError(message(cause)); }
    finally { setBusy(false); }
  }
  async function open(item: Task) {
    setBusy(true); setError('');
    try {
      const [latest, attempts] = await Promise.all([api<Task>(`/training/tasks/${item.id}`), api<Submission[]>(`/training/tasks/${item.id}/submissions`)]);
      setTask(latest); setSubmissions(attempts); setAnswer(attempts.at(-1)?.answer_text ?? ''); request.current = null;
    } catch (cause) { setError(message(cause)); }
    finally { setBusy(false); }
  }
  async function submit() {
    if (!task) return;
    setBusy(true); setError('');
    if (!request.current || request.current.task !== task.id || request.current.answer !== answer) {
      request.current = { id: crypto.randomUUID(), task: task.id, answer };
    }
    try {
      await api<Submission>(`/training/tasks/${task.id}/submissions`, { method: 'POST', headers, body: JSON.stringify({ request_id: request.current.id, answer_text: answer }) });
      const [latest, attempts, tasks] = await Promise.all([api<Task>(`/training/tasks/${task.id}`), api<Submission[]>(`/training/tasks/${task.id}/submissions`), taskId ? Promise.resolve([]) : api<Task[]>('/training/tasks')]);
      setTask(latest); setSubmissions(attempts); setHistory(tasks); request.current = null;
    } catch (cause) { setError(message(cause)); }
    finally { setBusy(false); }
  }
  return <div className="workspace"><main className="workspace-main training-screen">
    <button className="quiet-button" onClick={onBack} disabled={busy}>{taskId ? '← 返回求职路线' : '← 返回工作台'}</button>
    <h1>SQL 实战训练</h1><p>选择诊断中的 SQL 缺口，完成真实查询校验。通过本题只证明本题覆盖的能力。</p>
    {error && <div role="alert" className="error-message">{error} <button className="quiet-button" disabled={busy} onClick={() => setReload(value => value + 1)}>重新加载</button></div>}
    {loading ? <p role="status">正在加载训练记录…</p> : <>
      {!taskId && <section><h2>创建训练任务</h2>
        {diagnoses.length === 0 && <p>请先在岗位分析后完成一次能力诊断，再来选择待训练项。</p>}
        <label>选择能力诊断<select value={diagnosisId} disabled={busy} onChange={event => setDiagnosisId(event.target.value)}><option value="">请选择诊断记录</option>{diagnoses.map(item => <option key={item.id} value={item.id}>{item.resume_title} · {item.job_title}</option>)}</select></label>
        {gapsLoading ? <p role="status">正在读取待训练项…</p> : diagnosisId && gaps.length === 0 ? <p>这次诊断没有可训练的 SQL 缺口。当前首期支持 SQL 查询与聚合。</p> : null}
        <label>选择 SQL 待训练项<select value={requirementId} disabled={busy || gapsLoading} onChange={event => setRequirementId(event.target.value)}><option value="">请选择 SQL 缺口</option>{gaps.map(item => <option key={item.requirement_id} value={item.requirement_id}>{item.description}</option>)}</select></label>
        <button className="primary-button" disabled={busy || !requirementId || gapsLoading} onClick={create}>创建 SQL 训练</button>
      </section>}
      {task && <section aria-label="当前训练"><h2>{task.title}</h2><p>任务状态：{status[task.status]}</p><p>{task.task_payload.prompt}</p>
        <blockquote>岗位原文：{task.task_payload.diagnosis_evidence.excerpt}</blockquote>
        {Object.entries(task.task_payload.tables).map(([name, columns]) => <pre key={name}>{name} ({columns.join(', ')})</pre>)}
        <label>SQL 答案<textarea value={answer} disabled={busy || task.status === 'completed' || task.status === 'archived'} rows={8} maxLength={12000} onChange={event => setAnswer(event.target.value)} placeholder="SELECT …" /></label>
        <button className="primary-button" disabled={busy || !answer.trim() || task.status === 'completed' || task.status === 'archived'} onClick={submit}>{busy ? '正在校验…' : '提交 SQL 校验'}</button>
        <h3>提交记录</h3>{submissions.length === 0 && <p>尚未提交答案。</p>}{submissions.map(item => <article key={item.id}><h4>第 {item.attempt_no} 次：{status[item.status]}</h4><p>{item.evaluation_payload.feedback}</p><p>通过用例 {item.evaluation_payload.passed_cases} / {item.evaluation_payload.checked_cases}</p>{item.evaluation_payload.evidence.length > 0 && <p>已保存本题的任务验证证据。</p>}</article>)}
      </section>}
      {!taskId && <section><h2>最近训练</h2>{history.length === 0 && <p>还没有训练任务。</p>}{history.map(item => <button className="quiet-button training-history" disabled={busy} key={item.id} onClick={() => open(item)}>{item.title} · {status[item.status]}</button>)}</section>}
    </>}
  </main></div>;
}
