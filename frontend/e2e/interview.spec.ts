import { expect, test } from '@playwright/test';

test('独立完成三轮面试，刷新恢复与查看复盘', async ({ page }, testInfo) => {
  await page.goto('/');
  await page.getByRole('button', { name: '注册', exact: true }).click();
  await page.getByLabel('称呼', { exact: true }).fill('面试同学');
  await page.getByLabel('邮箱地址').fill(`interview-${testInfo.project.name}-${Date.now()}@example.com`);
  await page.getByLabel('密码', { exact: true }).fill('a-unique-long-password');
  await page.getByLabel('确认密码').fill('a-unique-long-password');
  await page.getByRole('button', { name: '创建账户并进入' }).click();
  await page.getByRole('button', { name: '进入模拟面试' }).click();
  await page.getByLabel('项目经历').fill('在校园图书借阅系统中负责后端接口开发和数据库设计。');
  await page.getByRole('button', { name: '开始模拟面试' }).click();
  await expect(page.getByRole('heading', { name: '第 1 / 3 轮' })).toBeVisible();
  await page.getByLabel('你的回答').fill('我实现了图书借阅接口，并编写测试。');
  await page.getByRole('button', { name: '提交回答，继续追问' }).click();
  await expect(page.getByRole('heading', { name: '第 2 / 3 轮' })).toBeVisible();
  await page.reload();
  await page.getByRole('button', { name: '进入模拟面试' }).click();
  await page.getByRole('button', { name: /继续第 2 轮/ }).click();
  await expect(page.getByText('我实现了图书借阅接口，并编写测试。', { exact: true })).toBeVisible();
  await page.getByLabel('你的回答').fill('我对比了关系数据库和文档数据库，根据事务需求选择 SQLite。');
  await page.getByRole('button', { name: '提交回答，继续追问' }).click();
  await expect(page.getByRole('heading', { name: '第 3 / 3 轮' })).toBeVisible();
  await page.getByLabel('你的回答').fill('目前没有补充。');
  await page.getByRole('button', { name: '提交并生成复盘' }).click();
  const report = page.getByRole('region', { name: '面试复盘', exact: true });
  await expect(report).toBeVisible();
  await expect(report.getByText('表达线索得分：3 / 4', { exact: true })).toBeVisible();
  await expect(report.getByText('反思改进：说明一次失败或局限，以及下一步改进。', { exact: true })).toBeVisible();
  await expect(page.getByLabel('你的回答')).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath('interview-review.png'), fullPage: true });
  await page.getByRole('button', { name: '返回面试列表' }).click();
  await page.getByRole('button', { name: /查看复盘/ }).click();
  await expect(report).toBeVisible();
  expect(await page.evaluate(() => localStorage.length)).toBe(0);
});

test('加载失败可重试，提交失败保留回答并能继续', async ({ page, request }, testInfo) => {
  // Create an account, then log in through the UI to obtain its normal session and CSRF token.
  const email = `retry-${testInfo.project.name}-${Date.now()}@example.com`;
  await request.post('http://127.0.0.1:8000/api/v1/auth/register', {
    headers: { Origin: 'http://127.0.0.1:5173' },
    data: { email, password: 'a-unique-long-password', display_name: '重试同学' },
  });
  await page.goto('/');
  await page.getByLabel('邮箱地址').fill(email);
  await page.getByLabel('密码', { exact: true }).fill('a-unique-long-password');
  await page.getByRole('button', { name: '登录工作台' }).click();
  await page.route('**/api/v1/interviews', route => route.fulfill({
    status: 503, json: { error: { message: '模拟加载失败' } },
  }));
  await page.getByRole('button', { name: '进入模拟面试' }).click();
  await expect(page.getByRole('alert')).toHaveText('模拟加载失败');
  await page.unroute('**/api/v1/interviews');
  await page.getByRole('button', { name: '刷新记录' }).click();
  await expect(page.getByText('暂无面试记录。')).toBeVisible();
  await page.getByLabel('项目经历').fill('在校园项目中实现图书借阅接口和数据库访问层。');
  await page.getByRole('button', { name: '开始模拟面试' }).click();
  await page.getByLabel('你的回答').fill('我实现接口和测试。');
  await page.route('**/api/v1/interviews/*/answers', route => route.fulfill({
    status: 503, json: { error: { message: '模拟提交失败' } },
  }), { times: 1 });
  await page.getByRole('button', { name: '提交回答，继续追问' }).click();
  await expect(page.getByRole('alert')).toContainText('模拟提交失败');
  await expect(page.getByLabel('你的回答')).toHaveValue('我实现接口和测试。');
  await page.getByRole('button', { name: '提交回答，继续追问' }).click();
  await expect(page.getByRole('heading', { name: '第 2 / 3 轮' })).toBeVisible();
});
