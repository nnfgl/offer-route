import { useEffect, useState } from 'react';
import { api, ApiError } from '../../../lib/api';

export type InterviewLinks = { job_analysis_id: string | null; diagnosis_id: string | null };
export type FixedInterviewContext = { title: string; job_analysis_id: string; diagnosis_id: string };
type Choices = {
  shared_storage_ready: boolean; requires_job_link: boolean;
  jobs: { id: string; title: string }[];
  diagnoses: { id: string; created_at: number }[];
};

export function InterviewContextFields({ links, onChange, onExpired }: {
  links: InterviewLinks; onChange: (links: InterviewLinks) => void; onExpired: () => void;
}) {
  const [choices, setChoices] = useState<Choices | null>(null);
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let active = true;
    setError('');
    const query = links.job_analysis_id ? `?job_analysis_id=${encodeURIComponent(links.job_analysis_id)}` : '';
    api<Choices>(`/interviews/contexts${query}`).then(data => { if (active) setChoices(data); })
      .catch(cause => {
        if (!active) return;
        if (cause instanceof ApiError && cause.status === 401) onExpired();
        else setError(cause instanceof Error ? cause.message : '关联记录加载失败');
      });
    return () => { active = false; };
  }, [links.job_analysis_id, retry, onExpired]);
  if (error) return <div className="voice-notice">{error} <button type="button" className="quiet-button" onClick={() => setRetry(value => value + 1)}>重试关联记录</button></div>;
  if (!choices) return <p className="planned-note" role="status">正在加载岗位关联…</p>;
  if (!choices.shared_storage_ready) return <p className="planned-note">岗位和诊断关联暂未开放，当前可先独立练习。</p>;
  return <>
    <label>关联岗位分析{choices.requires_job_link ? '（必选）' : '（可选）'}<select aria-label={`关联岗位分析${choices.requires_job_link ? '（必选）' : '（可选）'}`} required={choices.requires_job_link} value={links.job_analysis_id ?? ''} onChange={event => onChange({ job_analysis_id: event.target.value || null, diagnosis_id: null })}>
      <option value="">{choices.requires_job_link ? '请选择已完成的岗位分析' : '独立练习，不关联岗位分析'}</option>
      {choices.jobs.map(job => <option key={job.id} value={job.id}>{job.title}</option>)}
    </select></label>
    {!choices.jobs.length && <p className="planned-note">当前没有已完成的岗位分析，请先完成岗位分析。</p>}
    {links.job_analysis_id && <label>关联能力诊断（可选）<select aria-label="关联能力诊断（可选）" value={links.diagnosis_id ?? ''} onChange={event => onChange({ ...links, diagnosis_id: event.target.value || null })}>
      <option value="">仅使用岗位要求和项目经历</option>
      {choices.diagnoses.map(diagnosis => <option key={diagnosis.id} value={diagnosis.id}>{new Date(diagnosis.created_at * 1000).toLocaleString()} · {diagnosis.id.slice(0, 8)}</option>)}
    </select></label>}
  </>;
}
