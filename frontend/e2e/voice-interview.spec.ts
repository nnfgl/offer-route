import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';

async function login(page: Page, suffix: string) {
  await page.goto('/');
  await page.getByRole('button', { name: '注册', exact: true }).click();
  await page.getByLabel('称呼', { exact: true }).fill('语音同学');
  await page.getByLabel('邮箱地址').fill(`voice-${suffix}-${Date.now()}@example.com`);
  await page.getByLabel('密码', { exact: true }).fill('a-unique-long-password');
  await page.getByLabel('确认密码').fill('a-unique-long-password');
  await page.getByRole('button', { name: '创建账户并进入' }).click();
  await page.getByRole('button', { name: '进入模拟面试' }).click();
}

async function fakeMedia(page: Page) {
  await page.addInitScript(() => {
    let emit: (event: Record<string, unknown>) => void = () => {};
    let sequence = 0;
    const sent: Record<string, unknown>[] = [];
    const track = { kind: 'audio', enabled: false, stopped: false, stop() { this.stopped = true; } };
    const media = { getTracks: () => [track], getAudioTracks: () => [track] };
    Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: { getUserMedia: async () => media } });
    class Channel {
      readyState = 'open';
      onmessage: ((event: { data: string }) => void) | null = null;
      close() { this.readyState = 'closed'; }
      send(data: string) {
        const event = JSON.parse(data); sent.push(event);
        if (event.type === 'session.update') queueMicrotask(() => emit({ type: 'session.updated' }));
        if (event.type === 'response.create') queueMicrotask(() => {
          emit({ type: 'response.created', response: { id: 'r1' } });
          emit({ type: 'conversation.item.created', item: { id: 'q1', role: 'assistant' } });
          emit({ type: 'response.audio_transcript.delta', item_id: 'q1', delta: '请介绍你的项目。' });
        });
        if (event.type === 'response.cancel') queueMicrotask(() => {
          emit({ type: 'response.audio_transcript.done', item_id: 'q1', transcript: '请介绍你的项目。' });
          emit({ type: 'response.done', response: { id: 'r1' } });
        });
      }
    }
    class Peer {
      iceGatheringState = 'complete';
      localDescription: { sdp: string } | null = null;
      ondatachannel: ((event: { channel: Channel }) => void) | null = null;
      ontrack = null;
      onconnectionstatechange = null;
      connectionState = 'new';
      addTrack() {}
      createDataChannel() { return new Channel(); }
      async createOffer() { return { type: 'offer', sdp: 'v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\n' }; }
      async setLocalDescription(description: { sdp: string }) { this.localDescription = description; }
      async setRemoteDescription() {
        const channel = new Channel();
        this.ondatachannel?.({ channel });
        emit = event => channel.onmessage?.({ data: JSON.stringify({ event_id: `test-${++sequence}`, ...event }) });
        queueMicrotask(() => emit({ type: 'session.created' }));
      }
      close() { this.connectionState = 'closed'; }
    }
    Object.defineProperty(window, 'RTCPeerConnection', { value: Peer });
    Object.assign(window, { __voiceTest: { sent, track, emit: (event: Record<string, unknown>) => emit(event) } });
  });
}

