import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { api } from '../../../lib/api';
import type { Session } from '../../../lib/api';
import type { JobSummary } from '../job/types';
import type {
    DiagnosisCapabilities,
    DiagnosisDetail,
    DiagnosisItem,
    DiagnosisStatus,
    DiagnosisSummary,
    EvidenceType,
} from './types';
import '../job/job.css';
import './diagnosis.css';

const SAMPLE = '张三 · 后端开发工程师\n\n熟悉 Python 与 FastAPI，参与开源项目 offer-route（github.com/offer-route），优化接口 QPS 提升 30%。\n掌握 SQL 与 Redis 缓存，具备数据库设计与查询优化经验。';
const STATUS: Record<DiagnosisStatus, string> = {
    running: '处理中',
    completed: '已完成',
    needs_input: '需补充材料',
    failed: '诊断失败',
};
const EVIDENCE: Record<EvidenceType, string> = {
    self_claimed: '用户自述',
    portfolio_supported: '作品支持',
    task_verified: '任务验证',
};
const message = (error: unknown) => (error instanceof Error ? error.message : '操作失败，请重试');

function ItemCard({ item, pending = false }: { item: DiagnosisItem; pending?: boolean }) {
    const percent = Math.round(item.confidence_score * 100);
    return (
        <article className={`diagnosis-card${pending ? ' diagnosis-pending' : ''}`}>
            <div className="diagnosis-card-head">
                <span className="requirement-id">{item.requirement_id ?? '要求'}</span>
                {pending && <span className="pending-badge">待人工确认</span>}
                {item.evidence_type && (
                    <span className={`evidence-badge evidence-${item.evidence_type}`}>
                        {EVIDENCE[item.evidence_type]}
                    </span>
                )}
                <span className="confidence">{percent}% 置信</span>
            </div>
            <h4>{item.matched_requirement}</h4>
            <p className="diagnosis-claim">{item.claim_content}</p>
            {item.evidence_excerpt && <blockquote>{item.evidence_excerpt}</blockquote>}
        </article>
    );
}

