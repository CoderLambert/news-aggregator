import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '@/context/AuthContext'
import AuthModal from '@/components/AuthModal'
import WorkspaceModal from '@/components/workspace/WorkspaceModal'
import { ConnectionRequestError, createAIConnection, deleteAIConnection, listAIConnections, listAIProviders,
  patchAIConnection, replaceAIConnectionKey, type AIConnection, type AIProviderProfile } from '@/services/aiConnectionsApi'

type Editor = { kind: 'create' } | { kind: 'rename' | 'key' | 'delete'; connection: AIConnection }
function errorMessage(error: unknown) {
  return error instanceof ConnectionRequestError ? error.message : '操作结果未确认，请重新读取连接状态。'
}
export default function AIModelSettingsPage() {
  const { user, loading } = useAuth()
  const [login, setLogin] = useState(false)
  if (loading) return <p role="status" className="workspace-empty">正在读取账号…</p>
  if (!user) return <section className="workspace-empty"><h1>个人 AI 连接</h1><p>登录后管理自己的服务商连接。</p>
    <button type="button" className="workspace-button" onClick={() => setLogin(true)}>登录</button>
    {login && <AuthModal onClose={() => setLogin(false)} />}</section>
  return <AIConnectionsManager key={user.id} viewer={user.id} />
}

export function AIConnectionsManager({ viewer }: { viewer: number }) {
  const [data, setData] = useState<{ providers: AIProviderProfile[]; connections: AIConnection[] } | null>(null)
  const [loading, setLoading] = useState(true)
  const [attempt, setAttempt] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [editor, setEditor] = useState<Editor | null>(null)
  const lifetime = useRef<AbortController | null>(null)
  const writing = useRef(false)
  useEffect(() => {
    const controller = new AbortController()
    lifetime.current = controller
    void Promise.all([listAIProviders(controller.signal), listAIConnections(controller.signal)])
      .then(([providers, connections]) => { if (!controller.signal.aborted) setData({ providers, connections }) })
      .catch(reason => { if (!controller.signal.aborted) { setData(null); setError(errorMessage(reason)) } })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => { controller.abort(); lifetime.current = null }
  }, [viewer, attempt])
  const reload = () => {
    if (loading || writing.current) return
    setLoading(true); setError(''); setNotice(''); setAttempt(value => value + 1)
  }
  const mutate = async (operation: (signal: AbortSignal) => Promise<unknown>) => {
    const controller = lifetime.current
    if (!controller || controller.signal.aborted || writing.current || !data) return
    writing.current = true; setBusy(true); setError(''); setNotice('')
    try {
      await operation(controller.signal)
      if (controller.signal.aborted) return
      const connections = await listAIConnections(controller.signal)
      if (controller.signal.aborted) return
      setData(current => current ? { ...current, connections } : current)
      setEditor(null)
      setNotice('连接状态已更新；保存或启用不代表模型能力已验证。')
    } catch (reason) {
      if (controller.signal.aborted) return
      // A lost write response is reconciled by GET, never by replaying a Key.
      setData(null); setEditor(null); setError(errorMessage(reason))
    } finally {
      writing.current = false
      if (!controller.signal.aborted) setBusy(false)
    }
  }
  return <div className="workspace-page min-w-0 break-words">
    <Link to="/settings" className="workspace-link">返回设置</Link>
    <header className="workspace-page-heading"><div><h1>个人 AI 连接</h1><p>分别保存和管理多家服务商的 Key；名称、启停、替换和删除均只影响当前账号。</p></div></header>
    <p className="workspace-soft-panel">本页是唯一个人 API Key 设置入口，不发送模型请求。模型录入、能力测试与用途选择将在下一阶段提供；尚未配置完成时个人调用失败关闭。</p>
    {loading && <p role="status">正在读取连接…</p>}
    {error && <p role="alert" className="workspace-error">{error}</p>}
    {notice && <p role="status" className="workspace-notice">{notice}</p>}
    <div className="workspace-actions"><button type="button" className="workspace-button secondary" disabled={loading || busy} onClick={reload}>重新读取连接</button>
      <button type="button" className="workspace-button" disabled={!data?.providers.length || loading || busy || data.connections.length >= 20} onClick={() => setEditor({ kind: 'create' })}>新增连接</button></div>
    {!loading && !data && <p role="status">连接状态未知。重新读取成功前，不允许修改或再次提交 Key。</p>}
    {data && !data.connections.length && <p className="workspace-empty">尚无个人 AI 连接。可新增多个连接，保存后仍需配置模型与用途。</p>}
    <div className="grid min-w-0 gap-4 sm:grid-cols-2">{data?.connections.map(connection => <section className="workspace-panel min-w-0" key={connection.id} aria-label={connection.display_name}>
      <h2>{connection.display_name}</h2><p>{connection.provider_name} · {connection.region_name}</p>
      <p>{connection.masked_key} · {connection.is_enabled ? '已启用' : '已停用'} · 未测试</p>
      <p className="workspace-caption">更新时间：{new Date(connection.updated_at).toLocaleString()}</p>
      <div className="workspace-actions flex-wrap">
        <button type="button" className="workspace-button secondary" disabled={busy || loading} onClick={() => setEditor({ kind: 'rename', connection })}>修改名称</button>
        <button type="button" className="workspace-button secondary" disabled={busy || loading} onClick={() => void mutate(signal => patchAIConnection(connection, { is_enabled: !connection.is_enabled }, viewer, signal))}>{connection.is_enabled ? '停用' : '启用'}</button>
        <button type="button" className="workspace-button secondary" disabled={busy || loading} onClick={() => setEditor({ kind: 'key', connection })}>替换 Key</button>
        <button type="button" className="workspace-button danger" disabled={busy || loading} onClick={() => setEditor({ kind: 'delete', connection })}>删除连接</button>
      </div></section>)}</div>
    {editor && data && <ConnectionEditor key={editor.kind + ('connection' in editor ? editor.connection.id : '')}
      editor={editor} profiles={data.providers} busy={busy} onClose={() => setEditor(null)}
      onSave={(name, profile, key, requestId) => {
        if (editor.kind === 'create' && profile) void mutate(signal => createAIConnection({ provider_id: profile.provider_id, endpoint_profile: profile.profile_id,
          display_name: name, api_key: key, request_id: requestId }, viewer, signal))
        else if (editor.kind === 'rename') void mutate(signal => patchAIConnection(editor.connection, { display_name: name }, viewer, signal))
        else if (editor.kind === 'key') void mutate(signal => replaceAIConnectionKey(editor.connection, key, viewer, signal))
        else if (editor.kind === 'delete') void mutate(signal => deleteAIConnection(editor.connection, viewer, signal))
      }} />}
  </div>
}

