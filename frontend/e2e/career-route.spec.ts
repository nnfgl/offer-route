import { expect, test } from '@playwright/test';

test('自动生成求职路线，恢复练习并保存面试后的能力档案', async ({ page }, testInfo) => {
  test.setTimeout(60000);
  await page.goto('/');
  await page.getByRole('button', { name: '注册', exact: true }).click();
  await page.getByLabel('称呼', { exact: true }).fill('路线同学');
  await page.getByLabel('邮箱地址').fill(`career-${testInfo.project.name}-${Date.now()}@example.com`);
  await page.getByLabel('密码', { exact: true }).fill('career-integration-password');
  await page.getByLabel('确认密码').fill('career-integration-password');
  await page.getByRole('button', { name: '创建账户并进入' }).click();
  await page.getByRole('button', { name: '开始求职路线' }).click();
  await page.getByRole('button', { name: '填入示例' }).click();
  await page.getByRole('button', { name: '创建并运行路线' }).click();
  await expect(page.getByRole('button', { name: '完成 SQL 练习' })).toBeVisible();
  const reopen = async () => {
    await page.reload();
    await page.getByRole('button', { name: '开始求职路线' }).click();
    await page.getByRole('button', { name: /Python 后端工程师 ·/ }).click();
  };
  await reopen();
  await page.getByRole('button', { name: '完成 SQL 练习' }).click();
  await page.getByLabel('SQL 答案').fill("SELECT c.id, COUNT(o.id), COALESCE(SUM(o.amount_cents), 0) FROM customers c LEFT JOIN orders o ON o.customer_id=c.id AND o.status='paid' GROUP BY c.id");
  await page.getByRole('button', { name: '提交 SQL 校验' }).click();
  await expect(page.getByText('已保存本题的任务验证证据。')).toBeVisible();
  await page.getByRole('button', { name: '← 返回求职路线' }).click();
  await page.getByRole('button', { name: '进入关联面试' }).click();
  await expect(page.getByLabel('目标岗位')).toHaveValue('Python 后端工程师');
  await page.getByLabel('项目经历').fill('在校园图书项目中编写查询接口并处理异常返回。');
  await page.getByRole('button', { name: '开始模拟面试' }).click();
  for (let round = 1; round <= 3; round += 1) {
    await expect(page.getByRole('heading', { name: `第 ${round} / 3 轮` })).toBeVisible();
    await page.getByLabel('你的回答').fill('我接手校园项目的接口工作，梳理需求并修正返回格式。');
    await page.getByRole('button', { name: round < 3 ? '提交回答，继续追问' : '提交并生成复盘' }).click();
  }
  await expect(page.getByRole('region', { name: '面试复盘', exact: true })).toBeVisible();
  await page.getByRole('button', { name: '← 返回求职路线' }).click();
  const profile = page.getByRole('region', { name: '岗位能力档案' });
  await expect(profile.getByText(/必需要求的训练验证覆盖 1 \/ 2/)).toBeVisible();
  const practice = page.getByRole('region', { name: '面试后练习' });
  await practice.getByLabel('练习回答').first().fill('我负责梳理接口需求，记录现有返回格式并实现兼容。');
  await practice.getByRole('button', { name: '保存练习回答' }).first().click();
  await expect(practice.getByRole('heading', { name: /已提交/ })).toHaveCount(1);
  await reopen();
  await expect(practice.getByRole('heading', { name: /已提交/ })).toHaveCount(1);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
