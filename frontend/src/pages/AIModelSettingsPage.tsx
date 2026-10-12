import { useState } from 'react'
import { ArrowLeft, KeyRound, RotateCcw, ShieldCheck, Trash2 } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useAuth } from '@/context/AuthContext'
import { fetchAIConnections, fetchAIProviderProfiles, createAIConnection, deleteAIConnection, replaceAIConnectionKey, updateAIConnection } from '@/services/api'
import type { CreateAIConnectionInput } from '@/services/api'

const CONNECTIONS_KEY = 'aiConnections'

export default function AIModelSettingsPage() {
  const { user, loading: authLoading } = useAuth()
  if (authLoading) {
    return <section className="mx-auto max-w-3xl px-4 py-16" role="status">正在确认登录状态…</section>
  }
  if (!user) {
    return (
      <section className="mx-auto w-full max-w-3xl px-4 pb-12 pt-6 sm:pt-10">
        <Link to="/settings" className="inline-flex min-h-11 items-center gap-2 text-sm text-muted-foreground"><ArrowLeft aria-hidden="true" className="size-4" />返回设置</Link>
        <div className="mt-6 rounded-2xl border border-border bg-card p-6">
          <h1 className="text-2xl font-semibold">AI 模型与密钥</h1>
          <p className="mt-3 text-sm text-muted-foreground">登录后可管理只属于你的网站账号的 API Key。Key 不会写入浏览器存储。</p>
          <Link to="/settings" className="mt-5 inline-flex min-h-11 items-center rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground">返回账号设置</Link>
        </div>
      </section>
    )
  }

  return <AIModelSettingsForUser key={user.id} userId={user.id} />
}

