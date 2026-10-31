import { expect, test } from '@playwright/test';

test('注册、刷新恢复、退出和重新登录', async ({ page }, testInfo) => {
  const email = `qa-${testInfo.project.name}-${Date.now()}@example.com`;
  const password = 'a-unique-long-password';
  await page.goto('/');
  await page.getByRole('button', { name: '注册', exact: true }).click();
  await page.getByLabel('称呼', { exact: true }).fill('测试同学');
  await page.getByLabel('邮箱地址').fill(email);
  await page.getByLabel('密码', { exact: true }).fill(password);
  await page.getByLabel('确认密码').fill(password);
  await page.getByRole('button', { name: '创建账户并进入' }).click();
  await expect(page.getByRole('heading', { name: '你好，测试同学。' })).toBeVisible();
  await expect(page.getByText('即将开放', { exact: true })).toHaveCount(3);
  await page.reload();
  await expect(page.getByRole('heading', { name: '你好，测试同学。' })).toBeVisible();
  expect(await page.evaluate(() => localStorage.length)).toBe(0);
  expect(await page.evaluate(() => document.cookie)).not.toContain('offer_session');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByRole('button', { name: '退出登录' }).click();
  await expect(page.getByRole('heading', { name: '欢迎回来' })).toBeVisible();
  await page.getByLabel('邮箱地址').fill(email);
  await page.getByLabel('密码', { exact: true }).fill('incorrect-long-password');
  await page.getByRole('button', { name: '登录工作台' }).click();
  await expect(page.getByRole('alert')).toHaveText('邮箱或密码错误');
  await page.getByLabel('密码', { exact: true }).fill(password);
  await page.getByRole('button', { name: '登录工作台' }).click();
  await expect(page.getByRole('heading', { name: '你好，测试同学。' })).toBeVisible();
  await page.getByRole('button', { name: '退出登录' }).click();
  await expect(page.getByRole('heading', { name: '欢迎回来' })).toBeVisible();
});

test('确认密码不一致时保留表单并提示', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: '注册', exact: true }).click();
  await page.getByLabel('称呼', { exact: true }).fill('小林');
  await page.getByLabel('邮箱地址').fill('validation@example.com');
  await page.getByLabel('密码', { exact: true }).fill('first-long-password');
  await page.getByLabel('确认密码').fill('second-long-password');
  await page.getByRole('button', { name: '创建账户并进入' }).click();
  await expect(page.getByRole('alert')).toHaveText('两次输入的密码不一致');
});
