import { ArrowLeft, ArrowUpRight, Bot, Cloud, Server, Check, Plus, RefreshCw, Settings2, ShieldCheck } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { ModelCombobox } from '@/components/ui/model-combobox'
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import './aiConnections.css'
import { useAuth } from '@/context/AuthContext'
import AuthModal from '@/components/AuthModal'
import WorkspaceModal from '@/components/workspace/WorkspaceModal'
import AIModelsManager from '@/components/workspace/AIModelsManager'
import AITaskPreferencesSection from '@/components/workspace/AITaskPreferencesSection'
import { ConnectionRequestError, createAIConnection, deleteAIConnection, listAIConnections, listAIProviders,
  patchAIConnection, replaceAIConnectionKey, type AIAuthMode, type AIConnection, type AIProviderProfile } from '@/services/aiConnectionsApi'

type Editor = { kind: 'create' } | { kind: 'rename' | 'key' | 'delete'; connection: AIConnection }
function errorMessage(error: unknown) {
  return error instanceof ConnectionRequestError ? error.message : '操作结果未确认，请重新读取连接状态。'
}
export default function AIModelSettingsPage() {
  const { user, loading } = useAuth()
  const [login, setLogin] = useState(false)
  if (loading) return <p role="status" className="workspace-empty">正在读取账号…</p>
  if (!user) return <section className="workspace-empty"><h1>个人 AI 连接</h1><p>登录后管理自己的服务商连接。</p>
    <Button type="button" size="sm" onClick={() => setLogin(true)}>登录</Button>
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
  const [modelsRevision, setModelsRevision] = useState(0)
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
  return <div className="workspace-page ai-settings-page min-w-0 break-words">
    <Link to="/settings" className="mb-6 inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground"><ArrowLeft className="size-4" />返回设置</Link>
    <header className="mb-6 flex flex-wrap items-start justify-between gap-4">
      <div><div className="mb-2 flex items-center gap-2 text-xs font-medium tracking-wide text-primary"><Bot className="size-4" />你的 AI 工作空间</div>
        <h1 className="text-3xl font-semibold tracking-tight">个人 AI 连接</h1><p className="mt-2 text-sm text-muted-foreground">连接常用模型，为阅读、翻译与研究设置默认助手。</p></div>
      <div className="flex flex-wrap gap-2">
        <Button variant="outline" asChild><Link to="/settings/ai/usage">查看使用记录<ArrowUpRight /></Link></Button>
        <Button disabled={!data?.providers.length || loading || busy || data.connections.length >= 20} onClick={() => setEditor({ kind: 'create' })}><Plus />新增连接</Button>
      </div>
    </header>
    <div className="ai-setup-steps mb-7 grid gap-3 rounded-xl border bg-card p-4 sm:grid-cols-3">
      {['添加服务商连接', '添加并验证模型', '设置默认用途'].map((label, index) => <div key={label} className="flex items-center gap-3 text-sm"><span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-secondary text-xs font-semibold text-primary">{index + 1}</span>{label}</div>)}
    </div>
    {loading && <p role="status">正在读取连接…</p>}
    {error && <p role="alert" className="workspace-error">{error}</p>}
    {notice && <p role="status" className="workspace-notice">{notice}</p>}
    <div className="mb-4 flex items-center justify-between"><div className="flex items-center gap-2"><h2 className="text-base font-semibold">服务商连接</h2><Badge variant="secondary">{data?.connections.length ?? 0}</Badge></div>
      <Button variant="ghost" size="sm" disabled={loading || busy} onClick={reload}><RefreshCw className={loading ? 'animate-spin' : ''} />重新读取连接</Button></div>
    {!loading && !data && <p role="status">连接状态未知。重新读取成功前，不允许修改或再次提交 Key。</p>}
    {data && !data.connections.length && <p className="workspace-empty">尚无个人 AI 连接。可新增多个连接，保存后仍需配置模型与用途。</p>}
    <div className="grid min-w-0 gap-5">{data && [...data.connections].sort((a, b) => Number(b.is_enabled) - Number(a.is_enabled)).map(connection => <section key={connection.id} aria-label={connection.display_name}>
      <Card className={`ai-connection-card gap-0 overflow-hidden py-0 shadow-none ${connection.is_enabled ? '' : 'ai-connection-inactive'}`}>
        <div className="grid min-w-0 lg:grid-cols-[250px_minmax(0,1fr)]">
          <div className="flex flex-col gap-4 border-b bg-secondary/20 p-5 lg:border-r lg:border-b-0">
            <div className="flex items-start gap-3"><span className="flex size-10 shrink-0 items-center justify-center rounded-xl border bg-background text-primary"><Bot className="size-5" /></span>
              <div className="min-w-0"><h2 className="break-words text-base font-semibold">{connection.display_name}</h2><p className="mt-1 text-xs text-muted-foreground">{connection.provider_name}</p></div></div>
            <div className="flex items-center gap-2"><Badge variant={connection.is_enabled ? 'secondary' : 'outline'}>{connection.is_enabled ? '已启用' : '已停用'}</Badge><span className="font-mono text-xs text-muted-foreground">{connection.auth_mode === 'none' ? '无需 Key' : connection.masked_key}</span></div>
            <p className="text-xs leading-relaxed text-muted-foreground">{connection.region_name === '当前受信默认路由' ? '默认 API 线路' : connection.region_name}</p>
            <div className="flex flex-wrap gap-1">
              <Button variant="outline" size="sm" disabled={busy || loading} onClick={() => void mutate(signal => patchAIConnection(connection, { is_enabled: !connection.is_enabled }, viewer, signal))}>{connection.is_enabled ? '停用' : '启用'}</Button>
              <Button variant="ghost" size="sm" disabled={busy || loading} onClick={() => setEditor({ kind: 'rename', connection })}>修改名称</Button>
              {connection.auth_mode !== 'none' && <Button variant="ghost" size="sm" disabled={busy || loading} onClick={() => setEditor({ kind: 'key', connection })}>替换 Key</Button>}
              <Button variant="ghost" size="sm" className="text-muted-foreground hover:text-destructive" disabled={busy || loading} onClick={() => setEditor({ kind: 'delete', connection })}>删除连接</Button>
            </div>
            <p className="mt-auto flex items-start gap-2 text-[11px] leading-relaxed text-muted-foreground"><ShieldCheck className="mt-0.5 size-3.5 shrink-0" />Key 加密保存，仅当前账号可使用。</p>
          </div>
          <div className="min-w-0 p-5"><AIModelsManager key={connection.id} connection={connection} viewer={viewer} onModelsChanged={() => setModelsRevision(value => value + 1)} /></div>
        </div>
      </Card>
    </section>)}</div>
    {data && <AITaskPreferencesSection viewer={viewer} connections={data.connections} refreshToken={modelsRevision} />}
    <p className="mt-5 flex items-start gap-2 text-xs leading-relaxed text-muted-foreground"><Settings2 className="mt-0.5 size-4 shrink-0" />保存配置不会调用模型。主动测试、问答、翻译与研究可能产生服务商费用。</p>
    {editor && data && <ConnectionEditor key={editor.kind + ('connection' in editor ? editor.connection.id : '')}
      editor={editor} profiles={data.providers} busy={busy} onClose={() => setEditor(null)}
      onSave={(name, profile, key, requestId, authMode) => {
        if (editor.kind === 'create' && profile) void mutate(signal => createAIConnection({ provider_id: profile.provider_id, endpoint_profile: profile.profile_id,
          display_name: name, request_id: requestId, ...(authMode === 'none' ? { auth_mode: 'none' as const } : { auth_mode: 'api_key' as const, api_key: key }) }, viewer, signal))
        else if (editor.kind === 'rename') void mutate(signal => patchAIConnection(editor.connection, { display_name: name }, viewer, signal))
        else if (editor.kind === 'key') void mutate(signal => replaceAIConnectionKey(editor.connection, key, viewer, signal))
        else if (editor.kind === 'delete') void mutate(signal => deleteAIConnection(editor.connection, viewer, signal))
      }} />}
  </div>
}

function ConnectionEditor({ editor, profiles, busy, onClose, onSave }: {
  editor: Editor; profiles: AIProviderProfile[]; busy: boolean; onClose: () => void
  onSave: (name: string, profile: AIProviderProfile | undefined, key: string, requestId: string, authMode: AIAuthMode) => void
}) {
  const [name, setName] = useState('connection' in editor ? editor.connection.display_name : '')
  const [profileId, setProfileId] = useState(profiles.find(profile => profile.provider_id === 'deepseek')?.profile_id ?? profiles[0]?.profile_id ?? '')
  const [apiKey, setApiKey] = useState('')
  const [mode, setMode] = useState<AIAuthMode | null>(null)
  const profile = profiles.find(profile => profile.profile_id === profileId)
  const modes = profile?.auth_modes ?? ['api_key']
  const authMode = mode && modes.includes(mode) ? mode : modes[0]
  const [requestId] = useState(() => crypto.randomUUID())
  const isLocal = (item: AIProviderProfile) => item.network_zone === 'same_host' || item.network_zone === 'trusted_private'
  const local = profile ? isLocal(profile) : false
  const categoryProfiles = profiles.filter(item => isLocal(item) === local)
  const providers = [...new Map(categoryProfiles.map(item => [item.provider_id, item.provider_name])).entries()]
  const endpoints = categoryProfiles.filter(item => item.provider_id === profile?.provider_id)
  const selectProfile = (next: AIProviderProfile | undefined) => {
    if (!next) return
    setProfileId(next.profile_id); setMode(null); setApiKey('')
  }
  const routeLabel = (item: AIProviderProfile) => item.region_name === '当前受信默认路由' ? '默认线路' : item.region_name
  const needsKey = editor.kind === 'key' || editor.kind === 'create' && authMode === 'api_key'
  const needsName = editor.kind === 'create' || editor.kind === 'rename'
  const title = { create: '新增连接', rename: '修改连接名称', key: '替换连接 Key', delete: '确认删除连接' }[editor.kind]
  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (busy) return
    const key = apiKey
    setApiKey('')
    onSave(name.trim(), profile, key, requestId, authMode)
  }
  return <WorkspaceModal title={title} busy={busy} onClose={onClose} className="ai-connection-modal"><form className="ai-connection-form grid min-w-0 gap-5" onSubmit={submit}>
    {editor.kind === 'delete' ? <p>删除后将清除本连接 Key，并撤销旧授权版本；不会删除已经保存的历史内容。</p> : <p className="ai-connection-intro">连接你的模型服务，用于阅读、翻译与研究。</p>}
    {editor.kind === 'create' && <>
      <fieldset className="ai-access-types"><legend>接入方式</legend><div className="ai-access-options">
        {[false, true].map(value => <Button type="button" variant="outline" className="ai-access-card" key={String(value)} aria-pressed={local === value}
          disabled={busy || !profiles.some(item => isLocal(item) === value)}
          onClick={() => selectProfile(profiles.find(item => isLocal(item) === value))}>
          <span className="ai-access-card-icon">{value ? <Server size={19} /> : <Cloud size={19} />}</span>
          <span className="ai-access-card-copy"><strong>{value ? '本地与自建服务' : '云端 API'}</strong>
            <span>{value ? 'Ollama 或自建模型服务' : '使用服务商提供的 API Key'}</span></span>
          {local === value && <Check size={15} className="ai-access-card-check" />}

        </Button>)}
      </div></fieldset>
      <div className="ai-connection-fields"><label>服务商<ModelCombobox label="服务商" value={profile?.provider_id ?? ''} disabled={busy}
        searchLabel="搜索服务商" searchPlaceholder="搜索服务商名称或标识…" emptyText="没有匹配的服务商。"
        onChange={value => selectProfile(categoryProfiles.find(item => item.provider_id === value))}
        options={providers.map(([id, label]) => ({ value: id, label: id === 'ollama' && !local ? 'Ollama Cloud' : label }))} /></label>
      <label>连接线路<ModelCombobox label="连接线路" value={profileId} disabled={busy || endpoints.length === 1}
        searchLabel="搜索连接线路" searchPlaceholder="搜索线路名称或标识…" emptyText="没有匹配的连接线路。"
        onChange={value => selectProfile(endpoints.find(item => item.profile_id === value))}
        options={endpoints.map(item => ({ value: item.profile_id, label: routeLabel(item), description: undefined }))} /></label></div>
      <div className="ai-endpoint-note"><strong>{profile?.provider_name} · {profile && routeLabel(profile)}</strong>
        <p>{profile?.data_destination_label ?? '请求发送至所选服务商。'}</p>
        {local && <p>仅显示管理员已授权的地址。本地 Ollama 也可能运行云端模型，请按所选模型确认。</p>}
      </div>
      {modes.length > 1 ? <label>认证方式<ModelCombobox label="认证方式" value={authMode} disabled={busy}
        searchLabel="搜索认证方式" searchPlaceholder="搜索认证方式…" emptyText="没有匹配的认证方式。"
        onChange={value => { setMode(value as AIAuthMode); setApiKey('') }}
        options={modes.map(value => ({ value, label: value === 'none' ? '无需 Key（管理员授权）' : 'API Key' }))} /></label>
        : authMode === 'none' ? <p className="workspace-caption">此地址已授权，无需填写 API Key。</p> : null}
    </>}
    {needsName && <label>连接名称<Input value={name} disabled={busy} maxLength={64} required autoComplete="off" onChange={event => setName(event.target.value)} placeholder={`例如：我的 ${profile?.provider_name ?? 'AI'}${local ? ' 本地服务' : ''}`} /></label>}
    {needsKey && <label>API Key<Input type="password" value={apiKey} disabled={busy} minLength={8} maxLength={4096} required autoComplete="new-password" spellCheck={false} onChange={event => setApiKey(event.target.value)} /></label>}
    <p className="ai-connection-security"><ShieldCheck size={14} />Key 加密保存，不会回显。保存连接不会调用模型。</p>
    <footer className="workspace-modal-actions"><Button type="button" variant="outline" size="sm" disabled={busy} onClick={onClose}>取消</Button>
      <Button size="sm" disabled={busy || (needsName && !name.trim()) || (needsKey && apiKey.length < 8)}>{busy ? '正在保存…' : editor.kind === 'delete' ? '确认删除' : '保存连接'}</Button></footer>
  </form></WorkspaceModal>
}
