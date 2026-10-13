import { afterEach, describe, expect, it, vi } from 'vitest'
import { safeExternalUrl, setWorkspaceViewer, workspaceRequest, workspaceError, WorkspaceError } from '@/services/workspaceApi'

afterEach(() => { vi.unstubAllGlobals(); setWorkspaceViewer(null); document.cookie = 'csrftoken=; Max-Age=0' })

describe('workspace transport', () => {
  it.each([
    [400, ['只接受不含凭据的公开 HTTP(S) 域名地址。'], '只接受不含凭据的公开 HTTP(S) 域名地址。'],
    [400, { url: ['请输入有效地址。'] }, '请输入有效地址。'],
    [422, { non_field_errors: ['地址格式有误。'] }, '地址格式有误。'],
    [401, { detail: 'internal auth text' }, '请先登录后再进行此操作。'],
    [403, { detail: 'internal permission text' }, '当前操作没有权限，或安全会话已过期。请刷新页面后重试。'],
    [500, { detail: 'Traceback: private server configuration' }, '服务暂时不可用，请稍后重试。'],
    [400, { debug: 'internal diagnostic' }, '请求参数不正确，请检查输入后重试。'],
    [400, { detail: '<script>unsafe</script>' }, '请求参数不正确，请检查输入后重试。'],
  ])('maps status %s without exposing internal diagnostics', async (status, body, message) => {
    document.cookie = 'csrftoken=test-token'
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status })))
    await expect(workspaceRequest('/smart-channels/resolve/', { method: 'POST', body: { url: 'http://localhost/rss' } }))
      .rejects.toMatchObject({ status, message })
  })
  it('keeps a network failure distinct from authentication errors', async () => {
    document.cookie = 'csrftoken=test-token'
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    try { await workspaceRequest('/smart-channels/resolve/', { method: 'POST', body: {} }) }
    catch (error) { expect(workspaceError(error)).toBe('操作未完成，请检查网络后重试。'); return }
    throw new Error('Expected network failure')
  })
  it('never accepts executable or credential-bearing profile links', () => {
    expect(safeExternalUrl('javascript:alert(1)')).toBeUndefined()
    expect(safeExternalUrl('https://token:secret@example.org')).toBeUndefined()
    expect(safeExternalUrl('https://example.org/feed')).toBe('https://example.org/feed')
  })
  it('performs public GET without initializing a session or making AI writes', async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ sources: [] }), { status: 200 }))
    vi.stubGlobal('fetch', fetcher)
    await workspaceRequest('/smart-channels/catalog/')
    expect(fetcher).toHaveBeenCalledTimes(1)
    expect(fetcher.mock.calls[0][0]).toBe('/api/smart-channels/catalog/')
    expect(fetcher.mock.calls[0][1].method).toBe('GET')
  })
  it('sends CSRF and an account fence for a mutation', async () => {
    document.cookie = 'csrftoken=test-token'
    setWorkspaceViewer(12)
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200 }))
    vi.stubGlobal('fetch', fetcher)
    await workspaceRequest('/me/smart-channels/settings/', { method: 'PATCH', body: { mode: 'suggest' } })
    expect(fetcher.mock.calls[0][1].headers).toMatchObject({ 'X-CSRFToken': 'test-token', 'X-Workspace-Viewer': '12' })
  })
  it('blocks an account change while initializing CSRF', async () => {
    setWorkspaceViewer(1)
    const fetcher = vi.fn().mockImplementation(async () => { setWorkspaceViewer(2); return new Response('{}', { status: 200 }) })
    vi.stubGlobal('fetch', fetcher)
    await expect(workspaceRequest('/me/smart-channels/settings/', { method: 'PATCH', body: { mode: 'auto' } })).rejects.toMatchObject({ status: 409 })
    expect(fetcher).toHaveBeenCalledTimes(1)
  })
  it('surfaces conflict responses and handles no-content responses', async () => {
    document.cookie = 'csrftoken=test-token'
    vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({ detail: '预览已过期' }), { status: 409 })).mockResolvedValueOnce(new Response(null, { status: 204 })))
    await expect(workspaceRequest('/me/smart-channels/proposals/x/apply/', { method: 'POST', body: {} })).rejects.toBeInstanceOf(WorkspaceError)
    await expect(workspaceRequest('/me/reading-stats/', { method: 'DELETE' })).resolves.toBeUndefined()
  })
})
