export type VoiceMessage = {
  id: string; role: 'user' | 'assistant'; text: string; final: boolean; interrupted: boolean; sequence: number;
};
export type VoiceReport = {
  summary: string;
  data: {
    score: number; max_score: number; notice: string;
    dimensions: {
      name: string; score: number; reason: string; suggestion: string;
      evidence: { message_id: string; quote: string }[];
    }[];
    training_items: { skill: string; task: string }[];
  };
};
export type VoiceInterview = {
  id: string; role: string; experience: string; created_at: number;
  status: 'created' | 'connecting' | 'live' | 'ended';
  messages: VoiceMessage[]; incomplete: boolean;
  report_status: 'not_started' | 'processing' | 'completed' | 'failed';
  report_started_at: number | null; report_error: string | null; report: VoiceReport | null;
};
export type VoiceConfig = { configured: boolean; max_minutes: number; provider: string };
export type VoiceConnect = { answer_sdp: string; session: Record<string, unknown> };
