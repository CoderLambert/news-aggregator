import { afterEach, describe, expect, it, vi } from 'vitest'
import { parseNewsSummary, parseNewsDetail } from '@/types/news'
const item = { id: 1, title: 'Title', publish_time: '2026-10-12', source: 1, source_name: 'Source', category: 1, category_name: 'Category' }
afterEach(() => vi.restoreAllMocks())
describe('summary and detail contracts', () => {
  it('keeps bodies out of summaries and supports a legacy server during rollout', () => {
    const summary = parseNewsSummary({ ...item, content: 'a'.repeat(10000), content_zh: '中'.repeat(10000) })
    expect(summary.summary).toHaveLength(300)
    expect(summary.summary_zh).toHaveLength(300)
    expect(summary).not.toHaveProperty('content')
    expect(parseNewsSummary({ ...item, summary: 'excerpt' }).summary).toBe('excerpt')
  })
  it('rejects summaries as details and preserves complete detail bodies', () => {
    expect(() => parseNewsDetail({ ...item, summary: 'excerpt' })).toThrow(/content/)
    expect(() => parseNewsDetail({ ...item, content: 'legacy', content_zh: '' })).toThrow(/full_content/)
    expect(parseNewsDetail({ ...item, content: 'a'.repeat(10000), content_zh: '', full_content: '' }).content).toHaveLength(10000)
  })
})
it('sets 30s and summary only for list requests', async () => {
  vi.resetModules()
  const axios = (await import('axios')).default
  const captured = []
  const originalCreate = axios.create.bind(axios)
  vi.spyOn(axios, 'create').mockImplementation(cfg => {
    const instance = originalCreate(cfg)
    instance.defaults.adapter = async config => {
      captured.push(config)
      return { data: {}, status: 200, statusText: 'OK', headers: {}, config }
    }
    return instance
  })
  const api = await import('@/services/api')
  const signal = new AbortController().signal
  await api.fetchNews({ page: 2, search: 'test' }, signal)
  await api.fetchSemanticSearch('test', { page: 3 })
  await api.fetchNewsDetail(1)
  await api.fetchCategories()
  await api.fetchFullArticle(1)
  expect(captured.map(c => c.timeout)).toEqual([30000, 30000, 10000, 10000, 120000])
  expect(captured[0].params).toMatchObject({ page: 2, search: 'test', representation: 'summary' })
  expect(captured[0].signal).toBe(signal)
  expect(captured[1].params).toMatchObject({ page: 3, mode: 'semantic', representation: 'summary' })
})
