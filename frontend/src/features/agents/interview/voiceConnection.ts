import type { VoiceConnect, VoiceMessage } from './voiceTypes';

type Callbacks = {
  onState: (state: string) => void;
  onMessages: (messages: VoiceMessage[]) => void;
  onFinal: (message: VoiceMessage) => void;
  onError: (message: string) => void;
};
type CloudEvent = {
  type: string; event_id?: string; item_id?: string; response_id?: string;
  delta?: string; transcript?: string;
  response?: { id: string }; item?: { id: string; role?: string };
  error?: { code?: string; message?: string };
};

const wait = (ms: number) => new Promise<void>(resolve => window.setTimeout(resolve, ms));

/** WebRTC carries audio; both local and provider-created data channels carry control events. */
export class VoiceConnection {
  private pc: RTCPeerConnection | null = null;
  private media: MediaStream | null = null;
  private audio = new Audio();
  private channel: RTCDataChannel | null = null;
  private channels: RTCDataChannel[] = [];
  private messages = new Map<string, VoiceMessage>();
  private nextSequence = 0;
  private pending = new Set<string>();
  private seen = new Set<string>();
  private activeResponse: string | null = null;
  private assistantId: string | null = null;
  private speechActive = false;
  private failedTranscripts = new Set<string>();
  private lastInputEvent = 0;
  private closed = false;
  private finishing = false;
  private configured = false;
  private settings: Record<string, unknown> = {};
  private ready: (() => void) | null = null;
  private rejectReady: ((error: Error) => void) | null = null;

  constructor(private callbacks: Callbacks) {
    this.audio.autoplay = true;
    this.audio.setAttribute('playsinline', '');
  }