function AIModelSettingsForUser({ userId }: { userId: number }) {
  const queryClient = useQueryClient()
  const [selectedProfile, setSelectedProfile] = useState('deepseek_default')
  const [displayName, setDisplayName] = useState('')
  const [newApiKey, setNewApiKey] = useState('')
  const [replaceFor, setReplaceFor] = useState<string | null>(null)
  const [replacementKey, setReplacementKey] = useState('')
  const [renameFor, setRenameFor] = useState<string | null>(null)
  const [renameValue, setRenameValue] = useState('')
  const [notice, setNotice] = useState('')

  const providersQuery = useQuery({
    queryKey: ['aiProviderProfiles'],
    queryFn: ({ signal }) => fetchAIProviderProfiles(signal),
    staleTime: 5 * 60_000,
    retry: false,
  })
  const connectionsQuery = useQuery({
    queryKey: [CONNECTIONS_KEY, userId],
    queryFn: ({ signal }) => fetchAIConnections(signal),
    retry: false,
  })

  const profiles = providersQuery.data ?? []
  const selectedEndpoint = profiles.find((profile) => profile.profile_id === selectedProfile) ?? profiles[0]
  const connections = connectionsQuery.data ?? []
  const loading = providersQuery.isPending || connectionsQuery.isPending
  const providerError = providersQuery.isError || connectionsQuery.isError
  const refreshConnections = () => queryClient.invalidateQueries({ queryKey: [CONNECTIONS_KEY, userId] })
  const createMutation = useMutation({
    mutationFn: (input: CreateAIConnectionInput) => createAIConnection(input),
    onSuccess: async () => {
      setNewApiKey('')
      setDisplayName('')
      setNotice('连接已安全保存。本站尚未测试此 Key。')
      await refreshConnections()
    },
    onError: () => setNotice('保存失败。请检查填写内容后重试。'),
  })
  const replaceMutation = useMutation({
    mutationFn: ({ connectionId, apiKey }: { connectionId: string; apiKey: string }) => replaceAIConnectionKey(connectionId, apiKey),
    onSuccess: async () => {
      setReplacementKey('')
      setReplaceFor(null)
      setNotice('Key 已替换，旧凭据版本已失效。本站尚未测试新 Key。')
      await refreshConnections()
    },
    onError: () => setNotice('替换失败。请检查填写内容后重试。'),
  })
  const renameMutation = useMutation({
    mutationFn: ({ connectionId, displayName }: { connectionId: string; displayName: string }) => updateAIConnection(connectionId, { display_name: displayName }),
    onSuccess: async () => {
      setRenameFor(null)
      setRenameValue('')
      setNotice('连接名称已更新。')
      await refreshConnections()
    },
    onError: () => setNotice('名称更新失败，请重试。'),
  })
  const toggleMutation = useMutation({
    mutationFn: ({ connectionId, isEnabled }: { connectionId: string; isEnabled: boolean }) => updateAIConnection(connectionId, { is_enabled: isEnabled }),
    onSuccess: async (_connection, variables) => {
      setNotice(variables.isEnabled ? '连接已启用。' : '连接已停用，旧凭据版本已失效。')
      await refreshConnections()
    },
    onError: () => setNotice('状态更新失败，请重试。'),
  })
  const deleteMutation = useMutation({
    mutationFn: (connectionId: string) => deleteAIConnection(connectionId),
    onSuccess: async () => {
      setNotice('连接已删除，站点已清除保存的密文。')
      await refreshConnections()
    },
    onError: () => setNotice('删除失败，请重试。'),
  })

  return (
    <section className="mx-auto w-full max-w-3xl px-4 pb-12 pt-6 sm:pt-10">
      <Link to="/settings" className="inline-flex min-h-11 items-center gap-2 rounded-md text-sm text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
        <ArrowLeft aria-hidden="true" className="size-4" />返回设置
      </Link>
      <header className="mb-7 mt-4">
        <p className="text-sm font-medium text-orange-600">个人 API Key</p>
        <h1 className="mt-1 text-3xl font-semibold tracking-tight">AI 模型与密钥</h1>
        <p className="mt-2 text-sm leading-6 text-muted-foreground">Key 由本站后端加密保存。保存、查看或停用连接都不会调用服务商；每项连接目前都标为“未测试”。</p>
      </header>

      {notice && <p className="mb-5 rounded-lg border border-border bg-muted/40 p-3 text-sm" role="status">{notice}</p>}

      <section aria-labelledby="add-ai-connection" className="rounded-2xl border border-border bg-card p-5 sm:p-6">
        <h2 id="add-ai-connection" className="text-lg font-semibold">添加服务商连接</h2>
        <p className="mt-1 text-sm text-muted-foreground">请选择受信服务商和地域。服务端固定目标端点，不接受自定义 URL。</p>

        {loading ? <p className="mt-5 text-sm text-muted-foreground" role="status">正在读取连接信息…</p> : providerError ? (
          <p className="mt-5 text-sm text-destructive" role="alert">连接信息暂不可用，请稍后重试。</p>
        ) : (
          <form
            className="mt-5 space-y-4"
            onSubmit={(event) => {
              event.preventDefault()
              if (!selectedEndpoint || !newApiKey || createMutation.isPending) return
              setNotice('')
              createMutation.mutate({
                provider_id: selectedEndpoint.provider_id,
                endpoint_profile: selectedEndpoint.profile_id,
                display_name: displayName,
                api_key: newApiKey,
              })
            }}
          >
            <label className="block space-y-2 text-sm font-medium">
              <span>服务商与地域</span>
              <select
                value={selectedEndpoint?.profile_id ?? ''}
                onChange={(event) => setSelectedProfile(event.target.value)}
                className="h-11 w-full rounded-md border border-input bg-background px-3 text-sm"
                required
              >
                {profiles.map((profile) => <option key={profile.profile_id} value={profile.profile_id}>{profile.provider_name} · {profile.region_name}</option>)}
              </select>
            </label>
            {selectedEndpoint && <p className="break-all text-xs text-muted-foreground">固定官方端点：{selectedEndpoint.base_url}</p>}
            <label className="block space-y-2 text-sm font-medium">
              <span>连接名称（可选）</span>
              <Input value={displayName} onChange={(event) => setDisplayName(event.target.value)} maxLength={64} autoComplete="off" placeholder={selectedEndpoint ? `${selectedEndpoint.provider_name} · 个人` : '我的连接'} />
            </label>
            <label className="block space-y-2 text-sm font-medium">
              <span>API Key</span>
              <Input type="password" value={newApiKey} onChange={(event) => setNewApiKey(event.target.value)} maxLength={4096} autoComplete="new-password" spellCheck={false} required />
            </label>
            <Button type="submit" className="min-h-11" disabled={!selectedEndpoint || !newApiKey || createMutation.isPending}>
              <KeyRound aria-hidden="true" />{createMutation.isPending ? '正在安全保存…' : '保存连接'}
            </Button>
          </form>
        )}
      </section>

      <section aria-labelledby="saved-ai-connections" className="mt-6 rounded-2xl border border-border bg-card p-5 sm:p-6">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 id="saved-ai-connections" className="text-lg font-semibold">已保存的连接</h2>
            <p className="mt-1 text-sm text-muted-foreground">连接列表来自你的登录账号；Key 始终只显示掩码。</p>
          </div>
          <Button type="button" variant="outline" className="min-h-11" onClick={() => void refreshConnections()} disabled={connectionsQuery.isFetching}>
            <RotateCcw aria-hidden="true" />刷新
          </Button>
        </div>

        {loading ? <p className="mt-5 text-sm text-muted-foreground" role="status">正在读取连接信息…</p> : providerError ? null : connections.length === 0 ? (
          <p className="mt-5 rounded-xl bg-muted/40 p-4 text-sm text-muted-foreground">还没有保存的 API Key 连接。</p>
        ) : (
          <ul className="mt-5 space-y-3">
            {connections.map((connection) => (
              <li key={connection.id} className="rounded-xl border border-border p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="font-medium">{connection.display_name}</p>
                    <p className="mt-1 text-sm text-muted-foreground">{connection.provider_name} · {connection.region_name}</p>
                    <p className="mt-2 flex items-center gap-2 text-sm"><span aria-label="掩码 Key">{connection.masked_key}</span><span className="text-muted-foreground">{connection.key_saved ? '已保存' : '未保存'}</span></p>
                    <p className="mt-1 flex items-center gap-2 text-xs text-muted-foreground"><ShieldCheck aria-hidden="true" className="size-3.5" />未测试 · 保存连接不会调用服务商</p>
                    <p className="mt-1 text-xs text-muted-foreground">{connection.is_enabled ? '已启用' : '已停用'}</p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Button type="button" variant="outline" className="min-h-11" onClick={() => { setRenameFor(connection.id); setRenameValue(connection.display_name); setNotice('') }}>
                      修改名称
                    </Button>
                    <Button type="button" variant="outline" className="min-h-11" onClick={() => { setReplaceFor(connection.id); setReplacementKey(''); setNotice('') }}>
                      替换 Key
                    </Button>
                    <Button type="button" variant="outline" className="min-h-11" disabled={toggleMutation.isPending} onClick={() => toggleMutation.mutate({ connectionId: connection.id, isEnabled: !connection.is_enabled })}>
                      {connection.is_enabled ? '停用' : '启用'}
                    </Button>
                    <Button type="button" variant="destructive" className="min-h-11" disabled={deleteMutation.isPending} onClick={() => {
                      if (window.confirm('删除后本站会清除此连接的密文。已完成的历史内容不会删除。')) deleteMutation.mutate(connection.id)
                    }}>
                      <Trash2 aria-hidden="true" />删除
                    </Button>
                  </div>
                </div>

                {renameFor === connection.id && <form className="mt-4 space-y-3 border-t border-border pt-4" onSubmit={(event) => {
                  event.preventDefault()
                  if (!renameValue.trim() || renameMutation.isPending) return
                  setNotice('')
                  renameMutation.mutate({ connectionId: connection.id, displayName: renameValue })
                }}>
                  <label className="block space-y-2 text-sm font-medium">
                    <span>连接名称</span>
                    <Input value={renameValue} onChange={(event) => setRenameValue(event.target.value)} maxLength={64} autoComplete="off" required />
                  </label>
                  <div className="flex flex-wrap gap-2">
                    <Button type="submit" className="min-h-11" disabled={!renameValue.trim() || renameMutation.isPending}>{renameMutation.isPending ? '正在保存…' : '保存名称'}</Button>
                    <Button type="button" variant="outline" className="min-h-11" onClick={() => { setRenameFor(null); setRenameValue('') }}>取消</Button>
                  </div>
                </form>}

                {replaceFor === connection.id && <form className="mt-4 space-y-3 border-t border-border pt-4" onSubmit={(event) => {
                  event.preventDefault()
                  if (!replacementKey || replaceMutation.isPending) return
                  setNotice('')
                  replaceMutation.mutate({ connectionId: connection.id, apiKey: replacementKey })
                }}>
                  <label className="block space-y-2 text-sm font-medium">
                    <span>输入新的 API Key</span>
                    <Input type="password" value={replacementKey} onChange={(event) => setReplacementKey(event.target.value)} maxLength={4096} autoComplete="new-password" spellCheck={false} required />
                  </label>
                  <div className="flex flex-wrap gap-2">
                    <Button type="submit" className="min-h-11" disabled={!replacementKey || replaceMutation.isPending}>{replaceMutation.isPending ? '正在替换…' : '确认替换'}</Button>
                    <Button type="button" variant="outline" className="min-h-11" onClick={() => { setReplaceFor(null); setReplacementKey('') }}>取消</Button>
                  </div>
                </form>}
              </li>
            ))}
          </ul>
        )}
      </section>
    </section>
  )
}
