import { useCallback, useState } from 'react';
import type { Session } from '../../../lib/api';
import { InterviewScreen } from './InterviewScreen';
import { VoiceInterviewScreen } from './VoiceInterviewScreen';
import type { FixedInterviewContext } from './InterviewContextFields';

export function InterviewHub({ session, onExpired, onRunningChange, context }: {
  session: Session; onExpired: () => void; onRunningChange: (running: boolean) => void;
  context?: FixedInterviewContext;
}) {
  const [mode, setMode] = useState<'voice' | 'text'>(context ? 'text' : 'voice');
  const [running, setRunning] = useState(false);
  const runningChanged = useCallback((value: boolean) => {
    setRunning(value); onRunningChange(value);
  }, [onRunningChange]);
  return <div>
    <div className="interview-mode" aria-label="面试方式">
      <button className="quiet-button" disabled={running} aria-pressed={mode === 'voice'} onClick={() => setMode('voice')}>实时语音</button>
      <button className="quiet-button" disabled={running} aria-pressed={mode === 'text'} onClick={() => setMode('text')}>文字练习</button>
    </div>
    {mode === 'voice' ? <VoiceInterviewScreen session={session} onExpired={onExpired} onRunningChange={runningChanged} context={context} /> : <InterviewScreen session={session} onExpired={onExpired} context={context} />}
  </div>;
}
