import { useLayoutEffect, useRef, useState } from 'react'
import { ArrowLeft, KeyRound, RotateCcw, ShieldCheck, Trash2 } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import AITaskPreferencesSection from '@/components/ai/AITaskPreferencesSection'
import { useAuth } from '@/context/AuthContext'
import {
  fetchAIConnections,
  fetchAIProviderProfiles,
  fetchAIModelCatalog,
  fetchAIModels,
  createAIConnection,
  createAIModel,
  deleteAIConnection,
  deleteAIModel,
  replaceAIConnectionKey,
  testAIModel,
  updateAIConnection,
  updateAIModel,
} from '@/services/api'
import type { AIConnection, AIModelConfig, AIModelProbeKind, AIModelTestResult, CreateAIConnectionInput, CreateAIModelInput } from '@/services/api'

const CONNECTIONS_KEY = 'aiConnections'
const MODELS_KEY = 'aiModels'

function verificationLabel(status: AIModelConfig['verification_status']): string {
  if (status === 'verified') return '已测试成功'
  if (status === 'failed') return '最近测试失败'
  if (status === 'stale') return '配置已变化，测试结果过期'
  return '未测试'
}

type ProbeFeedbackState = 'pending' | 'succeeded' | 'failed' | 'unknown' | 'not_sent'

interface ProbeFeedback {
  state: ProbeFeedbackState
  message: string
}

interface ModelProbeRequest {
  modelId: string
  probeKind: AIModelProbeKind
  generation: number
  configIdentity: string
}

interface ProbeConfigSnapshot {
  models: AIModelConfig[]
  connections: AIConnection[]
}

interface ConfigChangeScope {
  modelIds: string[]
  connectionIds: string[]
}

const SAFE_PROBE_ERROR_MESSAGES: Record<string, ProbeFeedback> = {
  model_test_gateway_unavailable: { state: 'not_sent', message: '本次未发送：个人模型网关暂不可用，能力仍为“未测试”。' },
  model_test_route_unavailable: { state: 'not_sent', message: '本次未发送：该模型目前没有已批准的网关路由。' },
  endpoint_profile_unavailable: { state: 'not_sent', message: '本次未发送：服务商端点配置暂不可用。' },
  connection_unavailable: { state: 'not_sent', message: '本次未发送：连接暂不可用。' },
  connection_not_found: { state: 'not_sent', message: '本次未发送：连接不存在或已失效。' },
  model_not_found: { state: 'not_sent', message: '本次未发送：模型不存在或不可用。' },
  model_wrong_owner: { state: 'not_sent', message: '本次未发送：模型不属于当前账号。' },
  probe_kind_invalid: { state: 'not_sent', message: '本次未发送：测试类型无效。' },
  ai_byok_disabled: { state: 'not_sent', message: '本次未发送：个人模型功能当前未启用。' },
  authentication_required: { state: 'not_sent', message: '本次未发送：请先登录后再测试。' },
  gateway_unavailable: { state: 'not_sent', message: '本次未发送：个人模型网关暂不可用，能力仍为“未测试”。' },
  invalid_probe: { state: 'not_sent', message: '本次未发送：测试请求无效。' },
  gateway_rejected: { state: 'failed', message: '网关拒绝了本次测试。原始响应已隐藏；如需重试，请由你再次点击。' },
  probe_not_supported: { state: 'failed', message: '本次测试未能验证该能力，能力仍为未知。' },
  result_unknown: { state: 'unknown', message: '结果未确认；本站没有自动重试。请检查当前状态后再决定是否手动重试。' },
}

function probeFeedbackKey(modelId: string, probeKind: AIModelProbeKind): string {
  return `${modelId}:${probeKind}`
}

function probeConfigIdentity(modelId: string, snapshot: ProbeConfigSnapshot): string | null {
  const model = snapshot.models.find((candidate) => candidate.id === modelId)
  if (!model) return null
  const connection = snapshot.connections.find((candidate) => candidate.id === model.connection_id)
  if (!connection) return null

  // Credential versions are not exposed to the browser; configuration mutations advance the request generation instead.
  return JSON.stringify([
    model.id,
    model.connection_id,
    model.model_id,
    model.config_revision,
    connection.id,
    connection.provider_id,
    connection.endpoint_profile,
    connection.is_enabled,
  ])
}