function ConnectionEditor({ editor, profiles, busy, onClose, onSave }: {
  editor: Editor; profiles: AIProviderProfile[]; busy: boolean; onClose: () => void
  onSave: (name: string, profile: AIProviderProfile | undefined, key: string, requestId: string) => void
}) {
  const [name, setName] = useState('connection' in editor ? editor.connection.display_name : '')
  const [profileId, setProfileId] = useState(profiles.find(profile => profile.provider_id === 'deepseek')?.profile_id ?? profiles[0]?.profile_id ?? '')
  const [apiKey, setApiKey] = useState('')
  const [requestId] = useState(() => crypto.randomUUID())
  const needsKey = editor.kind === 'create' || editor.kind === 'key'
  const needsName = editor.kind === 'create' || editor.kind === 'rename'
  const title = { create: '新增连接', rename: '修改连接名称', key: '替换连接 Key', delete: '确认删除连接' }[editor.kind]
  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (busy) return
    const key = apiKey
    setApiKey('')
    onSave(name.trim(), profiles.find(profile => profile.profile_id === profileId), key, requestId)
  }
  return <WorkspaceModal title={title} busy={busy} onClose={onClose}><form className="grid min-w-0 gap-4" onSubmit={submit}>
    {editor.kind === 'delete' ? <p>删除后将清除本连接 Key，并撤销旧授权版本；不会删除已经保存的历史内容。</p> : <p>Key 只在本次提交中发送，保存后不会回显；连接操作不会调用模型。</p>}
    {editor.kind === 'create' && <label>服务商与受信端点<select className="max-w-full" value={profileId} disabled={busy} onChange={event => { setProfileId(event.target.value); setApiKey('') }}>
      {profiles.map(profile => <option key={profile.profile_id} value={profile.profile_id}>{profile.provider_name} · {profile.region_name}</option>)}</select></label>}
    {needsName && <label>连接名称<input value={name} disabled={busy} maxLength={64} required autoComplete="off" onChange={event => setName(event.target.value)} placeholder="例如：个人 DeepSeek" /></label>}
    {needsKey && <label>API Key<input type="password" value={apiKey} disabled={busy} minLength={8} maxLength={4096} required autoComplete="new-password" spellCheck={false} onChange={event => setApiKey(event.target.value)} /></label>}
    <footer className="workspace-modal-actions"><button type="button" className="workspace-button secondary" disabled={busy} onClick={onClose}>取消</button>
      <button className="workspace-button" disabled={busy || (needsName && !name.trim()) || (needsKey && apiKey.length < 8)}>{busy ? '正在保存…' : editor.kind === 'delete' ? '确认删除' : '保存连接'}</button></footer>
  </form></WorkspaceModal>
}
