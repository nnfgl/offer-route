import { StrictMode, useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { AuthScreen } from './features/auth/AuthScreen';
import { WorkspaceScreen } from './features/workspace/WorkspaceScreen';
import { api, ApiError } from './lib/api';
import type { Session } from './lib/api';
import './styles.css';

function App() {
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let active = true;
    setLoading(true); setError('');
    api<Session>('/auth/me').then(data => { if (active) setSession(data); }).catch(cause => {
      if (active && !(cause instanceof ApiError && cause.status === 401)) setError(cause.message);
    }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [retry]);
  if (loading) return <main className="loading-screen" role="status">正在准备你的工作台…</main>;
  if (error) return <main className="loading-screen"><h1>暂时无法连接服务</h1><p role="alert">{error}</p><button className="primary-button" onClick={() => setRetry(value => value + 1)}>重新连接</button></main>;
  return session ? <WorkspaceScreen session={session} onLogout={() => setSession(null)} /> : <AuthScreen onAuthenticated={setSession} />;
}

createRoot(document.getElementById('root')!).render(<StrictMode><App /></StrictMode>);
