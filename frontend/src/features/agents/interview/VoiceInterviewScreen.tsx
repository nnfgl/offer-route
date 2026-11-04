import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { api, ApiError } from '../../../lib/api';
import type { Session } from '../../../lib/api';
import { VoiceConnection } from './voiceConnection';
import type { VoiceConfig, VoiceConnect, VoiceInterview, VoiceMessage } from './voiceTypes';
import './interview.css';
import { InterviewContextFields } from './InterviewContextFields';
import type { InterviewLinks } from './InterviewContextFields';

export function VoiceInterviewScreen({ session, onExpired, onRunningChange }: {
  session: Session; onExpired: () => void; onRunningChange: (running: boolean) => void;
}) {
  const [config, setConfig] = useState<VoiceConfig | null>(null);
  const [history, setHistory] = useState<VoiceInterview[]>([]);
  const [current, setCurrent] = useState<VoiceInterview | null>(null);
  const [role, setRole] = useState('Python 后端工程师');
  const [experience, setExperience] = useState('');
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [muted, setMuted] = useState(false);
  const [voiceState, setVoiceState] = useState('尚未开始');
  const [error, setError] = useState('');
  const [needsIncomplete, setNeedsIncomplete] = useState(false);
  const [retry, setRetry] = useState(0);
  const [links, setLinks] = useState<InterviewLinks>({ job_analysis_id: null, diagnosis_id: null });
  const connection = useRef<VoiceConnection | null>(null);
  const saveQueue = useRef<Promise<unknown>>(Promise.resolve());
  const alive = useRef(true);
  const timer = useRef<number | undefined>(undefined);
  const finishRef = useRef<(acceptIncomplete?: boolean) => Promise<void>>(async () => {});
  const headers = { 'X-CSRF-Token': session.csrf_token };
  function fail(cause: unknown) {
    if (!alive.current) return;
    if (cause instanceof ApiError && cause.status === 401) { onExpired(); return; }
    setError(cause instanceof DOMException && cause.name === 'NotAllowedError'
      ? '麦克风权限未获得，请在浏览器中允许使用麦克风后重试'
      : cause instanceof Error ? cause.message : '语音操作失败，请重试');
  }
  function remember(record: VoiceInterview) {
    setCurrent(record);
    setHistory(previous => [record, ...previous.filter(item => item.id !== record.id)].slice(0, 50));
  }
  function stopMedia() {
    window.clearTimeout(timer.current); connection.current?.close();
    setRunning(false); onRunningChange(false);
  }
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false; window.clearTimeout(timer.current);
      connection.current?.close(); onRunningChange(false);
    };
  }, [onRunningChange]);
  useEffect(() => {
    let active = true;
    setLoading(true); setError('');
    Promise.all([api<VoiceConfig>('/voice-interviews/config'), api<VoiceInterview[]>('/voice-interviews')])
      .then(([settings, records]) => { if (active) { setConfig(settings); setHistory(records); } })
      .catch(cause => { if (active) fail(cause); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [retry, onExpired]);
  useEffect(() => {
    if (!current || current.report_status !== 'processing') return;
    const id = current.id;
    let active = true;
    let poll: number;
    async function refresh() {
      try {
        const record = await api<VoiceInterview>(`/voice-interviews/${id}`);
        if (!active) return;
        remember(record);
        if (record.report_status === 'processing') poll = window.setTimeout(refresh, 2000);
      } catch (cause) { if (active) fail(cause); }
    }
    poll = window.setTimeout(refresh, 1000);
    return () => { active = false; window.clearTimeout(poll); };
  }, [current?.id, current?.report_status]);

  async function connect(record: VoiceInterview) {
    connection.current?.close();
    const call = new VoiceConnection({
      onState: state => { if (alive.current) setVoiceState(state); },
      onMessages: messages => { if (alive.current) setCurrent(previous => previous?.id === record.id ? { ...previous, messages } : previous); },
      onFinal: message => persist(record.id, [message]),
      onError: message => { if (alive.current) setError(message); },
    });
    connection.current = call;
    setRunning(true); onRunningChange(true); setMuted(false);
    await call.start(async offer => {
      const result = await api<VoiceConnect>(`/voice-interviews/${record.id}/connect`, {
        method: 'POST', headers, body: JSON.stringify({ offer_sdp: offer }),
      });
      if (alive.current) setCurrent(previous => previous?.id === record.id ? { ...previous, status: 'live' } : previous);
      return result;
    });
    if (!alive.current) { call.close(); return; }
    timer.current = window.setTimeout(() => { void finishRef.current(); }, (config?.max_minutes ?? 15) * 60000);
  }
  function persist(id: string, messages: VoiceMessage[]) {
    saveQueue.current = saveQueue.current.catch(() => undefined).then(() =>
      api<VoiceInterview>(`/voice-interviews/${id}/messages`, {
        method: 'POST', headers, body: JSON.stringify({ messages }),
      }),
    );
    void saveQueue.current.catch(cause => { if (alive.current) fail(cause); });
  }
  async function start(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError(''); setNeedsIncomplete(false);
    try {
      const record = await api<VoiceInterview>('/voice-interviews', {
        method: 'POST', headers, body: JSON.stringify({ role, experience, ...links }),
      });
      remember(record); await connect(record);
    } catch (cause) { stopMedia(); fail(cause); } finally { if (alive.current) setBusy(false); }
  }
  async function finish(acceptIncomplete = false) {
    if (!current || busy) return;
    setBusy(true); setError('');
    window.clearTimeout(timer.current);
    setMuted(true);
    try {
      let messages = current.messages;
      if (connection.current) messages = await connection.current.drain(acceptIncomplete);
      // Freeze the media/transcript before the final snapshot and end request.
      stopMedia();
      await saveQueue.current.catch(() => undefined);
      let record = await api<VoiceInterview>(`/voice-interviews/${current.id}`);
      if (record.status !== 'ended') {
        if (messages.length && record.status === 'live') {
          try {
            record = await api<VoiceInterview>(`/voice-interviews/${current.id}/messages`, {
              method: 'POST', headers, body: JSON.stringify({ messages }),
            });
          } catch (cause) {
            if (!(acceptIncomplete && cause instanceof ApiError && [409, 422].includes(cause.status))) throw cause;
            // Explicit incomplete confirmation permits ending with the already saved snapshot.
          }
        }
        record = await api<VoiceInterview>(`/voice-interviews/${current.id}/end`, {
          method: 'POST', headers, body: JSON.stringify({ message_count: record.messages.length, accept_incomplete: acceptIncomplete }),
        });
      }
      remember(record); setVoiceState('面试已结束'); setNeedsIncomplete(false);
    } catch (cause) {
      if (cause instanceof Error && /转写尚未|转写未|转写不完整|上限|不能被覆盖/.test(cause.message)) setNeedsIncomplete(true);
      fail(cause);
    } finally { if (alive.current) setBusy(false); }
  }
  finishRef.current = finish;
  async function open(id: string) {
    if (running) return;
    setBusy(true); setError(''); setNeedsIncomplete(false); connection.current = null;
    try { remember(await api<VoiceInterview>(`/voice-interviews/${id}`)); }
    catch (cause) { fail(cause); } finally { setBusy(false); }
  }
  async function retryReview() {
    if (!current) return;
    setBusy(true); setError('');
    try { remember(await api<VoiceInterview>(`/voice-interviews/${current.id}/report`, { method: 'POST', headers })); }
    catch (cause) { fail(cause); } finally { setBusy(false); }
  }
  return <section className="interview-panel" aria-labelledby="voice-title">
    <div className="section-heading"><h2 id="voice-title">实时语音面试</h2>
      {current && <button className="quiet-button" disabled={busy || running} onClick={() => { setCurrent(null); connection.current = null; setError(''); }}>返回语音面试列表</button>}
    </div>
    <p>像真实面试一样交谈，可以随时插话打断。面试过程中只对话，结束后统一复盘。</p>
    {error && <p className="error-message" role="alert">{error}</p>}
    {!current ? <>
      {loading && <p role="status">正在检查语音服务…</p>}
      {config && !config.configured && <div className="voice-notice" role="status">语音服务尚未配置。请在后端 .env 配置百炼语音 API Key 和业务空间地址，然后重启后端。</div>}
      {config && !config.review_configured && <p className="voice-notice">面试后复盘尚未配置。请在后端设置 DEEPSEEK_API_KEY；语音通话仍可单独进行。</p>}
      <form onSubmit={start}>
        <InterviewContextFields links={links} onChange={setLinks} onExpired={onExpired} />
        <label>目标岗位<input required maxLength={100} value={role} onChange={e => setRole(e.target.value)} /></label>
        <label>项目经历<textarea required minLength={10} maxLength={5000} rows={4} value={experience} onChange={e => setExperience(e.target.value)} /></label>
        <p className="planned-note">开始后请求麦克风权限，语音发送至{config?.provider ?? '语音服务'}，本应用保存文字转写用于复盘，不保存原始录音。建议戴耳机；单场最长 {config?.max_minutes ?? 15} 分钟。</p>
        <button className="primary-button" disabled={busy || !config?.configured || !role.trim() || experience.trim().length < 10}>开始语音面试</button>
      </form>
      <h3>语音面试记录</h3>
      <button className="quiet-button" disabled={busy} onClick={() => setRetry(value => value + 1)}>刷新语音记录</button>
      {!loading && !history.length && <p>暂无语音面试记录。</p>}
      <ul className="interview-history">{history.map(record => <li key={record.id}><button className="quiet-button" disabled={busy} onClick={() => open(record.id)}>{record.role} · {record.status === 'ended' ? '查看语音复盘' : '查看未结束面试'} · {new Date(record.created_at * 1000).toLocaleString()}</button></li>)}</ul>
    </> : <>
      <h3>{current.role}</h3>
      {current.status !== 'ended' && <div className="voice-stage">
        <div className={`voice-orb ${running ? 'voice-orb-active' : ''}`} aria-hidden="true">🎙</div>
        <p role="status">{busy ? voiceState : running ? voiceState : '语音已断开，可结束并复盘已保存内容'}</p>
        <div className="voice-controls">
          <button className="quiet-button" disabled={busy || !running || needsIncomplete} onClick={() => { const next = !muted; setMuted(next); connection.current?.setMicrophone(!next); }}>{muted ? '开启麦克风' : '静音麦克风'}</button>
          <button className="quiet-button" disabled={busy || !running} onClick={() => { connection.current?.interrupt(); setVoiceState('已打断，请继续回答'); }}>打断面试官</button>
          <button className="quiet-button" disabled={busy || !running} onClick={() => { void connection.current?.play().catch(fail); }}>播放面试官声音</button>
          <button className="primary-button" disabled={busy} onClick={() => { void finish(); }}>{busy ? '正在处理…' : '结束面试并复盘'}</button>
        </div>
        {needsIncomplete && <button className="quiet-button" disabled={busy} onClick={() => { void finish(true); }}>仅用已保存内容结束</button>}
      </div>}
      <h3>对话转写</h3>
      <p className="planned-note">转写可能存在识别误差。被打断的面试官文字可能包含尚未听到的部分。</p>
      {!current.messages.length && <p>对话开始后，转写会显示在这里。</p>}
      <ol className="voice-transcript">{current.messages.map(message => <li key={message.id} className={`voice-message voice-${message.role}`}><strong>{message.role === 'user' ? '你' : '面试官'}{!message.final ? ' · 转写中' : ''}{message.interrupted ? ' · 已打断' : ''}</strong><p>{message.text}</p></li>)}</ol>
      {current.status === 'ended' && <section aria-label="语音面试复盘">
        <h3>语音面试复盘</h3>
        {current.incomplete && <p className="voice-notice">本场使用不完整转写结束，复盘只采用已完整保存的回答。</p>}
        {current.report_status === 'processing' && <p role="status">面试已结束，正在根据完整对话生成复盘…</p>}
        {current.report_error && <p className="error-message" role="alert">{current.report_error}</p>}
        {current.report_status !== 'completed' && <button className="quiet-button" disabled={busy} onClick={retryReview}>重试生成复盘</button>}
        <button className="quiet-button" disabled={busy} onClick={() => open(current.id)}>刷新复盘</button>
        {current.report && <>
          <p>{current.report.summary}</p><p>内容表现评分：{current.report.data.score} / {current.report.data.max_score}</p>
          <p className="planned-note">{current.report.data.notice}</p>
          {current.report.data.dimensions.map(dimension => <article className="interview-feedback" key={dimension.name}>
            <h4>{dimension.name} · {dimension.score} / 5</h4><p>{dimension.reason}</p>
            {dimension.evidence.map((evidence, index) => <blockquote key={`${evidence.message_id}-${index}`}>{evidence.quote}</blockquote>)}
            <p>改进建议：{dimension.suggestion}</p>
          </article>)}
          <h4>待训练项</h4><ul>{current.report.data.training_items.map(item => <li key={item.skill}>{item.skill}：{item.task}</li>)}</ul>
        </>}
      </section>}
    </>}
  </section>;
}
