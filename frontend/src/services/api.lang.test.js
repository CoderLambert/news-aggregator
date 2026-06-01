/**
 * Regression tests for the language-parameter interceptor.
 *
 * Bug: only `api` (the 10s-timeout axios instance) had a request interceptor
 * adding ?lang=<lang>. `apiFetch` (full-article fetch) and `apiLong`
 * (translation) silently dropped the lang param, so backend got requests
 * with no language preference for two of the three critical endpoints.
 *
 * These tests guard against regression.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'

describe('axios lang interceptor coverage', () => {
  beforeEach(() => {
    vi.resetModules()
    localStorage.setItem('newshub_lang', 'en')
  })
  afterEach(() => {
    vi.restoreAllMocks()
    localStorage.clear()
  })

  // We capture the final request config by stubbing the axios adapter on each
  // instance. The adapter receives the fully-prepared config (params merged),
  // so we can assert on config.params.lang.
  async function captureRequestConfig(makeRequest) {
    const axios = (await import('axios')).default
    const captured = []
    const originalCreate = axios.create.bind(axios)
    vi.spyOn(axios, 'create').mockImplementation((cfg) => {
      const inst = originalCreate(cfg)
      inst.defaults.adapter = async (config) => {
        captured.push(config)
        return {
          data: {}, status: 200, statusText: 'OK',
          headers: {}, config, request: {},
        }
      }
      return inst
    })
    const api = await import('./api')
    await makeRequest(api)
    return captured
  }

  it('fetchNews (api client) includes lang=en in query params', async () => {
    const [config] = await captureRequestConfig(api => api.fetchNews())
    expect(config.params.lang).toBe('en')
  })

  it('fetchFullArticle (apiFetch client) includes lang=en in query params', async () => {
    const [config] = await captureRequestConfig(api => api.fetchFullArticle('42'))
    expect(config.params?.lang).toBe('en')   // ← will FAIL before fix
  })

  it('translateFullArticle (apiLong client) includes lang=en in query params', async () => {
    const [config] = await captureRequestConfig(api => api.translateFullArticle('42'))
    expect(config.params?.lang).toBe('en')   // ← will FAIL before fix
  })

  it('always sends lang param for valid language codes', async () => {
    localStorage.setItem('newshub_lang', 'en')
    const [config] = await captureRequestConfig(api => api.fetchNews())
    expect(config.params.lang).toBe('en')
  })

  it('defaults to lang=zh when localStorage is empty', async () => {
    localStorage.removeItem('newshub_lang')
    const [config] = await captureRequestConfig(api => api.fetchNews())
    expect(config.params.lang).toBe('zh')
  })
})
