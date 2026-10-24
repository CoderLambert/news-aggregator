import { test, expect } from '@playwright/test'
import type { Page } from '@playwright/test'
import type { BackendSnapshot } from '../../src/mocks/backend'
import type { MockDiagnostics } from '../../src/mocks/browser'
type MockWindow = Window & { __NEWSHUB_MOCK__?: MockDiagnostics }
import { scenarioMatrix } from './matrix.mjs'

const TITLE = '场景测试：前端接口契约'
const READ_PATH = '/api/me/news/910001/read-state/'
async function snapshot(page: Page): Promise<BackendSnapshot> {
  return page.evaluate(() => {
    const mock = (window as MockWindow).__NEWSHUB_MOCK__
    if (!mock) throw new Error('MSW diagnostic marker missing')
    return mock.inspect()
  })
}
async function opened(page: Page) {
  await expect(page.getByRole('heading', { name: TITLE, exact: true })).toBeVisible()
}
async function ready(page: Page) {
  await expect(page.locator('#newshub-mock-status')).toBeVisible()
  await expect.poll(() => page.evaluate(() => (window as MockWindow).__NEWSHUB_MOCK__?.transport)).toBe('msw')
}
async function patchStatuses(page: Page) {
  return (await snapshot(page)).requests.filter(row => row.path === READ_PATH && row.method === 'PATCH').map(row => row.status)
}

test.afterEach(async ({ page }, info) => {
  if (!await page.evaluate(() => Boolean((window as MockWindow).__NEWSHUB_MOCK__)).catch(() => false)) return
  const data = await snapshot(page)
  await info.attach('mock-network-audit', { body: JSON.stringify(data, null, 2), contentType: 'application/json' })
  // A forgotten startup endpoint is a failure, even when the main article happens to render.
  expect(data.unhandled).toEqual([])
})

for (const row of scenarioMatrix) {
  test(`${row.id}: ${row.journey}`, async ({ page }) => {
    const apiResponses: boolean[] = []
    const escaping: string[] = []
    page.on('response', response => {
      const url = new URL(response.url())
      if (url.pathname.startsWith('/api/')) apiResponses.push(response.fromServiceWorker())
      if (url.origin !== 'http://127.0.0.1:9530' && ['http:', 'https:'].includes(url.protocol)) escaping.push(url.origin)
    })
    await page.goto(`${row.path}?scenario=${row.id}`, { waitUntil: 'commit' })
    await ready(page)
    const list = page.getByRole('region', { name: '资讯阅读列表' })
    const listError = list.getByRole('alert').filter({ hasText: '新闻加载失败。' })
    switch (row.journey) {
      case 'open-and-save': {
        await list.getByRole('heading', { name: TITLE, exact: true }).click()
        await opened(page)
        const mark = page.getByRole('button', { name: '标为已读', exact: true })
        await expect(mark).toBeEnabled()
        await mark.click()
        await expect(page.getByRole('button', { name: '已读', exact: true })).toHaveAttribute('aria-pressed', 'true')
        await expect.poll(() => patchStatuses(page)).toEqual([200])
        break
      }
      case 'empty-list':
        await expect(list.getByText('未找到结果', { exact: true })).toBeVisible()
        await expect(list.getByRole('heading', { name: TITLE, exact: true })).toHaveCount(0)
        break
      case 'list-error':
        await expect(listError).toBeVisible()
        await expect(list.getByRole('heading', { name: TITLE, exact: true })).toHaveCount(0)
        expect((await snapshot(page)).requests.filter(r => r.path === '/api/news/').some(r => r.status === row.status)).toBe(true)
        break
      case 'manual-retry':
        await expect(listError).toBeVisible()
        expect((await snapshot(page)).requests.filter(r => r.path === '/api/news/').map(r => r.status)).toEqual([503, 503])
        await listError.getByRole('button', { name: '重试', exact: true }).click()
        await expect(list.getByRole('heading', { name: TITLE, exact: true })).toBeVisible()
        expect((await snapshot(page)).requests.filter(r => r.path === '/api/news/').map(r => r.status)).toEqual([503, 503, 200])
        break
      case 'slow-list':
        await expect.poll(async () => (await snapshot(page)).requests.some(r => r.path === '/api/news/' && r.outcome === 'pending')).toBe(true)
        await expect(list.getByRole('heading', { name: TITLE, exact: true })).toHaveCount(0)
        await expect(list.getByRole('heading', { name: TITLE, exact: true })).toBeVisible()
        break
      case 'search-race': {
        await expect(list.getByRole('heading', { name: TITLE, exact: true })).toBeVisible()
        const search = list.getByRole('searchbox')
        const before = (await snapshot(page)).requests.filter(r => r.path === '/api/news/').length
        await search.fill('旧')
        await expect.poll(async () => (await snapshot(page)).requests.filter(r => r.path === '/api/news/').length).toBeGreaterThan(before)
        await search.fill('新')
        await expect(list.getByRole('heading', { name: '场景测试：新请求结果', exact: true })).toBeVisible()
        await expect.poll(async () => (await snapshot(page)).active).toBe(0)
        await expect(list.getByRole('heading', { name: '场景测试：旧请求结果', exact: true })).toHaveCount(0)
        break
      }
      case 'detail-error':
        await expect(page.getByRole('alert').filter({ hasText: '新闻加载失败，请重试。' })).toBeVisible()
        await expect(page.getByRole('heading', { name: TITLE, exact: true })).toHaveCount(0)
        expect((await snapshot(page)).requests.some(r => r.path === '/api/news/910001/' && r.status === 404)).toBe(true)
        break
      case 'no-body':
        await opened(page)
        await expect(page.getByText('合成文章正文', { exact: true })).toHaveCount(0)
        await expect(page.getByText('这是一条合成摘要，用于测试真实 NewsHub 页面。', { exact: true }).first()).toBeVisible()
        break
      case 'failed-save': {
        await opened(page)
        const mark = page.getByRole('button', { name: '标为已读', exact: true })
        await expect(mark).toBeEnabled(); await mark.click()
        await expect(page.getByRole('alert').filter({ hasText: '未能保存，请重试。' })).toBeVisible()
        await expect(mark).toHaveAttribute('aria-pressed', 'false')
        await expect(mark).toBeEnabled()
        await expect.poll(() => patchStatuses(page)).toEqual([503])
        break
      }
      case 'conflict-recovery':
        await opened(page)
        await page.getByRole('button', { name: '标为已读', exact: true }).click()
        await expect(page.getByRole('alert').filter({ hasText: '未能保存' })).toBeVisible()
        await page.getByRole('button', { name: '已读', exact: true }).click()
        await expect(page.getByRole('button', { name: '标为已读', exact: true })).toHaveAttribute('aria-pressed', 'false')
        await expect.poll(() => patchStatuses(page)).toEqual([409, 200])
        break
      case 'read-retry':
        await opened(page)
        await page.getByRole('button', { name: '重试读取状态', exact: true }).click()
        await expect(page.getByRole('button', { name: '标为已读', exact: true })).toBeEnabled()
        break
      case 'no-personal-write':
        await opened(page)
        await expect(page.getByRole('button', { name: /^(标为已读|已读|读取状态…)$/ })).toHaveCount(0)
        expect((await snapshot(page)).requests.some(r => r.path === row.probe && r.status === row.status)).toBe(true)
        expect((await snapshot(page)).requests.some(r => r.method === 'PATCH')).toBe(false)
        break
      default: throw new Error(`Missing journey implementation: ${row.journey}`)
    }
    // Actual successful responses must have come from a worker, not a Vite/Django fallback.
    expect(apiResponses.length).toBeGreaterThan(0)
    expect(apiResponses.every(Boolean)).toBe(true)
    expect(escaping).toEqual([])
  })
}

