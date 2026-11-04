import { useCallback, useState } from 'react';
import type { Session } from '../../../lib/api';
import { InterviewScreen } from './InterviewScreen';
import { VoiceInterviewScreen } from './VoiceInterviewScreen';

export function InterviewHub({ session, onExpired, onRunningChange }: {
  session: Session; onExpired: () => void; onRunningChange: (running: boolean) => void;
}) {
  const [mode, setMode] = useState<'voice' | 'text'>('voice');
  const [running, setRunning] = useState(false);
  const runningChanged = useCallback((value: boolean) => {
    setRunning(value); onRunningChange(value);
  }, [onRunningChange]);
  return <div>
    <div className="interview-mode" aria-label="面试方式">
      <button className="quiet-button" disabled={running} aria-pressed={mode === 'voice'} onClick={() => setMode('voice')}>实时语音</button>
      <button className="quiet-button" disabled={running} aria-pressed={mode === 'text'} onClick={() => setMode('text')}>文字练习</button>
    </div>
    {mode === 'voice' ? <VoiceInterviewScreen session={session} onExpired={onExpired} onRunningChange={runningChanged} /> : <InterviewScreen session={session} onExpired={onExpired} />}
  </div>;
}