function feedbackForProbeResult(result: AIModelTestResult, probeKind: AIModelProbeKind): ProbeFeedback {
  if (result.stale || result.status === 'stale') {
    return { state: 'unknown', message: '测试请求已返回，但模型配置期间发生变化；旧结果没有覆盖当前模型状态。' }
  }
  if (result.status === 'succeeded') {
    return { state: 'succeeded', message: probeKind === 'text' ? '文本能力测试成功。' : '工具调用能力测试成功。' }
  }
  if (result.status === 'unknown') {
    return SAFE_PROBE_ERROR_MESSAGES[result.safe_error_code] ?? {
      state: 'unknown', message: '结果未确认；本站没有自动重试。请检查当前状态后再决定是否手动重试。',
    }
  }
  if (result.status === 'not_sent') {
    return SAFE_PROBE_ERROR_MESSAGES[result.safe_error_code] ?? {
      state: 'not_sent', message: '本次未发送；能力仍为“未测试”。',
    }
  }
  return SAFE_PROBE_ERROR_MESSAGES[result.safe_error_code] ?? {
    state: 'failed', message: probeKind === 'text' ? '文本能力测试失败。' : '工具调用能力测试失败。',
  }
}

function feedbackForProbeError(error: unknown): ProbeFeedback {
  if (typeof error === 'object' && error !== null) {
    const record = error as Record<string, unknown>
    const response = typeof record.response === 'object' && record.response !== null
      ? record.response as Record<string, unknown>
      : null
    const data = response && typeof response.data === 'object' && response.data !== null
      ? response.data as Record<string, unknown>
      : null
    const errorCode = data && typeof data.error_code === 'string' ? data.error_code : ''
    if (errorCode && SAFE_PROBE_ERROR_MESSAGES[errorCode]) return SAFE_PROBE_ERROR_MESSAGES[errorCode]
    if (['ECONNABORTED', 'ETIMEDOUT', 'ERR_NETWORK'].includes(String(record.code))) {
      return { state: 'unknown', message: '请求超时或网络中断，无法确认是否到达服务商；本站没有自动重试。请先检查当前状态。' }
    }
  }
  return { state: 'unknown', message: '本次测试结果未确认；本站没有自动重试。请检查当前状态后再决定是否手动重试。' }
}

