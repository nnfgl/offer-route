import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { api } from '../../../lib/api';
import type { Session } from '../../../lib/api';
import type { Capabilities, JobSummary, JobTask, Requirement } from './types';
import './job.css';
const SAMPLE = '任职要求：\n1. 熟悉 Python，掌握 FastAPI 或 Django 至少一种框架。\n2. 掌握 SQL，具备数据库设计和查询优化经验。\n3. 具备 Git 团队协作经验。\n4. 本科及以上学历。\n加分项：\n1. 有 Redis 缓存实践经验优先。\n2. 有开源项目贡献经验优先。\n岗位职责：\n负责业务接口开发和维护。';
const STATUS = { running: '处理中', completed: '已完成', needs_input: '需补充材料', failed: '分析失败' };
const PRIORITIES = [
    { key: 'required', title: '必需条件', description: '招聘方明确要求，优先准备。' },
    { key: 'preferred', title: '优先与加分', description: '帮助形成优势，按个人情况准备。' },
    { key: 'unspecified', title: '待确认要求', description: '原文优先级不明确或条件混合，建议进一步核对。' },
] as const;
const CATEGORIES = { skill: '技能', experience: '经验', education: '学历', other: '其他' };
const message = (error: unknown) => error instanceof Error ? error.message : '操作失败，请重试';
export function JobScreen({ session, onBack }: {
    session: Session;
    onBack: () => void;
}) {
    const [title, setTitle] = useState('');
    const [source, setSource] = useState('');
    const [capabilities, setCapabilities] = useState<Capabilities | null>(null);
    const [history, setHistory] = useState<JobSummary[]>([]);
    const [task, setTask] = useState<JobTask | null>(null);
    const [selected, setSelected] = useState<Requirement | null>(null);
    const [error, setError] = useState('');
    const [busy, setBusy] = useState(false);
    const [loading, setLoading] = useState(true);
    const [reload, setReload] = useState(0);
    const evidenceRef = useRef<HTMLElement>(null);
    useEffect(() => {
        let active = true;
        setLoading(true);
        setError('');
        Promise.all([api<Capabilities>('/jobs/capabilities'), api<JobSummary[]>('/jobs/analyses')])
            .then(([config, records]) => { if (active) {
            setCapabilities(config);
            setHistory(records);
        } })
            .catch(cause => { if (active)
            setError(message(cause)); })
            .finally(() => { if (active)
            setLoading(false); });
        return () => { active = false; };
    }, [reload]);
    async function submit(event: FormEvent<HTMLFormElement>) {
        event.preventDefault();
        if (busy)
            return;
        if (title.trim().length < 2 || source.trim().length < 20) {
            setError('请填写至少 2 个字符的岗位名称和 20 个字符的招聘要求');
            return;
        }
        setBusy(true);
        setError('');
        setSelected(null);
        try {
            const result = await api<JobTask>('/jobs/analyses', {
                method: 'POST', headers: { 'X-CSRF-Token': session.csrf_token },
                body: JSON.stringify({ title: title.trim(), source_text: source.trim() }),
            });
            setTask(result);
            setHistory(records => [result, ...records.filter(item => item.id !== result.id)].slice(0, 20));
        }
        catch (cause) {
            setError(message(cause));
        }
        finally {
            setBusy(false);
        }
    }
    async function openHistory(id: string) {
        setBusy(true);
        setError('');
        setSelected(null);
        try {
            const result = await api<JobTask>(`/jobs/analyses/${id}`);
            setTask(result);
            setTitle(result.title);
            setSource(result.source_text);
        }
        catch (cause) {
            setError(message(cause));
        }
        finally {
            setBusy(false);
        }
    }
    function showEvidence(item: Requirement) {
        setSelected(item);
        window.requestAnimationFrame(() => evidenceRef.current?.scrollIntoView({ block: 'nearest' }));
    }
    const chars = Array.from(task?.source_text ?? '');
    return <div className="workspace">
    <header className="workspace-header">
      <a className="brand" href="/"><span className="brand-mark">↗</span> OFFER ROUTE</a>
      <button className="quiet-button" onClick={onBack}>返回工作台</button>
    </header>
    <main className="job-main">
      <span className="eyebrow muted">01 / UNDERSTAND YOUR TARGET</span>
      <div className="job-heading"><div><h1>看懂岗位，再开始准备。</h1><p>拆解要求，保留依据，让每一步准备都有方向。</p></div>
        {capabilities && <span className="provider-label">{capabilities.provider === 'rules' ? '本地规则提取' : 'DeepSeek 分析'}</span>}
      </div>
      <div className="job-layout">
        <aside className="job-input-panel">
          <div className="job-panel-heading"><h2>目标岗位</h2><button className="quiet-button" disabled={busy || loading} onClick={() => { setTitle('Python 后端开发'); setSource(SAMPLE); }}>填入示例</button></div>
          <form onSubmit={submit}>
            <label>岗位名称<input value={title} onChange={event => setTitle(event.target.value)} required minLength={2} maxLength={120} placeholder="例如：Python 后端开发" disabled={busy}/></label>
            <label>招聘要求<textarea value={source} onChange={event => setSource(event.target.value)} required minLength={20} maxLength={20000} rows={12} placeholder="粘贴招聘原文，尽量包含任职要求、必备条件与加分项。" disabled={busy}/></label>
            <span className="input-count">{source.length.toLocaleString()} / 20,000 字符</span>
            {capabilities?.provider === 'rules' && <p className="job-help">本地提取保留原句，适合结构明确的招聘要求；隐含要求和复杂条件仍需核对。</p>}
            {capabilities && !capabilities.configured && <p role="alert" className="error-message">DeepSeek 尚未配置，请联系项目管理员。</p>}
            <button className="primary-button" type="submit" disabled={busy || loading || !capabilities?.configured}>{busy ? '正在处理…' : '分析岗位要求'}<span aria-hidden="true">↗</span></button>
          </form>
          {error && <p className="error-message job-error" role="alert">{error} <button className="quiet-button" onClick={() => setReload(value => value + 1)} disabled={busy}>重新连接</button></p>}
          <section className="job-history" aria-label="最近分析"><h2>最近分析</h2>
            {loading ? <p role="status">正在加载…</p> : history.length === 0 ? <p>还没有记录，先分析一份岗位要求。</p> : <ul>{history.map(item => <li key={item.id}><button disabled={busy} className={task?.id === item.id ? 'history-active' : ''} onClick={() => openHistory(item.id)}><strong>{item.title}</strong><span>{STATUS[item.status]} · {new Date(item.created_at * 1000).toLocaleDateString('zh-CN')}</span></button></li>)}</ul>}
          </section>
        </aside>
        <section className="job-results" aria-label="岗位分析结果" aria-busy={busy}>
          {busy && <div className="analysis-progress" role="status">正在核对岗位要求与原文依据，请稍候。</div>}
          {!task && !busy && <div className="job-empty"><span aria-hidden="true">↗</span><h2>从一份岗位要求开始</h2><p>分析后，这里会展示必需条件、加分项和可定位的原文证据。</p><p>分析记录仅在你的账户中可见。</p></div>}
          {task && <>
            <div className="result-heading"><div><span className="eyebrow muted">ANALYSIS REPORT</span><h2>{task.title}</h2></div><span className="provider-label">{STATUS[task.status]}</span></div>
            <p className="job-help">本次使用：{task.provider === 'rules' ? '本地规则提取' : 'DeepSeek'}。{task.result?.summary}</p>
            {task.error && <p className="error-message" role="alert">{task.error.message}</p>}
            {task.status === 'needs_input' && <p className="job-notice">尚未识别到明确要求。请补充任职要求、技能、经验或学历条件后重新分析。</p>}
            {task.status === 'completed' && PRIORITIES.map(group => {
                const items = task.requirements.filter(item => item.priority === group.key);
                return <section className="requirement-group" key={group.key}><h3>{group.title}<span>{items.length}</span></h3><p className="job-help">{group.description}</p>
                {items.length === 0 ? <p className="no-requirements">未提取到该类要求。</p> : items.map(item => <article className="requirement-card" key={item.id}><div><span className="requirement-id">{item.id} / {CATEGORIES[item.category]}</span><h4>{item.text}</h4></div><blockquote>{item.quote}</blockquote><button className="evidence-button" onClick={() => showEvidence(item)}>查看原文 · 第 {item.source_line} 行</button></article>)}
              </section>;
            })}
            <section className="source-panel" ref={evidenceRef} aria-label="原文核对"><h3>原文核对</h3><p className="job-help">{selected ? `${selected.id} 的依据已高亮` : '点击任一要求的“查看原文”，核对对应内容。'}</p><pre>{selected ? <>{chars.slice(0, selected.source_start).join('')}<mark>{chars.slice(selected.source_start, selected.source_end).join('')}</mark>{chars.slice(selected.source_end).join('')}</> : task.source_text}</pre></section>
            <section className="workflow-trace"><h3>处理记录</h3><ol>{task.trace.map((step, index) => <li key={index} data-status={step.status}><strong>{step.name}</strong><span>{step.detail}</span></li>)}</ol>
              {task.provider === 'deepseek' && <p className="job-help">调用 {task.usage.attempts} 次 · 服务返回输入 {task.usage.prompt_tokens} / 输出 {task.usage.completion_tokens} tokens；未返回的用量不计入展示。</p>}
            </section>
            <div className="job-notice">能力诊断功能正在建设中。你的岗位分析已保存，可从最近分析中再次查看。</div>
          </>}
        </section>
      </div>
    </main>
  </div>;
}