export function DiagnosisScreen({ session, onBack }: { session: Session; onBack: () => void }) {
    const [title, setTitle] = useState('');
    const [source, setSource] = useState('');
    const [jobId, setJobId] = useState('');
    const [analyses, setAnalyses] = useState<JobSummary[]>([]);
    const [capabilities, setCapabilities] = useState<DiagnosisCapabilities | null>(null);
    const [history, setHistory] = useState<DiagnosisSummary[]>([]);
    const [task, setTask] = useState<DiagnosisDetail | null>(null);
    const [context, setContext] = useState<{ resumeTitle: string; jobTitle: string } | null>(null);
    const [error, setError] = useState('');
    const [busy, setBusy] = useState(false);
    const [loading, setLoading] = useState(true);
    const [reload, setReload] = useState(0);

    useEffect(() => {
        let active = true;
        setLoading(true);
        setError('');
        Promise.all([
            api<DiagnosisCapabilities>('/diagnoses/capabilities'),
            api<DiagnosisSummary[]>('/diagnoses'),
            api<JobSummary[]>('/jobs/analyses'),
        ])
            .then(([config, records, jobs]) => {
                if (active) {
                    setCapabilities(config);
                    setHistory(records);
                    setAnalyses(jobs.filter((item) => item.status === 'completed'));
                }
            })
            .catch((cause) => { if (active) setError(message(cause)); })
            .finally(() => { if (active) setLoading(false); });
        return () => { active = false; };
    }, [reload]);

    async function submit(event: FormEvent<HTMLFormElement>) {
        event.preventDefault();
        if (busy) return;
        if (!jobId) {
            setError('请先选择一份已完成的岗位分析');
            return;
        }
        if (title.trim().length < 2 || source.trim().length < 20) {
            setError('请填写至少 2 个字符的简历标题和 20 个字符的简历内容');
            return;
        }
        setBusy(true);
        setError('');
        try {
            const resumeTitle = title.trim();
            const result = await api<DiagnosisDetail>('/diagnoses', {
                method: 'POST',
                headers: { 'X-CSRF-Token': session.csrf_token },
                body: JSON.stringify({
                    job_analysis_id: jobId,
                    title: resumeTitle,
                    source_text: source.trim(),
                }),
            });
            const jobTitle = analyses.find((item) => item.id === jobId)?.title ?? '岗位分析';
            setTask(result);
            setContext({ resumeTitle, jobTitle });
            setHistory((records) => [
                {
                    id: result.id,
                    resume_id: result.resume_id,
                    job_analysis_id: result.job_analysis_id,
                    status: result.status,
                    resume_title: resumeTitle,
                    job_title: jobTitle,
                    summary: result.result.summary,
                    created_at: result.created_at,
                },
                ...records.filter((item) => item.id !== result.id),
            ].slice(0, 20));
        } catch (cause) {
            setError(message(cause));
        } finally {
            setBusy(false);
        }
    }

    async function openHistory(id: string, resumeTitle: string, jobTitle: string) {
        setBusy(true);
        setError('');
        try {
            const result = await api<DiagnosisDetail>(`/diagnoses/${id}`);
            setTask(result);
            setContext({ resumeTitle, jobTitle });
        } catch (cause) {
            setError(message(cause));
        } finally {
            setBusy(false);
        }
    }

    function fillSample() {
        setTitle('张三 · 后端开发');
        setSource(SAMPLE);
    }

    return (
        <div className="workspace">
            <header className="workspace-header">
                <a className="brand" href="/"><span className="brand-mark">↗</span> OFFER ROUTE</a>
                <button className="quiet-button" onClick={onBack}>返回工作台</button>
            </header>
            <main className="job-main">
                <span className="eyebrow muted">02 / KNOW YOUR GAPS</span>
                <div className="job-heading">
                    <div>
                        <h1>对照岗位，看清自己。</h1>
                        <p>让每一项优势与能力缺口，都有简历证据可依。</p>
                    </div>
                    {capabilities && (
                        <span className="provider-label">
                            {capabilities.provider === 'rules' ? '本地规则诊断' : 'DeepSeek 诊断'}
                        </span>
                    )}
                </div>
                <div className="job-layout">
                    <aside className="job-input-panel">
                        <div className="job-panel-heading">
                            <h2>诊断材料</h2>
                            <button className="quiet-button" disabled={busy || loading} onClick={fillSample}>填入示例</button>
                        </div>
                        <form onSubmit={submit}>
                            <label>对比的岗位分析
                                <select value={jobId} onChange={(event) => setJobId(event.target.value)} required disabled={busy || loading}>
                                    <option value="">{analyses.length ? '选择一份已完成的岗位分析' : '暂无已完成的岗位分析'}</option>
                                    {analyses.map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}
                                </select>
                            </label>
                            <label>简历标题
                                <input value={title} onChange={(event) => setTitle(event.target.value)} required minLength={2} maxLength={120} placeholder="例如：张三 · 后端开发" disabled={busy} />
                            </label>
                            <label>简历内容
                                <textarea value={source} onChange={(event) => setSource(event.target.value)} required minLength={20} maxLength={20000} rows={12} placeholder="粘贴简历原文，尽量包含项目经历、产出与量化结果。" disabled={busy} />
                            </label>
                            <span className="input-count">{source.length.toLocaleString()} / 20,000 字符</span>
                            {capabilities?.provider === 'rules' && <p className="job-help">本地诊断按关键词命中与证据信号给出初判（自述 / 作品 / 任务验证），复杂能力仍需人工核对。</p>}
                            {capabilities && !capabilities.configured && <p role="alert" className="error-message">DeepSeek 尚未配置，请联系项目管理员。</p>}
                            <button className="primary-button" type="submit" disabled={busy || loading || !capabilities?.configured || analyses.length === 0}>
                                {busy ? '正在诊断…' : '开始能力诊断'}<span aria-hidden="true">↗</span>
                            </button>
                        </form>
                        {error && (
                            <p className="error-message job-error" role="alert">
                                {error} <button className="quiet-button" onClick={() => setReload((value) => value + 1)} disabled={busy}>重新连接</button>
                            </p>
                        )}
                        <section className="job-history" aria-label="最近诊断">
                            <h2>最近诊断</h2>
                            {loading ? <p role="status">正在加载…</p> : history.length === 0 ? <p>还没有诊断记录，先对照一份岗位分析开始。</p> : (
                                <ul>
                                    {history.map((item) => (
                                        <li key={item.id}>
                                            <button disabled={busy} className={task?.id === item.id ? 'history-active' : ''} onClick={() => openHistory(item.id, item.resume_title, item.job_title)}>
                                                <strong>{item.resume_title}</strong>
                                                <span>{item.job_title} · {STATUS[item.status]} · {new Date(item.created_at * 1000).toLocaleDateString('zh-CN')}</span>
                                            </button>
                                        </li>
                                    ))}
                                </ul>
                            )}
                        </section>
                    </aside>
                    <section className="job-results" aria-label="能力诊断结果" aria-busy={busy}>
                        {busy && <div className="analysis-progress" role="status">正在对照岗位要求与简历证据，请稍候。</div>}
                        {!task && !busy && (
                            <div className="job-empty">
                                <span aria-hidden="true">↗</span>
                                <h2>从一份岗位分析开始</h2>
                                <p>先完成岗位分析，再粘贴简历，这里会给出优势、能力缺口与待验证项。</p>
                                <p>所有判断都会关联简历原文与岗位要求，诊断记录仅你的账户可见。</p>
                            </div>
                        )}
                        {task && (
                            <>
                                <div className="result-heading">
                                    <div>
                                        <span className="eyebrow muted">DIAGNOSIS REPORT</span>
                                        <h2>{context?.resumeTitle ?? '能力诊断'}</h2>
                                        {context && <p className="job-help">对照岗位：{context.jobTitle}</p>}
                                    </div>
                                    <span className="provider-label">{STATUS[task.status]}</span>
                                </div>
                                {task.status === 'failed' && <p className="error-message" role="alert">{task.result.summary}</p>}
                                {task.status === 'running' && <div className="analysis-progress" role="status">诊断处理中…</div>}
                                {task.status === 'needs_input' && <p className="job-notice">未从这份简历中识别到可诊断的信息，请补充更具体的项目经历与技能描述。</p>}
                                {(task.status === 'completed' || task.status === 'needs_input') && (
                                    <>
                                        <p className="job-help">{task.result.summary}</p>
                                        <section className="diagnosis-group">
                                            <h3>优势 <span>{task.result.strengths.length}</span></h3>
                                            {task.result.strengths.length === 0 ? <p className="no-requirements">暂无有把握的优势。</p> : task.result.strengths.map((item) => <ItemCard key={item.requirement_id ?? item.matched_requirement} item={item} />)}
                                        </section>
                                        <section className="diagnosis-group">
                                            <h3>能力缺口 <span>{task.result.gaps.length}</span></h3>
                                            {task.result.gaps.length === 0 ? <p className="no-requirements">未识别到明确的能力缺口。</p> : task.result.gaps.map((item) => <ItemCard key={item.requirement_id ?? item.matched_requirement} item={item} />)}
                                        </section>
                                        <section className="diagnosis-group">
                                            <h3>待人工确认 <span>{task.result.pending_verification.length}</span></h3>
                                            {task.result.pending_verification.length === 0 ? <p className="no-requirements">暂无待确认项。</p> : task.result.pending_verification.map((item) => <ItemCard key={item.requirement_id ?? item.matched_requirement} item={item} pending />)}
                                        </section>
                                    </>
                                )}
                            </>
                        )}
                    </section>
                </div>
            </main>
        </div>
    );
}