  async start(exchange: (offer: string) => Promise<VoiceConnect>) {
    if (!navigator.mediaDevices?.getUserMedia || !window.RTCPeerConnection) {
      throw new Error('当前环境不支持语音通话，请使用支持 WebRTC 的浏览器并通过 HTTPS 或本机地址访问');
    }
    this.callbacks.onState('正在申请麦克风权限');
    const media = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true }, video: false,
    });
    if (this.closed) { media.getTracks().forEach(track => track.stop()); throw new Error('连接已取消'); }
    this.media = media;
    // Do not send microphone audio until session.update has been acknowledged.
    media.getAudioTracks().forEach(track => { track.enabled = false; });
    const pc = new RTCPeerConnection({ iceServers: [] });
    this.pc = pc;
    media.getTracks().forEach(track => pc.addTrack(track, media));
    pc.ontrack = event => {
      this.audio.srcObject = event.streams[0] ?? new MediaStream([event.track]);
      void this.play().catch(() => this.callbacks.onError('浏览器阻止了声音播放，请点击“播放面试官声音”'));
    };
    pc.onconnectionstatechange = () => {
      if (this.closed) return;
      if (['failed', 'closed', 'disconnected'].includes(pc.connectionState)) {
        this.setMicrophone(false);
        this.callbacks.onState('连接中断');
        this.callbacks.onError('语音连接已中断，可结束并复盘已保存的内容，或返回列表新建面试');
        this.rejectReady?.(new Error('语音连接中断'));
      }
    };
    const attach = (channel: RTCDataChannel) => {
      this.channels.push(channel);
      channel.onmessage = event => {
        if (this.closed) return;
        try { this.handle(JSON.parse(String(event.data)) as CloudEvent, channel); }
        catch { this.callbacks.onError('收到无法解析的语音事件，请结束后重试'); }
      };
    };
    const outgoing = pc.createDataChannel('oai-events');
    attach(outgoing);
    pc.ondatachannel = event => attach(event.channel);
    this.callbacks.onState('正在连接面试官');
    await pc.setLocalDescription(await pc.createOffer());
    // This API accepts a complete SDP offer, not trickle ICE candidates.
    await new Promise<void>((resolve, reject) => {
      if (pc.iceGatheringState === 'complete') { resolve(); return; }
      const timeout = window.setTimeout(() => {
        pc.removeEventListener('icegatheringstatechange', changed);
        reject(new Error('网络协商超时，请检查网络后重试'));
      }, 7000);
      function changed() {
        if (pc.iceGatheringState !== 'complete') return;
        window.clearTimeout(timeout); pc.removeEventListener('icegatheringstatechange', changed); resolve();
      }
      pc.addEventListener('icegatheringstatechange', changed);
    });
    if (this.closed) throw new Error('连接已取消');
    const result = await exchange(pc.localDescription!.sdp);
    if (this.closed) throw new Error('连接已取消');
    this.settings = result.session;
    await new Promise<void>((resolve, reject) => {
      const timeout = window.setTimeout(() => reject(new Error('面试官未就绪，请结束后重试连接')), 15000);
      this.ready = () => { window.clearTimeout(timeout); resolve(); };
      this.rejectReady = error => { window.clearTimeout(timeout); reject(error); };
      void pc.setRemoteDescription({ type: 'answer', sdp: result.answer_sdp }).catch(this.rejectReady);
    });
    this.ready = null; this.rejectReady = null;
  }

  private send(event: Record<string, unknown>) {
    const channel = this.channel?.readyState === 'open' ? this.channel : this.channels.find(item => item.readyState === 'open');
    if (channel) channel.send(JSON.stringify({ event_id: crypto.randomUUID(), ...event }));
  }

  private update(id: string, role: 'user' | 'assistant', text: string, final: boolean) {
    const previous = this.messages.get(id);
    if (previous?.final) return;
    const message: VoiceMessage = {
      id, role, text, final, interrupted: previous?.interrupted ?? false,
      sequence: previous?.sequence ?? this.nextSequence++,
    };
    this.messages.set(id, message);
    this.callbacks.onMessages(this.snapshot());
    if (final && text.trim()) this.callbacks.onFinal(message);
  }

  private handle(event: CloudEvent, channel: RTCDataChannel) {
    if (event.event_id) {
      if (this.seen.has(event.event_id)) return;
      this.seen.add(event.event_id);
    }
    const type = event.type;
    if (type === 'session.created' && !this.configured) {
      this.channel = channel; this.configured = true;
      this.send({ type: 'session.update', session: this.settings });
    } else if (type === 'session.updated') {
      this.setMicrophone(true);
      this.callbacks.onState('正在聆听'); this.ready?.();
      this.send({ type: 'response.create' });
    } else if (type === 'response.created') {
      this.activeResponse = event.response?.id ?? null;
      this.assistantId = null;
      if (this.finishing) this.interrupt();
      else { this.audio.muted = false; this.callbacks.onState('面试官正在说话'); }
    } else if (type === 'response.done') {
      if (event.response?.id === this.activeResponse) this.activeResponse = null;
      if (!this.finishing) this.callbacks.onState('正在聆听');
    } else if (type === 'input_audio_buffer.speech_started') {
      this.lastInputEvent = Date.now(); this.speechActive = true;
      if (event.item_id) {
        this.pending.add(event.item_id);
        if (!this.messages.has(event.item_id)) this.update(event.item_id, 'user', '', false);
      }
      this.interrupt();
      if (!this.finishing) this.callbacks.onState('正在听你回答');
    } else if (type === 'input_audio_buffer.speech_stopped') {
      this.lastInputEvent = Date.now(); this.speechActive = false;
    } else if (type === 'conversation.item.created' && event.item) {
      const item = event.item;
      if (item.role === 'user' && !this.messages.has(item.id)) {
        this.pending.add(item.id); this.update(item.id, 'user', '', false);
      } else if (item.role === 'assistant') {
        this.assistantId = item.id;
        if (!this.messages.has(item.id)) this.update(item.id, 'assistant', '', false);
      }
    } else if (type.startsWith('conversation.item.input_audio_transcription.') && event.item_id) {
      this.lastInputEvent = Date.now();
      const id = event.item_id;
      if (type.endsWith('.failed')) {
        this.pending.delete(id); this.failedTranscripts.add(id);
        this.update(id, 'user', this.messages.get(id)?.text || '（该段语音转写失败）', false);
        this.callbacks.onError('有一段回答转写失败，结束时可确认仅使用已保存内容复盘');
      } else if (type.endsWith('.completed')) {
        this.pending.delete(id);
        this.failedTranscripts.delete(id);
        const text = event.transcript?.trim() ?? '';
        if (!text) { this.messages.delete(id); this.callbacks.onMessages(this.snapshot()); }
        else this.update(id, 'user', text, true);
      } else if (type.endsWith('.delta')) {
        this.update(id, 'user', (this.messages.get(id)?.text ?? '') + (event.delta ?? ''), false);
      }
    } else if (type === 'response.audio_transcript.delta' || type === 'response.audio_transcript.done') {
      const id = event.item_id;
      if (!id) return;
      this.assistantId = id;
      const final = type.endsWith('.done');
      const text = final ? (event.transcript ?? this.messages.get(id)?.text ?? '')
        : (this.messages.get(id)?.text ?? '') + (event.delta ?? '');
      this.update(id, 'assistant', text, final);
    } else if (type === 'error') {
      // A server-VAD cancellation can race our explicit cancellation.
      if (/no.*response|no active|not.*progress|cancel.*not/i.test(event.error?.message ?? '')) return;
      this.callbacks.onError('语音服务返回错误，请结束后检查后端模型配置与服务额度');
      this.rejectReady?.(new Error('语音服务配置未成功'));
    }
  }

  interrupt() {
    this.audio.muted = true;
    if (this.assistantId && this.activeResponse) {
      const message = this.messages.get(this.assistantId);
      if (message && !message.interrupted) {
        message.interrupted = true;
        this.callbacks.onMessages(this.snapshot());
        if (message.final && message.text.trim()) this.callbacks.onFinal({ ...message });
      }
    }
    if (this.activeResponse) { this.send({ type: 'response.cancel' }); this.activeResponse = null; }
  }

  setMicrophone(enabled: boolean) {
    this.media?.getAudioTracks().forEach(track => { track.enabled = enabled && !this.finishing; });
  }

  async play() { await this.audio.play(); }

  snapshot() { return [...this.messages.values()].filter(message => message.text.trim()).map(message => ({ ...message })); }

  async drain(acceptIncomplete = false): Promise<VoiceMessage[]> {
    this.finishing = true; this.setMicrophone(false); this.interrupt();
    this.callbacks.onState('正在保存最后的转写');
    if (!this.closed && !acceptIncomplete) {
      const start = Date.now();
      // Disabled RTP microphone tracks send silence, allowing server VAD to commit the last turn.
      while (Date.now() - start < 12000) {
        await wait(100);
        if (Date.now() - start >= 1500 && !this.speechActive && !this.pending.size &&
          Date.now() - this.lastInputEvent >= 1000) break;
      }
    }
    if (!acceptIncomplete && (this.pending.size || this.speechActive || this.failedTranscripts.size)) {
      throw new Error('最后的语音转写尚未完整到达。可以重试等待，或选择“仅用已保存内容结束”。');
    }
    if (acceptIncomplete) for (const id of this.pending) {
      if (!this.messages.get(id)?.text.trim()) this.update(id, 'user', '（该段语音未完成转写）', false);
    }
    return this.snapshot();
  }

  close() {
    if (this.closed) return;
    this.closed = true;
    this.rejectReady?.(new Error('连接已关闭'));
    this.media?.getTracks().forEach(track => track.stop());
    this.channels.forEach(channel => channel.close()); this.pc?.close();
    this.audio.pause(); this.audio.srcObject = null;
  }
}