type Message = { id: string; role: string; text: string; final: boolean; interrupted?: boolean };
async function fakeApi(page: Page) {
  let record = {
    id: 'voice-browser-test', role: 'Python 后端工程师', experience: '校园图书借阅系统的后端开发经历',
    status: 'created', created_at: 1, messages: [] as Message[], report_status: 'not_started',
    incomplete: false, report_error: null, report: null as unknown,
  };
  const actions: string[] = [];
  const report = {
    summary: '面试已结束，这是根据完整转写生成的复盘。',
    data: { score: 12, max_score: 20, notice: '基于文字转写，不分析声学表现。',
      dimensions: ['岗位理解', '技术与经历', '表达结构', '反思改进'].map(name => ({
        name, score: 3, reason: '根据候选人回答分析', suggestion: '补充可验证的项目结果',
        evidence: [{ message_id: 'u1', quote: '我负责接口开发' }],
      })), training_items: [{ skill: '技术与经历', task: '补充可验证的项目结果' }] },
  };
  await page.route('**/api/v1/voice-interviews**', async route => {
    const path = new URL(route.request().url()).pathname;
    const method = route.request().method();
    let response: unknown = record;
    if (path.endsWith('/config')) response = { configured: true, review_configured: true, max_minutes: 15, provider: '模拟语音服务' };
    else if (path.endsWith('/voice-interviews')) {
      if (method === 'GET') response = [];
      else { actions.push('create'); record = { ...record, ...route.request().postDataJSON() }; response = record; }
    } else if (path.endsWith('/connect')) {
      actions.push('connect'); record.status = 'live';
      response = { answer_sdp: 'v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\n', session: { instructions: '模拟面试官' } };
    } else if (path.endsWith('/messages')) {
      actions.push('save');
      const messages = new Map(record.messages.map(message => [message.id, message]));
      for (const message of route.request().postDataJSON().messages) messages.set(message.id, message);
      record.messages = [...messages.values()]; response = record;
    } else if (path.endsWith('/end')) {
      actions.push('end'); record.status = 'ended'; record.report_status = 'processing';
      record.incomplete = route.request().postDataJSON().accept_incomplete; response = record;
    } else if (method === 'GET' && record.status === 'ended') {
      actions.push('review'); record.report_status = 'completed'; record.report = report; response = record;
    }
    await route.fulfill({ status: path.endsWith('/voice-interviews') && method === 'POST' ? 201 : 200, json: response });
  });
  return { actions, record: () => record };
}

async function emit(page: Page, event: Record<string, unknown>) {
  await page.evaluate(value => {
    (window as unknown as { __voiceTest: { emit: (event: Record<string, unknown>) => void } }).__voiceTest.emit(value);
  }, event);
}

test('未配置语音服务时明确提示并保留文字练习入口', async ({ page }, info) => {
  await page.route('**/api/v1/voice-interviews/config', route => route.fulfill({
    json: { configured: false, max_minutes: 15, provider: '阿里云百炼' },
  }));
  await login(page, `config-${info.project.name}`);
  await expect(page.getByText(/语音服务尚未配置/)).toBeVisible();
  await expect(page.getByRole('button', { name: '开始语音面试', exact: true })).toBeDisabled();
  await page.getByRole('button', { name: '文字练习', exact: true }).click();
  await expect(page.getByRole('button', { name: '开始模拟面试', exact: true })).toBeVisible();
});

