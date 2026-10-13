import { afterEach, describe, expect, it, vi } from 'vitest'
import { safeExternalUrl, setWorkspaceViewer, workspaceRequest, WorkspaceError } from '@/services/workspaceApi'

afterEach(() => { vi.unstubAllGlobals(); setWorkspaceViewer(null); document.cookie = 'csrftoken=; Max-Age=0' })

describe('workspace transport', () => {
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