test('reload resets state and counters; SPA navigation does not require a scenario query', async ({ page }) => {
  await page.goto('/news/910001?scenario=normal')
  await ready(page)
  await page.getByRole('button', { name: '标为已读', exact: true }).click()
  await expect(page.getByRole('button', { name: '已读', exact: true })).toBeVisible()
  await page.reload()
  await ready(page)
  await expect(page.getByRole('button', { name: '标为已读', exact: true })).toHaveAttribute('aria-pressed', 'false')
  expect(await patchStatuses(page)).toEqual([])
})
test('browser contexts do not share private read state', async ({ page, browser }) => {
  await page.goto('/news/910001?scenario=normal')
  await ready(page)
  await page.getByRole('button', { name: '标为已读', exact: true }).click()
  await expect(page.getByRole('button', { name: '已读', exact: true })).toBeVisible()
  const other = await browser.newContext({ serviceWorkers: 'allow' })
  try {
    const otherPage = await other.newPage()
    await otherPage.goto('http://127.0.0.1:9530/news/910001?scenario=normal')
    await ready(otherPage)
    await expect(otherPage.getByRole('button', { name: '标为已读', exact: true })).toHaveAttribute('aria-pressed', 'false')
    expect((await snapshot(otherPage)).unhandled).toEqual([])
  } finally { await other.close() }
})
test('unknown scenario fails before the app can issue API requests', async ({ page }) => {
  const requested: string[] = []
  page.on('request', r => { if (new URL(r.url()).pathname.startsWith('/api/')) requested.push(r.url()) })
  await page.goto('/?scenario=misspelled')
  await expect(page.getByRole('alert')).toContainText('模拟环境启动失败')
  expect(requested).toEqual([])
  expect(await page.evaluate(() => Boolean((window as MockWindow).__NEWSHUB_MOCK__))).toBe(false)
})
test('worker-blocked browser fails closed instead of loading the real API', async ({ browser }) => {
  const context = await browser.newContext({ serviceWorkers: 'block' })
  try {
    const page = await context.newPage()
    await page.goto('http://127.0.0.1:9530/?scenario=normal')
    await expect(page.getByRole('alert')).toContainText('模拟环境启动失败')
  } finally { await context.close() }
})
test('narrow viewport can open an article and save its state', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/?scenario=normal')
  await ready(page)
  await page.getByRole('region', { name: '资讯阅读列表' }).getByRole('heading', { name: TITLE, exact: true }).click()
  await opened(page)
  await page.getByRole('button', { name: '标为已读', exact: true }).click()
  await expect(page.getByRole('button', { name: '已读', exact: true })).toHaveAttribute('aria-pressed', 'true')
})
