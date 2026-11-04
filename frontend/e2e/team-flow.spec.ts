import { expect, test } from '@playwright/test';

test('诊断缺口进入 SQL 训练，校验后关联同一岗位面试', async ({ page }, testInfo) => {
  test.setTimeout(60000);
  await page.goto('/');
  await page.getByRole('button', { name: '注册', exact: true }).click();
  await page.getByLabel('称呼', { exact: true }).fill('联调同学');
  await page.getByLabel('邮箱地址').fill(`team-${testInfo.project.name}-${Date.now()}@example.com`);
  await page.getByLabel('密码', { exact: true }).fill('team-integration-password');
  await page.getByLabel('确认密码').fill('team-integration-password');
  await page.getByRole('button', { name: '创建账户并进入' }).click();
  await expect(page.getByRole('heading', { name: '你好，联调同学。' })).toBeVisible();
  const session = await (await page.request.get('/api/v1/auth/me')).json();
  const headers = { Origin: 'http://127.0.0.1:5173', 'X-CSRF-Token': session.csrf_token };
  const jobResponse = await page.request.post('/api/v1/jobs/analyses', {
    headers, data: { title: '联调 Python 后端', source_text: '岗位要求：\n熟悉 Python 开发\n熟悉 SQL 数据库查询与聚合' },
  });
  expect(jobResponse.status()).toBe(201);
  const job = await jobResponse.json();
  await page.getByRole('button', { name: '开始能力诊断 ↗' }).click();
  await page.getByLabel('对比的岗位分析').selectOption(job.id);
  await page.getByLabel('简历标题').fill('联调简历');
  await page.getByLabel('简历内容').fill('在校园项目中负责 Python 接口实现，编写单元测试并维护文档。');
  const diagnosisPromise = page.waitForResponse(response => response.url().endsWith('/api/v1/diagnoses') && response.request().method() === 'POST');
  await page.getByRole('button', { name: '开始能力诊断', exact: false }).click();
  const diagnosisResponse = await diagnosisPromise;
  expect(diagnosisResponse.status()).toBe(201);
  const diagnosis = await diagnosisResponse.json();
  await expect(page.getByRole('region', { name: '能力诊断结果' }).getByText('已完成', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '返回工作台', exact: true }).click();
  const gaps = await (await page.request.get(`/api/v1/training/diagnoses/${diagnosis.id}/gaps`)).json();
  const gap = gaps.gaps.find((item: { skill_id: string }) => item.skill_id === 'sql.join_aggregation');
  expect(gap).toBeTruthy();
  await page.getByRole('button', { name: '开始实战训练 ↗' }).click();
  await page.getByLabel('选择能力诊断').selectOption(diagnosis.id);
  await page.getByLabel('选择 SQL 待训练项').selectOption(gap.requirement_id);
  await page.getByRole('button', { name: '创建 SQL 训练' }).click();
  const task = page.getByRole('region', { name: '当前训练' });
  await expect(task).toBeVisible();
  await page.getByLabel('SQL 答案').fill('SELECT 1');
  await page.getByRole('button', { name: '提交 SQL 校验' }).click();
  await expect(task.getByRole('heading', { name: '第 1 次：未通过' })).toBeVisible();
  await page.getByLabel('SQL 答案').fill("SELECT c.id, COUNT(o.id), COALESCE(SUM(o.amount_cents), 0) FROM customers c LEFT JOIN orders o ON o.customer_id=c.id AND o.status='paid' GROUP BY c.id");
  await page.getByRole('button', { name: '提交 SQL 校验' }).click();
  await expect(task.getByText('任务状态：已完成', { exact: true })).toBeVisible();
  await expect(task.getByText('已保存本题的任务验证证据。')).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.reload();
  await page.getByRole('button', { name: '开始实战训练 ↗' }).click();
  await page.getByRole('button', { name: /SQL 聚合与 LEFT JOIN · 已完成/ }).click();
  await expect(page.getByRole('heading', { name: '第 2 次：通过' })).toBeVisible();
  await page.getByRole('button', { name: '← 返回工作台' }).click();
  await page.getByRole('button', { name: '进入模拟面试' }).click();
  await page.getByRole('button', { name: '文字练习', exact: true }).click();
  await page.getByLabel('关联岗位分析（可选）').selectOption(job.id);
  await page.getByLabel('关联能力诊断（可选）').selectOption(diagnosis.id);
  await page.getByLabel('项目经历').fill('在校园项目中负责 Python 接口实现，并编写单元测试。');
  await page.getByRole('button', { name: '开始模拟面试' }).click();
  for (let round = 1; round <= 3; round += 1) {
    await expect(page.getByRole('heading', { name: `第 ${round} / 3 轮` })).toBeVisible();
    await page.getByLabel('你的回答').fill('我实现接口并编写测试，对比方案，记录结果和局限。');
    await page.getByRole('button', { name: round < 3 ? '提交回答，继续追问' : '提交并生成复盘' }).click();
  }
  await expect(page.getByRole('region', { name: '面试复盘', exact: true })).toBeVisible();
});