test('语音可打断，结束前保存最后一句，结束后才生成复盘', async ({ page }, info) => {
  await fakeMedia(page);
  const api = await fakeApi(page);
  await page.route('**/api/v1/interviews/contexts*', route => route.fulfill({ json: {
    shared_storage_ready: true, requires_job_link: true,
    jobs: [{ id: 'job-context', title: 'Python 后端工程师' }],
    diagnoses: new URL(route.request().url()).searchParams.has('job_analysis_id')
      ? [{ id: 'diagnosis-context', created_at: 1 }] : [],
  } }));
  await login(page, `live-${info.project.name}`);
  await page.getByLabel('关联岗位分析（必选）').selectOption('job-context');
  await page.getByLabel('关联能力诊断（可选）').selectOption('diagnosis-context');
  await page.getByLabel('项目经历').fill('在校园图书借阅系统中负责后端接口和数据库设计。');
  await page.getByRole('button', { name: '开始语音面试', exact: true }).click();
  await expect(page.getByText('面试官正在说话', { exact: true })).toBeVisible();
  expect((api.record() as unknown as { job_analysis_id: string }).job_analysis_id).toBe('job-context');
  expect((api.record() as unknown as { diagnosis_id: string }).diagnosis_id).toBe('diagnosis-context');
  await expect(page.getByRole('button', { name: '文字练习', exact: true })).toBeDisabled();
  await page.screenshot({ path: info.outputPath('voice-live.png'), fullPage: true });
  await emit(page, { type: 'input_audio_buffer.speech_started', item_id: 'u1' });
  const cancels = await page.evaluate(() => (window as unknown as { __voiceTest: { sent: { type: string }[] } }).__voiceTest.sent.filter(event => event.type === 'response.cancel').length);
  expect(cancels).toBe(1);
  await expect(page.getByText('面试官 · 已打断', { exact: true })).toBeVisible();
  await emit(page, { type: 'input_audio_buffer.speech_stopped', item_id: 'u1' });
  await emit(page, { type: 'conversation.item.input_audio_transcription.completed', item_id: 'u1', transcript: '我负责接口开发，并编写自动化测试。' });
  await expect(page.getByText('我负责接口开发，并编写自动化测试。', { exact: true })).toBeVisible();
  await expect(page.getByRole('region', { name: '语音面试复盘', exact: true })).toHaveCount(0);
  expect(api.actions).not.toContain('end'); expect(api.actions).not.toContain('review');
  // Empty ASR results can arrive after the next question: deleting them must not reuse sequence IDs.
  await emit(page, { type: 'input_audio_buffer.speech_started', item_id: 'empty' });
  await emit(page, { type: 'input_audio_buffer.speech_stopped', item_id: 'empty' });
  await emit(page, { type: 'conversation.item.created', item: { id: 'q2', role: 'assistant' } });
  await emit(page, { type: 'response.audio_transcript.done', item_id: 'q2', transcript: '验证结果是什么？' });
  await emit(page, { type: 'conversation.item.input_audio_transcription.completed', item_id: 'empty', transcript: '' });
  await emit(page, { type: 'input_audio_buffer.speech_started', item_id: 'u2' });
  await page.getByRole('button', { name: '结束面试并复盘', exact: true }).click();
  await expect(page.getByText('正在保存最后的转写', { exact: true })).toBeVisible();
  await emit(page, { type: 'input_audio_buffer.speech_stopped', item_id: 'u2' });
  await emit(page, { type: 'conversation.item.input_audio_transcription.completed', item_id: 'u2', transcript: '最后一句回答：下一步改进数据库索引。' });
  const review = page.getByRole('region', { name: '语音面试复盘', exact: true });
  await expect(review.getByText('面试已结束，这是根据完整转写生成的复盘。')).toBeVisible();
  expect(api.record().messages.find(message => message.id === 'u2')?.text).toContain('最后一句回答');
  const sequence = api.record().messages.map(message => (message as Message & { sequence: number }).sequence);
  expect(new Set(sequence).size).toBe(sequence.length);
  expect(api.actions.indexOf('end')).toBeGreaterThan(api.actions.lastIndexOf('save'));
  expect(api.actions.indexOf('review')).toBeGreaterThan(api.actions.indexOf('end'));
  expect(await page.evaluate(() => (window as unknown as { __voiceTest: { track: { stopped: boolean } } }).__voiceTest.track.stopped)).toBe(true);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath('voice-review.png'), fullPage: true });
});

test('转写失败时需明确确认，不能自动生成完整复盘', async ({ page }, info) => {
  await fakeMedia(page); const api = await fakeApi(page);
  await login(page, `partial-${info.project.name}`);
  await page.getByLabel('项目经历').fill('在校园图书借阅系统中负责后端接口和数据库设计。');
  await page.getByRole('button', { name: '开始语音面试', exact: true }).click();
  await expect(page.getByText('面试官正在说话', { exact: true })).toBeVisible();
  await emit(page, { type: 'input_audio_buffer.speech_started', item_id: 'u1' });
  await emit(page, { type: 'input_audio_buffer.speech_stopped', item_id: 'u1' });
  await emit(page, { type: 'conversation.item.input_audio_transcription.completed', item_id: 'u1', transcript: '我负责接口开发。' });
  await emit(page, { type: 'input_audio_buffer.speech_started', item_id: 'u2' });
  await emit(page, { type: 'input_audio_buffer.speech_stopped', item_id: 'u2' });
  await emit(page, { type: 'conversation.item.input_audio_transcription.failed', item_id: 'u2' });
  await page.getByRole('button', { name: '结束面试并复盘', exact: true }).click();
  await expect(page.getByRole('button', { name: '仅用已保存内容结束', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '开启麦克风', exact: true })).toBeDisabled();
  expect(api.actions).not.toContain('end');
  await page.route('**/api/v1/voice-interviews/*/messages', route => route.fulfill({
    status: 409, json: { error: { message: '已达到本场面试轮数上限' } },
  }), { times: 1 });
  await page.getByRole('button', { name: '仅用已保存内容结束', exact: true }).click();
  await expect(page.getByText('本场使用不完整转写结束，复盘只采用已完整保存的回答。')).toBeVisible();
  expect(api.record().incomplete).toBe(true);
  expect(api.record().messages.some(message => message.id === 'u1')).toBe(true);
});
