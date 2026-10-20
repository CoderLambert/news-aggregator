import { beforeEach, describe, expect, it, vi } from 'vitest'
import { WorkspaceError, workspaceRequest } from '@/services/workspaceApi'
import { ConnectionRequestError, createAIConnection, patchAIConnection, replaceAIConnectionKey, deleteAIConnection, listAIConnections, listAIModels, listAIProviders, type AIConnection } from '@/services/aiConnectionsApi'
vi.mock('@/services/workspaceApi', async original => ({ ...await original<typeof import('@/services/workspaceApi')>(), workspaceRequest: vi.fn() }))
const request = vi.mocked(workspaceRequest)
const row = { id: 'connection-id', revision: 9 } as AIConnection
const modelConnection = { id: 'connection-id', provider_id: 'deepseek' } as AIConnection
beforeEach(() => {
  // A returned function is a cleanup hook; never return the request mock.
  request.mockReset().mockResolvedValue({ connections: [] })
})
describe('connection request boundary', () => {
  it('rejects unknown auth modes and contradictory no-Key state', async () => {
    for (const connection of [{ auth_mode: 'inherit', key_saved: true }, { auth_mode: 'none', key_saved: true }]) {
      request.mockResolvedValueOnce({ connections: [connection] })
      await expect(listAIConnections()).rejects.toBeInstanceOf(ConnectionRequestError)
    }
    request.mockResolvedValueOnce({ providers: [{ auth_modes: ['none', 'inherit'] }] })
    await expect(listAIProviders()).rejects.toBeInstanceOf(ConnectionRequestError)
  })
  it('cannot turn an unknown delivery mode into article-chat permission', async () => {
    request.mockResolvedValueOnce({ models: [{ id: 'unknown-model', article_chat_supported: true, delivery_mode: 'magic' }] })
    expect((await listAIModels(modelConnection))[0].article_chat_supported).toBe(false)
  })
  it('keeps unknown route and capability values unverified', async () => {
    request.mockResolvedValueOnce({ models: [{ id: 'unknown-model', has_trusted_route: 'true',
      article_chat_supported: true, stream_verified: 'yes', delivery_mode: 'streaming',
      capabilities: { text: true, tools: 'guessed' } }] })
    const model = (await listAIModels(modelConnection))[0]
    expect(model.has_trusted_route).toBe(false)
    expect(model.capabilities).toEqual({ text: 'unknown', tools: 'unknown' })
    expect(model.stream_verified).toBe(false)
    expect(model.article_chat_supported).toBe(false)
  })
  it('carries immutable expected revision and explicit viewer on every write', async () => {
    await patchAIConnection(row, { is_enabled: false }, 7)
    await replaceAIConnectionKey(row, 'synthetic-new-key', 7)
    await deleteAIConnection(row, 7)
    expect(request.mock.calls.map(([, options]) => [options?.viewer, (options?.body as { revision: number }).revision])).toEqual([[7, 9], [7, 9], [7, 9]])
  })
  it('never reflects a server error body containing the submitted secret', async () => {
    request.mockRejectedValue(new WorkspaceError('sk-synthetic-never-display', 400))
    const error = await createAIConnection({ provider_id: 'deepseek', endpoint_profile: 'deepseek_default', display_name: 'mine', api_key: 'sk-synthetic-never-display', request_id: 'synthetic-id' }, 7).catch(value => value)
    expect(error).toBeInstanceOf(ConnectionRequestError)
    expect(error.message).not.toContain('sk-synthetic')
    expect(request).toHaveBeenCalledOnce()
  })
  it('defaults missing article-chat capability to false while preserving legacy T02 metadata', async () => {
    const supported = { id: 'model-id', article_chat_supported: true, has_trusted_route: true,
      capabilities: { text: 'supported', tools: 'unknown' } }
    request.mockResolvedValueOnce({ models: [supported] })
    await expect(listAIModels(modelConnection)).resolves.toEqual([supported])
    request.mockResolvedValueOnce({ models: [{ id: 'legacy-t02-model' }] })
    await expect(listAIModels(modelConnection)).resolves.toEqual([
      { id: 'legacy-t02-model', article_chat_supported: false, has_trusted_route: false,
        capabilities: { text: 'unknown', tools: 'unknown' } },
    ])
    expect(request).toHaveBeenCalledTimes(2)
  })
  it('reads a list without sending any Key, mutation, or retry', async () => {
    await listAIConnections()
    expect(request).toHaveBeenCalledExactlyOnceWith('/me/ai/connections/', { signal: undefined })
  })
})