function ProbeTestButton({
  label,
  pendingLabel,
  feedback,
  disabled,
  onClick,
}: {
  label: string
  pendingLabel: string
  feedback?: ProbeFeedback
  disabled: boolean
  onClick: () => void
}) {
  const pending = feedback?.state === 'pending'
  const failed = feedback?.state === 'failed'
  return (
    <div className="flex min-w-0 flex-col items-start gap-1">
      <Button type="button" variant="outline" className="min-h-11" disabled={disabled} onClick={onClick}>
        {pending ? pendingLabel : label}
      </Button>
      {feedback && <p role={failed ? 'alert' : 'status'} aria-live="polite" className="max-w-64 text-xs leading-5 text-muted-foreground">{feedback.message}</p>}
    </div>
  )
}

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
  const [modelFormFor, setModelFormFor] = useState<string | null>(null)
  const [selectedCatalogModelId, setSelectedCatalogModelId] = useState('')
  const [modelIdDraft, setModelIdDraft] = useState('')
  const [modelDisplayName, setModelDisplayName] = useState('')
  const [editModelFor, setEditModelFor] = useState<string | null>(null)
  const [editModelId, setEditModelId] = useState('')
  const [editModelDisplayName, setEditModelDisplayName] = useState('')
  const [notice, setNotice] = useState('')
  const [probeFeedback, setProbeFeedback] = useState<Record<string, ProbeFeedback>>({})
  const [pendingModelChanges, setPendingModelChanges] = useState<Record<string, number>>({})
  const [pendingConnectionChanges, setPendingConnectionChanges] = useState<Record<string, number>>({})
  const probeGenerations = useRef(new Map<string, number>())
  const probeConfigSnapshot = useRef<ProbeConfigSnapshot>({ models: [], connections: [] })
  const pendingModelChangeCounts = useRef(new Map<string, number>())
  const pendingConnectionChangeCounts = useRef(new Map<string, number>())

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
  const modelCatalogQuery = useQuery({
    queryKey: ['aiModelCatalog'],
    queryFn: ({ signal }) => fetchAIModelCatalog(signal),
    staleTime: 5 * 60_000,
    retry: false,
  })
  const modelsQuery = useQuery({
    queryKey: [MODELS_KEY, userId],
    queryFn: ({ signal }) => fetchAIModels(signal),
    retry: false,
  })

  const profiles = providersQuery.data ?? []
  const selectedEndpoint = profiles.find((profile) => profile.profile_id === selectedProfile) ?? profiles[0]
  const connections = connectionsQuery.data ?? []
  const models = modelsQuery.data ?? []
  const modelPresets = modelCatalogQuery.data?.models ?? []
  const loading = providersQuery.isPending || connectionsQuery.isPending
  const providerError = providersQuery.isError || connectionsQuery.isError
  useLayoutEffect(() => {
    probeConfigSnapshot.current = {
      models: modelsQuery.data ?? [],
      connections: connectionsQuery.data ?? [],
    }
  }, [modelsQuery.data, connectionsQuery.data])
  const refreshConnections = () => queryClient.invalidateQueries({ queryKey: [CONNECTIONS_KEY, userId] })
  const refreshModels = () => queryClient.invalidateQueries({ queryKey: [MODELS_KEY, userId] })
  const refreshConnectionsAndModels = () => Promise.all([refreshConnections(), refreshModels()])
  const refreshTaskPreferences = () => queryClient.invalidateQueries({ queryKey: ['aiTaskPreferences', userId] })
  const nextProbeGeneration = (modelId: string, probeKind: AIModelProbeKind) => {
    const key = probeFeedbackKey(modelId, probeKind)
    const generation = (probeGenerations.current.get(key) ?? 0) + 1
    probeGenerations.current.set(key, generation)
    return generation
  }
  const invalidateModelProbes = (modelIds: readonly string[]) => {
    const keys = modelIds.flatMap((modelId) => (['text', 'tools'] as const).map((probeKind) => {
      const key = probeFeedbackKey(modelId, probeKind)
      probeGenerations.current.set(key, (probeGenerations.current.get(key) ?? 0) + 1)
      return key
    }))
    setProbeFeedback((current) => {
      const next = { ...current }
      keys.forEach((key) => delete next[key])
      return next
    })
  }
  const beginConfigurationChange = (scope: ConfigChangeScope): ConfigChangeScope => {
    scope.modelIds.forEach((modelId) => {
      pendingModelChangeCounts.current.set(modelId, (pendingModelChangeCounts.current.get(modelId) ?? 0) + 1)
    })
    scope.connectionIds.forEach((connectionId) => {
      pendingConnectionChangeCounts.current.set(connectionId, (pendingConnectionChangeCounts.current.get(connectionId) ?? 0) + 1)
    })
    setPendingModelChanges(Object.fromEntries(pendingModelChangeCounts.current))
    setPendingConnectionChanges(Object.fromEntries(pendingConnectionChangeCounts.current))
    invalidateModelProbes(scope.modelIds)
    return scope
  }
  const beginConnectionConfigurationChange = (connectionId: string) => beginConfigurationChange({
    connectionIds: [connectionId],
    modelIds: probeConfigSnapshot.current.models
      .filter((model) => model.connection_id === connectionId)
      .map((model) => model.id),
  })
  const finishConfigurationChange = (scope: ConfigChangeScope | undefined) => {
    if (!scope) return
    scope.modelIds.forEach((modelId) => {
      const nextCount = (pendingModelChangeCounts.current.get(modelId) ?? 0) - 1
      if (nextCount > 0) pendingModelChangeCounts.current.set(modelId, nextCount)
      else pendingModelChangeCounts.current.delete(modelId)
    })
    scope.connectionIds.forEach((connectionId) => {
      const nextCount = (pendingConnectionChangeCounts.current.get(connectionId) ?? 0) - 1
      if (nextCount > 0) pendingConnectionChangeCounts.current.set(connectionId, nextCount)
      else pendingConnectionChangeCounts.current.delete(connectionId)
    })
    setPendingModelChanges(Object.fromEntries(pendingModelChangeCounts.current))
    setPendingConnectionChanges(Object.fromEntries(pendingConnectionChangeCounts.current))
  }
  const isProbeConfigurationPending = (modelId: string) => {
    if (pendingModelChangeCounts.current.has(modelId)) return true
    const model = probeConfigSnapshot.current.models.find((candidate) => candidate.id === modelId)
    return model ? pendingConnectionChangeCounts.current.has(model.connection_id) : false
  }
  const isCurrentProbeRequest = (request: ModelProbeRequest) => {
    const key = probeFeedbackKey(request.modelId, request.probeKind)
    return probeGenerations.current.get(key) === request.generation &&
      probeConfigIdentity(request.modelId, probeConfigSnapshot.current) === request.configIdentity
  }
  const reportIgnoredStaleProbe = (request: ModelProbeRequest) => {
    const key = probeFeedbackKey(request.modelId, request.probeKind)
    if (probeGenerations.current.get(key) !== request.generation ||
      probeConfigIdentity(request.modelId, probeConfigSnapshot.current) === request.configIdentity) return
    setProbeFeedback((current) => current[key]?.state === 'pending'
      ? {
        ...current,
        [key]: { state: 'unknown', message: '测试期间配置已变化，旧请求结果已忽略；当前能力状态未更新。' },
      }
      : current)
  }
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
    onMutate: ({ connectionId }) => beginConnectionConfigurationChange(connectionId),
    onSuccess: async (_connection, _variables, scope) => {
      if (scope) invalidateModelProbes(scope.modelIds)
      setReplacementKey('')
      setReplaceFor(null)
      setNotice('Key 已替换，旧凭据版本已失效。本站尚未测试新 Key。')
      await refreshConnections()
    },
    onError: () => setNotice('替换失败。请检查填写内容后重试。'),
    onSettled: (_data, _error, _variables, scope) => finishConfigurationChange(scope),
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
    onMutate: ({ connectionId }) => beginConnectionConfigurationChange(connectionId),
    onSuccess: async (_connection, variables, scope) => {
      if (scope) invalidateModelProbes(scope.modelIds)
      setNotice(variables.isEnabled ? '连接已启用。' : '连接已停用，旧凭据版本已失效。')
      await Promise.all([refreshConnections(), refreshTaskPreferences()])
    },
    onError: () => setNotice('状态更新失败，请重试。'),
    onSettled: (_data, _error, _variables, scope) => finishConfigurationChange(scope),
  })
  const deleteMutation = useMutation({
    mutationFn: (connectionId: string) => deleteAIConnection(connectionId),
    onMutate: (connectionId) => beginConnectionConfigurationChange(connectionId),
    onSuccess: async (_deleted, _connectionId, scope) => {
      if (scope) invalidateModelProbes(scope.modelIds)
      setNotice('连接已删除，站点已清除保存的密文。')
      await Promise.all([refreshConnections(), refreshTaskPreferences()])
    },
    onError: () => setNotice('删除失败，请重试。'),
    onSettled: (_data, _error, _connectionId, scope) => finishConfigurationChange(scope),
  })
  const createModelMutation = useMutation({
    mutationFn: (input: CreateAIModelInput) => createAIModel(input),
    onSuccess: async () => {
      setModelFormFor(null)
      setSelectedCatalogModelId('')
      setModelIdDraft('')
      setModelDisplayName('')
      setNotice('模型已保存，当前未测试；保存模型不会调用服务商。')
      await refreshModels()
    },
    onError: () => setNotice('模型保存失败，请检查模型 ID 后重试。'),
  })
  const deleteModelMutation = useMutation({
    mutationFn: (modelId: string) => deleteAIModel(modelId),
    onMutate: (modelId) => beginConfigurationChange({ modelIds: [modelId], connectionIds: [] }),
    onSuccess: async (_deleted, _modelId, scope) => {
      if (scope) invalidateModelProbes(scope.modelIds)
      setNotice('模型配置已删除。')
      await Promise.all([refreshModels(), refreshTaskPreferences()])
    },
    onError: () => setNotice('模型删除失败，请重试。'),
    onSettled: (_data, _error, _modelId, scope) => finishConfigurationChange(scope),
  })
  const updateModelMutation = useMutation({
    mutationFn: ({ modelId, nextModelId, displayName }: { modelId: string; nextModelId: string; displayName: string }) =>
      updateAIModel(modelId, { model_id: nextModelId, display_name: displayName }),
    onMutate: (variables) => beginConfigurationChange({ modelIds: [variables.modelId], connectionIds: [] }),
    onSuccess: async (_model, _variables, scope) => {
      if (scope) invalidateModelProbes(scope.modelIds)
      setEditModelFor(null)
      setEditModelId('')
      setEditModelDisplayName('')
      setNotice('模型配置已更新；此前的测试结果已失效。')
      await refreshModels()
    },
    onError: () => setNotice('模型配置更新失败，请检查模型 ID 后重试。'),
    onSettled: (_data, _error, _variables, scope) => finishConfigurationChange(scope),
  })
  const testModelMutation = useMutation({
    mutationFn: ({ modelId, probeKind }: ModelProbeRequest) => testAIModel(modelId, probeKind),
    retry: false,
    onSuccess: async (result, variables) => {
      if (!isCurrentProbeRequest(variables)) {
        reportIgnoredStaleProbe(variables)
        return
      }
      setProbeFeedback((current) => ({
        ...current,
        [probeFeedbackKey(variables.modelId, variables.probeKind)]: feedbackForProbeResult(result, variables.probeKind),
      }))
      await refreshModels()
    },
    onError: (error, variables) => {
      if (!isCurrentProbeRequest(variables)) {
        reportIgnoredStaleProbe(variables)
        return
      }
      setProbeFeedback((current) => ({
        ...current,
        [probeFeedbackKey(variables.modelId, variables.probeKind)]: feedbackForProbeError(error),
      }))
    },
  })

  const startModelTest = (modelId: string, probeKind: AIModelProbeKind) => {
    if (isProbeConfigurationPending(modelId)) return
    const isText = probeKind === 'text'
    const prompt = isText
      ? '这会向服务商发送一条极短的文本请求，可能产生费用。本站不会自动重试。要继续吗？'
      : '这会向服务商发送一条极短的工具调用请求，可能产生费用。本站不会自动重试。要继续吗？'
    if (!window.confirm(prompt)) return
    if (isProbeConfigurationPending(modelId)) return
    const configIdentity = probeConfigIdentity(modelId, probeConfigSnapshot.current)
    if (!configIdentity) return
    const generation = nextProbeGeneration(modelId, probeKind)
    setNotice('')
    setProbeFeedback((current) => ({
      ...current,
      [probeFeedbackKey(modelId, probeKind)]: {
        state: 'pending',
        message: isText ? '正在测试文本能力…' : '正在测试工具调用能力…',
      },
    }))
    testModelMutation.mutate({ modelId, probeKind, generation, configIdentity })
  }

  return (
    <section className="mx-auto w-full max-w-3xl px-4 pb-12 pt-6 sm:pt-10">
      <Link to="/settings" className="inline-flex min-h-11 items-center gap-2 rounded-md text-sm text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
        <ArrowLeft aria-hidden="true" className="size-4" />返回设置
      </Link>
      <header className="mb-7 mt-4">
        <p className="text-sm font-medium text-orange-600">个人 API Key</p>
        <h1 className="mt-1 text-3xl font-semibold tracking-tight">AI 模型与密钥</h1>
        <p className="mt-2 text-sm leading-6 text-muted-foreground">Key 由本站后端加密保存。保存连接和模型配置都不会调用服务商；模型需要经过明确测试后才会显示已验证能力。</p>
      </header>

      {notice && <p className="mb-5 rounded-lg border border-border bg-muted/40 p-3 text-sm" role="status">{notice}</p>}

      <AITaskPreferencesSection
        userId={userId}
        models={models}
        connections={connections}
        dataLoading={connectionsQuery.isPending || modelsQuery.isPending}
        dataError={connectionsQuery.isError || modelsQuery.isError}
      />

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
          <Button type="button" variant="outline" className="min-h-11" onClick={() => void refreshConnectionsAndModels()} disabled={connectionsQuery.isFetching || modelsQuery.isFetching}>
            <RotateCcw aria-hidden="true" />刷新连接和模型
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

                <section aria-labelledby={`models-for-${connection.id}`} className="mt-5 border-t border-border pt-4">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <h3 id={`models-for-${connection.id}`} className="font-medium">模型配置</h3>
                      <p className="mt-1 text-xs text-muted-foreground">可选官方目录模型或手动输入 ID；保存不会发送请求。</p>
                    </div>
                    <Button type="button" variant="outline" className="min-h-11" onClick={() => {
                      setModelFormFor(connection.id)
                      setSelectedCatalogModelId('')
                      setModelIdDraft('')
                      setModelDisplayName('')
                      setNotice('')
                    }}>
                      添加模型
                    </Button>
                  </div>

                  {modelsQuery.isError && <p className="mt-3 text-sm text-destructive" role="alert">模型列表暂不可用。可以重试读取，目录问题不会阻止手动输入模型 ID。</p>}
                  {modelsQuery.isPending ? <p className="mt-3 text-sm text-muted-foreground" role="status">正在读取模型配置…</p> : (
                    <ul className="mt-3 space-y-2">
                      {models.filter((model) => model.connection_id === connection.id).map((model) => (
                        <li key={model.id} className="rounded-lg bg-muted/40 p-3">
                          <div className="flex flex-wrap items-start justify-between gap-3">
                            <div className="min-w-0">
                              <p className="font-medium">{model.display_name}</p>
                              <p className="mt-1 break-all text-xs text-muted-foreground">模型 ID：{model.model_id}</p>
                              <p className="mt-1 text-xs text-muted-foreground">{model.source === 'catalog' ? `官方目录 ${model.catalog_version} · 声明能力未实测` : '手动录入 · 未经目录核验'}</p>
                              <p className="mt-1 text-xs text-muted-foreground">文本：{model.capabilities.text} · 工具：{model.capabilities.tools} · {verificationLabel(model.verification_status)}</p>
                              {model.has_trusted_context_limit ? (
                                <p className="mt-1 text-xs text-muted-foreground">官方上下文上限 {model.context_window_tokens?.toLocaleString()} tokens；最大输出 {model.max_output_tokens?.toLocaleString() ?? '未知'} tokens</p>
                              ) : (
                                <p className="mt-1 text-xs text-amber-700">上下文上限未核实；不会据此自动发送整篇文章。</p>
                              )}
                            </div>
                            <div className="flex flex-wrap gap-2">
                              {model.catalog_model_id ? (
                                <>
                                  <ProbeTestButton
                                    label="测试文本能力"
                                    pendingLabel="文本测试中…"
                                    feedback={probeFeedback[probeFeedbackKey(model.id, 'text')]}
                                    disabled={testModelMutation.isPending || Boolean(pendingModelChanges[model.id] || pendingConnectionChanges[connection.id])}
                                    onClick={() => startModelTest(model.id, 'text')}
                                  />
                                  <ProbeTestButton
                                    label="测试工具能力"
                                    pendingLabel="工具测试中…"
                                    feedback={probeFeedback[probeFeedbackKey(model.id, 'tools')]}
                                    disabled={testModelMutation.isPending || Boolean(pendingModelChanges[model.id] || pendingConnectionChanges[connection.id])}
                                    onClick={() => startModelTest(model.id, 'tools')}
                                  />
                                </>
                              ) : (
                                <p className="self-center text-xs text-muted-foreground">该手动模型尚无预批准网关路由，暂不可测试。</p>
                              )}
                              <Button type="button" variant="outline" className="min-h-11" onClick={() => {
                                setEditModelFor(model.id)
                                setEditModelId(model.model_id)
                                setEditModelDisplayName(model.display_name)
                                setNotice('')
                              }}>编辑模型</Button>
                              <Button type="button" variant="destructive" className="min-h-11" disabled={deleteModelMutation.isPending} onClick={() => {
                                if (window.confirm('删除这个模型配置？')) deleteModelMutation.mutate(model.id)
                              }}>删除模型</Button>
                            </div>
                          </div>
                          {editModelFor === model.id && <form className="mt-4 space-y-3 border-t border-border pt-4" onSubmit={(event) => {
                            event.preventDefault()
                            if (!editModelId.trim() || !editModelDisplayName.trim() || updateModelMutation.isPending) return
                            updateModelMutation.mutate({
                              modelId: model.id,
                              nextModelId: editModelId.trim(),
                              displayName: editModelDisplayName.trim(),
                            })
                          }}>
                            <label className="block space-y-2 text-sm font-medium">
                              <span>模型 ID</span>
                              <Input value={editModelId} onChange={(event) => setEditModelId(event.target.value)} maxLength={160} autoComplete="off" spellCheck={false} required />
                            </label>
                            <label className="block space-y-2 text-sm font-medium">
                              <span>显示名称</span>
                              <Input value={editModelDisplayName} onChange={(event) => setEditModelDisplayName(event.target.value)} maxLength={64} autoComplete="off" required />
                            </label>
                            <div className="flex flex-wrap gap-2">
                              <Button type="submit" className="min-h-11" disabled={!editModelId.trim() || !editModelDisplayName.trim() || updateModelMutation.isPending}>
                                {updateModelMutation.isPending ? '正在保存…' : '保存模型修改'}
                              </Button>
                              <Button type="button" variant="outline" className="min-h-11" onClick={() => setEditModelFor(null)}>取消</Button>
                            </div>
                          </form>}
                        </li>
                      ))}
                    </ul>
                  )}

                  {modelFormFor === connection.id && <form className="mt-4 space-y-3 rounded-lg border border-border p-3" onSubmit={(event) => {
                    event.preventDefault()
                    if (createModelMutation.isPending) return
                    const input: CreateAIModelInput = selectedCatalogModelId
                      ? { connection_id: connection.id, catalog_model_id: selectedCatalogModelId, display_name: modelDisplayName }
                      : { connection_id: connection.id, model_id: modelIdDraft.trim(), display_name: modelDisplayName }
                    if (!selectedCatalogModelId && !modelIdDraft.trim()) return
                    setNotice('')
                    createModelMutation.mutate(input)
                  }}>
                    <label className="block space-y-2 text-sm font-medium">
                      <span>官方模型预设</span>
                      <select
                        value={selectedCatalogModelId}
                        onChange={(event) => setSelectedCatalogModelId(event.target.value)}
                        className="h-11 w-full rounded-md border border-input bg-background px-3 text-sm"
                      >
                        <option value="">手动输入模型 ID</option>
                        {modelPresets.filter((preset) => preset.provider_id === connection.provider_id).map((preset) => (
                          <option key={preset.catalog_model_id} value={preset.catalog_model_id}>{preset.display_name} · {preset.model_id}</option>
                        ))}
                      </select>
                    </label>
                    {modelCatalogQuery.isError && <p className="text-xs text-amber-700" role="status">官方目录暂不可用。你仍可手动输入模型 ID。</p>}
                    {selectedCatalogModelId ? (
                      <p className="text-xs text-muted-foreground">已选：{modelPresets.find((preset) => preset.catalog_model_id === selectedCatalogModelId)?.model_id}</p>
                    ) : (
                      <label className="block space-y-2 text-sm font-medium">
                        <span>模型 ID</span>
                        <Input value={modelIdDraft} onChange={(event) => setModelIdDraft(event.target.value)} maxLength={160} autoComplete="off" spellCheck={false} required />
                      </label>
                    )}
                    <label className="block space-y-2 text-sm font-medium">
                      <span>显示名称（可选）</span>
                      <Input value={modelDisplayName} onChange={(event) => setModelDisplayName(event.target.value)} maxLength={64} autoComplete="off" />
                    </label>
                    <div className="flex flex-wrap gap-2">
                      <Button type="submit" className="min-h-11" disabled={createModelMutation.isPending || (!selectedCatalogModelId && !modelIdDraft.trim())}>
                        {createModelMutation.isPending ? '正在保存…' : '保存模型'}
                      </Button>
                      <Button type="button" variant="outline" className="min-h-11" onClick={() => setModelFormFor(null)}>取消</Button>
                    </div>
                  </form>}
                </section>
              </li>
            ))}
          </ul>
        )}
      </section>
    </section>
  )
}
