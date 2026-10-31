import { useState } from 'react';
import type { FormEvent } from 'react';
import { api } from '../../lib/api';
import type { Session } from '../../lib/api';

export function AuthScreen({ onAuthenticated }: { onAuthenticated: (session: Session) => void }) {
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const fields = new FormData(event.currentTarget);
    const password = String(fields.get('password'));
    if (mode === 'register' && password !== fields.get('confirmation')) {
      setError('两次输入的密码不一致'); return;
    }
    setBusy(true); setError('');
    try {
      const body = {
        email: String(fields.get('email')).trim(), password,
        ...(mode === 'register' ? { display_name: String(fields.get('display_name')).trim() } : {}),
      };
      onAuthenticated(await api<Session>(`/auth/${mode}`, { method: 'POST', body: JSON.stringify(body) }));
    } catch (cause) { setError(cause instanceof Error ? cause.message : '操作失败，请重试'); }
    finally { setBusy(false); }
  }

  return <main className="auth-layout">
    <section className="story-panel">
      <a className="brand" href="/" aria-label="Offer Route 首页"><span className="brand-mark">↗</span> OFFER ROUTE</a>
      <div className="story-copy"><span className="eyebrow">YOUR NEXT CHAPTER</span>
        <h1>让每一次准备，<br />都离目标更近。</h1>
        <p>从看懂岗位，到练出实力。把求职准备变成一条清晰、可追踪的成长路线。</p>
        <div className="route-art" aria-hidden="true"><span>01 看懂目标</span><i /><span>02 找到差距</span><i /><span>03 练出实力</span><i /><span>04 从容表达</span></div>
      </div>
      <footer className="story-footer"><span>目标清晰 · 成长有据</span><span>CAREER, WITH DIRECTION.</span></footer>
    </section>
    <section className="form-panel" aria-labelledby="auth-title">
      <span className="edition">求职准备，从这里开始</span>
      <div className="auth-card"><span className="eyebrow muted">WELCOME TO YOUR WORKSPACE</span>
        <h2 id="auth-title">{mode === 'login' ? '欢迎回来' : '开启你的求职路线'}</h2>
        <p className="form-description">{mode === 'login' ? '登录账户，继续向理想岗位迈进。' : '创建账户，为下一次机会做好准备。'}</p>
        <div className="mode-switch" aria-label="账户操作">
          <button type="button" disabled={busy} aria-pressed={mode === 'login'} className={mode === 'login' ? 'active' : ''} onClick={() => { setMode('login'); setError(''); }}>登录</button>
          <button type="button" disabled={busy} aria-pressed={mode === 'register'} className={mode === 'register' ? 'active' : ''} onClick={() => { setMode('register'); setError(''); }}>注册</button>
        </div>
        <form key={mode} onSubmit={submit}>
          {mode === 'register' && <label>称呼<input name="display_name" autoComplete="nickname" placeholder="我们应该如何称呼你" required maxLength={40} pattern=".*\S.*" /></label>}
          <label>邮箱地址<input name="email" type="email" autoComplete="email" placeholder="you@example.com" required maxLength={254} /></label>
          <label>密码<input name="password" type="password" autoComplete={mode === 'login' ? 'current-password' : 'new-password'} placeholder="至少 10 个字符" required minLength={10} maxLength={128} /></label>
          {mode === 'register' && <label>确认密码<input name="confirmation" type="password" autoComplete="new-password" placeholder="再次输入密码" required minLength={10} maxLength={128} /></label>}
          {error && <p className="error-message" role="alert">{error}</p>}
          <button className="primary-button" disabled={busy} type="submit">{busy ? '正在处理…' : mode === 'login' ? '登录工作台' : '创建账户并进入'}<span aria-hidden="true">↗</span></button>
        </form>
        <p className="privacy-note">你的求职路线，从一个属于自己的账户开始。</p>
      </div>
      <footer className="form-footer">OFFER ROUTE <span>一步一步，走向下一站。</span></footer>
    </section>
  </main>;
}
