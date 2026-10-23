import { useEffect, useId, useRef, useState } from 'react'
import './smart-grouping.css'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, FolderOpen, Sparkles } from 'lucide-react'
import { useAuth } from '@/context/AuthContext'
import AuthModal from '@/components/AuthModal'
import WorkspaceModal from '@/components/workspace/WorkspaceModal'
import { useChannelConfig } from '@/services/channelQueries'
import { newsKeys } from '@/services/newsQueries'
import { workspaceCatalogOptions, workspaceConfigOptions, workspaceKeys, workspaceRequest, workspaceError,
  originLabel, proposalStatus, type GroupingMode, type GroupingConfig, type Proposal, type ProposalPage, type Topic, type SiteClassifier } from '@/services/workspaceApi'
import type { ChannelGroup } from '@/types/channels'
import ExistingGroupOrganizer from '@/components/workspace/ExistingGroupOrganizer'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { ModelCombobox } from '@/components/ui/model-combobox'
import { NativeSelect } from '@/components/ui/native-select'
import { listAITaskPreferences } from '@/services/aiConnectionsApi'

const modeOptions: Array<{ value: GroupingMode; title: string; description: string }> = [
  { value: 'suggest', title: '推荐并确认', description: '新增订阅先生成建议，由你确认。' },
  { value: 'auto', title: '自动加入已有分组', description: '仅使用可信主题与已绑定分组；AI 结果仍需确认。' },
  { value: 'off', title: '关闭后续自动整理', description: '保留现有分组，仍可主动生成一次性预览。' },
]
const errorMessages: Record<string, string> = {
  classifier_stopped: '后台分类授权或预算已变更，任务已中止；已派发调用不会自动重发。',
  authorization_changed: '模型凭据或授权已变化，请检查设置后重新生成。',
  configuration_changed: '订阅或分组已变化，请重新生成预览。', metadata_changed: '频道资料已更新，请重新生成。',
  model_unavailable: '没有可用的模型连接。', rate_limited: '模型限流，后台将遵守等待时间进行有限重试。',
  model_request_failed: '模型请求失败，请检查模型连接；可使用规则推荐继续整理。',
  incomplete_output: '模型返回不完整，未应用任何分组。', worker_interrupted: '任务已中断或结果未知，不会自动重发；确认后可显式重新预览。',
  invalid_output: '模型输出格式无效，未修改你的分组。', invalid_topic: '模型返回了未允许的主题。',
  invalid_source: '模型返回了未知频道。', expired: '任务已过期，请重新生成。',
}

function useClassificationModel(viewer: number, enabled: boolean) {
  const preferences = useQuery({
    queryKey: ['ai-task-preferences', viewer], queryFn: ({ signal }) => listAITaskPreferences(signal),
    enabled, retry: false,
  })
  const selected = preferences.data?.preferences.find(item => item.task_kind === 'default' && item.selection_state === 'available')
  return { model: selected?.model ?? null, id: selected?.model_config_id ?? null,
    consentKey: JSON.stringify([selected?.model_config_id, preferences.data?.revision]),
    loading: enabled && preferences.isPending, error: preferences.isError }
}

export default function SmartGroupingWorkspace() {
  const { user, loading } = useAuth()
  const [login, setLogin] = useState(false)
  if (loading) return <p role="status" className="workspace-empty">正在加载账号…</p>
  if (!user) return <div className="workspace-empty"><h1>AI 智能整理</h1><p>登录后选择主题预设，整理自己的已订阅频道。</p><button type="button" className="workspace-button" onClick={() => setLogin(true)}>登录</button>{login && <AuthModal onClose={() => setLogin(false)} />}</div>
  return <SmartPage key={user.id} viewer={user.id} admin={user.isSuperuser} />
}

function SmartPage({ viewer, admin }: { viewer: number; admin: boolean }) {
  const channels = useChannelConfig()
  const [advanced, setAdvanced] = useState(false)
  const catalog = useQuery(workspaceCatalogOptions(viewer, 'history'))
  const config = useQuery(workspaceConfigOptions(viewer))
  if (config.isError || catalog.isError || channels.error) return <div role="alert" className="workspace-empty"><h1>整理配置未能加载</h1><p>不会使用不完整的订阅数据生成建议。</p><button type="button" className="workspace-button secondary" onClick={() => { void config.refetch(); void catalog.refetch(); void channels.retry() }}>重试</button></div>
  if (!config.data || !catalog.data || !channels.ready) return <p role="status" className="workspace-empty">正在加载订阅与主题资料…</p>
  return <><ExistingGroupOrganizer viewer={viewer} initialConfig={config.data} groups={channels.groups.data ?? []}
    subscriptions={(channels.subscriptions.data ?? []).map(subscription => ({ id: subscription.source_id, groupIds: subscription.group_ids }))} />
    <section className="workspace-panel" aria-label="旧版主题预设入口"><header className="workspace-panel-heading"><div className="space-y-2"><Badge variant="outline">次要入口 · 旧版 · 可创建分组</Badge><h2>按主题预设整理</h2></div>
      <Button type="button" variant="ghost" aria-expanded={advanced} onClick={() => setAdvanced(value => !value)}>高级：按主题预设整理</Button></header>
      <p className="workspace-caption">兼容旧流程：按预置主题创建或合并分组。默认请先使用上方“按已有分组整理”主流程。</p>
      {advanced && <Organizer embedded viewer={viewer} admin={admin} initialConfig={config.data} catalog={catalog.data} groups={channels.groups.data ?? []}
    subscriptions={(channels.subscriptions.data ?? []).map(subscription => ({ id: subscription.source_id, groupIds: subscription.group_ids }))} />}
    </section>{admin && !advanced && <SiteClassifierPanel viewer={viewer} />}</>
}

export function Organizer({ viewer, admin, initialConfig, catalog, groups, subscriptions, embedded = false }: {
  viewer: number; admin: boolean; initialConfig: GroupingConfig
  catalog: NonNullable<ReturnType<typeof useQuery<import('@/services/workspaceApi').Catalog>>['data']>
  groups: ChannelGroup[]; subscriptions: Array<{ id: number; groupIds: number[] }>; embedded?: boolean
}) {
  const client = useQueryClient()
  const [selectedTopics, setSelectedTopics] = useState<string[]>(catalog.presets[0]?.topics ?? [])
  const [scope, setScope] = useState<'all' | 'ungrouped'>('all')
  const [engine, setEngine] = useState<'rules' | 'ai'>('rules')
  const classification = useClassificationModel(viewer, engine === 'ai')
  const [confirmedModel, setConfirmedModel] = useState<string | null>(null)
  const consent = Boolean(classification.id && confirmedModel === classification.consentKey)
  const [modeDraft, setMode] = useState<GroupingMode | null>(null)
  const mode = modeDraft ?? initialConfig.mode
  const [historyPage, setHistoryPage] = useState(1)
  const [activeId, setActiveId] = useState<string | null>(null)
  const [notice, setNotice] = useState('')
  const [clearHistory, setClearHistory] = useState(false)
  const [pendingCreate, setPendingCreate] = useState<CreateRequest | null>(null)
  const lifetime = useRef<AbortController | null>(null)
  const writePending = useRef(false)
  const focusRequested = useRef(false)
  const previewHeading = useRef<HTMLHeadingElement>(null)
  const startButton = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    const controller = new AbortController()
    lifetime.current = controller
    return () => { controller.abort(); lifetime.current = null }
  }, [])
  const isCurrent = () => lifetime.current !== null && !lifetime.current.signal.aborted
  const sourceIds = subscriptions.filter(subscription => scope === 'all' || subscription.groupIds.length === 0).map(subscription => subscription.id)
  const knownIds = new Set(catalog.sources.filter(source => source.topics.length > 0).map(source => source.id))
  const supportedCount = sourceIds.filter(id => knownIds.has(id)).length
  const history = useQuery({ queryKey: workspaceKeys.proposalHistory(viewer, 'topics', historyPage), queryFn: ({ signal }) => workspaceRequest<ProposalPage>('/me/smart-channels/proposals/?target=topics&page=' + historyPage, { signal, viewer }),
    retry: false, refetchOnWindowFocus: false,
    refetchInterval: query => query.state.status !== 'error' && query.state.data?.results.some(item => item.status === 'queued' || item.status === 'running') ? 3000 : false })
  const active = useQuery({ queryKey: workspaceKeys.proposal(viewer, activeId), enabled: !!activeId,
    queryFn: ({ signal }) => workspaceRequest<Proposal>('/me/smart-channels/proposals/' + activeId + '/', { signal }),
    retry: false, refetchOnWindowFocus: false,
    refetchInterval: query => query.state.status !== 'error' && ['queued', 'running'].includes(query.state.data?.status ?? '') ? 2000 : false })
  const refresh = async () => {
    if (!isCurrent()) return
    await Promise.all([client.invalidateQueries({ queryKey: workspaceKeys.all }), client.invalidateQueries({ queryKey: ['channels'] }), client.invalidateQueries({ queryKey: newsKeys.lists() })])
  }
  const create = useMutation({
    mutationFn: (body: CreateRequest) => workspaceRequest<Proposal>('/me/smart-channels/proposals/', {
      method: 'POST', body, viewer, signal: lifetime.current?.signal,
    }),
    onSuccess: value => {
      if (!isCurrent()) return
      setPendingCreate(null)
      setConfirmedModel(null)
      client.setQueryData(workspaceKeys.proposal(viewer, value.id), value)
      setActiveId(value.id)
      void refresh()
    },
    onSettled: () => { writePending.current = false },
  })
  const startPreview = () => {
    if (!isCurrent() || writePending.current) return
    const body = pendingCreate ?? { source_ids: [...sourceIds], topic_keys: [...selectedTopics], engine,
      consent: engine === 'ai' && consent, request_id: crypto.randomUUID(),
      ...(engine === 'ai' && classification.id ? { model_config_id: classification.id } : {}) }
    setPendingCreate(body)
    writePending.current = true
    focusRequested.current = true
    create.mutate(body)
  }
  const change = useMutation({ mutationFn: ({ id, action, body }: { id: string; action: 'apply' | 'cancel' | 'undo'; body?: unknown }) =>
    workspaceRequest<Proposal>('/me/smart-channels/proposals/' + id + '/' + action + '/', {
      method: 'POST', body: body ?? {}, viewer, signal: lifetime.current?.signal,
    }),
    onSuccess: async value => {
      if (!isCurrent()) return
      client.setQueryData(workspaceKeys.proposal(viewer, value.id), value)
      setNotice(value.status === 'applied' ? '整理已应用。只添加本次选择的归属，不会删除原有分组。' : value.status === 'undone' ? '已撤销本次新增归属，后续人工修改、分组名称和订阅均保留。' : '已取消，未应用分组变更。')
      await refresh()
    },
  })
  const reconcile = async () => {
    const result = await active.refetch()
    if (isCurrent() && result.isSuccess) change.reset()
  }
  const saveMode = useMutation({ mutationFn: (value: GroupingMode) => workspaceRequest<GroupingConfig>('/me/smart-channels/settings/', {
    method: 'PATCH', body: { mode: value }, viewer, signal: lifetime.current?.signal,
  }),
    onSuccess: value => {
      if (!isCurrent()) return
      setMode(null)
      client.setQueryData(workspaceKeys.config(viewer), value)
      setNotice('后续整理模式已保存，现有频道归属保持不变。')
      void refresh()
    },
  })
  const clear = useMutation({ mutationFn: () => workspaceRequest('/me/reading-stats/', { method: 'DELETE', viewer, signal: lifetime.current?.signal }),
    onSuccess: () => { if (!isCurrent()) return; setClearHistory(false); setNotice('个人阅读记录已清除。'); void refresh() } })
  const processing = active.data && ['queued', 'running'].includes(active.data.status)
  const busy = create.isPending || change.isPending || saveMode.isPending
  const setupLocked = busy || !!pendingCreate || !!processing
  const step = pendingCreate || processing ? 2 : active.data?.status === 'applied' || active.data?.status === 'undone' ? 4
    : active.data?.status === 'ready' ? 3 : 1
  useEffect(() => {
    if (focusRequested.current && active.data && previewHeading.current) {
      previewHeading.current.focus()
      focusRequested.current = false
    }
  }, [activeId, active.data?.status, active.data])
  return <div className={embedded ? 'space-y-4' : 'workspace-page workspace-smart'}>
    <nav aria-label="整理步骤"><ol className="smart-steps">
      {['选择范围与主题', '生成预览', '调整并确认', '查看结果'].map((label, index) =>
        <li key={label} aria-current={step === index + 1 ? 'step' : undefined}><span>{index + 1}</span>{label}</li>)}
    </ol></nav>
    {!embedded && <header className="workspace-page-heading"><div><p className="workspace-eyebrow">少一点整理，多一点阅读</p><h1>AI 智能整理 <span className="workspace-beta">Beta</span></h1><p>利用频道资料生成建议，预览、调整后再应用。人工选择始终优先。</p></div></header>}
    <div className="workspace-organizer-hero"><section className="workspace-organizer-intro"><div className="workspace-folder-illustration" aria-hidden="true"><FolderOpen /><Sparkles /></div>
      <div><h2>选择范围与主题</h2><p>选择一个阅读主题包，整理已订阅来源。规则推荐无需模型调用，AI 精分仅在你明确授权后启动。</p>
        <div className="workspace-engine-options" role="group" aria-label="整理引擎"><button type="button" aria-pressed={engine === 'rules'} disabled={setupLocked} onClick={() => setEngine('rules')}>来源资料推荐</button><button type="button" aria-pressed={engine === 'ai'} disabled={!initialConfig.ai_available || setupLocked} onClick={() => setEngine('ai')}><Sparkles size={14} aria-hidden="true" />AI 精细分类</button></div>
        {!initialConfig.ai_available && <p className="workspace-caption">AI 尚不可用。<Link to="/settings">配置个人模型连接</Link>；资料推荐仍可使用。</p>}
        {engine === 'ai' && <div className="workspace-soft-panel">
          <p>{classification.loading ? '正在读取个人默认模型…' : classification.model
            ? `${pendingCreate ? '当前默认模型' : '本次分类模型'}：${classification.model.display_name} (${classification.model.model_id})`
            : '请先在模型设置中配置并验证个人默认模型。'} <Link to="/settings/ai" className="workspace-link">模型设置</Link></p>
          {pendingCreate && <p>正在恢复首次请求，保留原模型与原授权；默认模型的更改不会应用到该请求。</p>}
          {classification.error && <p role="alert">暂时无法读取模型，不会派发分类请求。</p>}
          <label className="workspace-check"><input type="checkbox" disabled={setupLocked || !classification.id} checked={consent}
            onChange={event => setConfirmedModel(event.target.checked ? classification.consentKey : null)} />同意本次使用上述个人模型额度；仅发送公开频道资料和已收录标题。仅明确限流拒绝时最多重试一次，结果未知不会自动重发。</label>
        </div>}
        <div className="workspace-actions"><label>整理范围<NativeSelect aria-label="整理范围" disabled={setupLocked} value={scope} onChange={event => setScope(event.target.value === 'ungrouped' ? 'ungrouped' : 'all')}><option value="all">全部已订阅</option><option value="ungrouped">仅未分组频道</option></NativeSelect></label>
</div>
    <section className="workspace-preset-section"><header className="workspace-panel-heading"><div><h2>主题预设</h2><p className="workspace-caption">选择你关心的主题。生成的是可编辑建议，不会立即修改订阅。</p></div><div className="workspace-tabs" role="group" aria-label="主题包">{catalog.presets.map(preset => <button type="button" key={preset.key} aria-pressed={preset.topics.length === selectedTopics.length && preset.topics.every(topic => selectedTopics.includes(topic))} disabled={setupLocked} onClick={() => setSelectedTopics([...preset.topics])}>{preset.name}</button>)}</div></header>
      <div className="workspace-preset-cards">{catalog.topics.map(topic => <label key={topic.key} className="workspace-preset-card" data-selected={selectedTopics.includes(topic.key)}><input type="checkbox" disabled={setupLocked} checked={selectedTopics.includes(topic.key)} onChange={event => setSelectedTopics(current => event.target.checked ? [...current, topic.key] : current.filter(key => key !== topic.key))} /><span className="workspace-topic-symbol" data-topic={topic.key}><FolderOpen size={20} aria-hidden="true" /></span><span><strong>{topic.name}</strong><small>{topic.description}</small></span></label>)}</div>
    </section>
          <button ref={startButton} type="button" className="workspace-button" disabled={busy || change.isError || !!processing || !sourceIds.length || !selectedTopics.length || (engine === 'ai' && ((!consent && !pendingCreate) || sourceIds.length > 40)) || (engine === 'rules' && sourceIds.length > 200)} onClick={startPreview}><Sparkles size={16} aria-hidden="true" />{create.isPending ? '正在准备预览…' : pendingCreate ? '重试同一次预览' : '生成分组预览'}</button>
        {sourceIds.length > (engine === 'ai' ? 40 : 200) && <p role="status" className="workspace-caption">本次上限为 {engine === 'ai' ? 40 : 200} 个频道，请使用“仅未分组频道”缩小范围。</p>}
        {subscriptions.length === 0 && <div role="status"><p>还没有订阅频道，先添加来源再整理。</p><Link className="workspace-button secondary" to="/channels">去添加频道</Link></div>}
        {subscriptions.length > 0 && sourceIds.length === 0 && <p role="status">所有已订阅频道都已分组，可切换为“全部已订阅”。</p>}
        {selectedTopics.length === 0 && <p role="status">请至少选择一个主题。</p>}
      </div></section>
      <aside className="workspace-panel"><h2>当前频道状态</h2><dl className="workspace-reading-numbers"><div><dt>已订阅</dt><dd>{subscriptions.length}</dd></div><div><dt>本次整理</dt><dd>{sourceIds.length}</dd></div><div><dt>已有主题</dt><dd>{supportedCount}</dd></div></dl>
        <p className="workspace-caption">主题不足的频道保留待确认，不会强行归类。</p>

      </aside></div>
    {(create.isError || change.isError || saveMode.isError) && <p role="alert" className="workspace-error">{workspaceError(create.error ?? change.error ?? saveMode.error)}</p>}
    {pendingCreate && create.isError && <div role="alert" className="workspace-soft-panel">
      <p>创建结果尚未确认。重试会复用原频道、主题及请求编号，不会创建另一份任务。</p>
      <button type="button" className="workspace-button secondary" onClick={() => {
        setPendingCreate(null); create.reset(); setNotice('已放弃本地请求。服务端可能已创建任务，请先查看整理记录。')
        void history.refetch(); startButton.current?.focus()
      }}>返回修改选择</button>
    </div>}
    {change.isError && <div role="alert" className="workspace-soft-panel"><p>操作结果尚未确认，请先读取当前任务状态。不会自动重复应用或撤销。</p>
      <button type="button" disabled={active.isFetching} onClick={() => void reconcile()}>读取操作结果</button></div>}
    {notice && <p role="status" className="workspace-notice">{notice}</p>}

    {activeId && <section className="workspace-panel" aria-label="整理预览">
      <header className="workspace-panel-heading"><h2 ref={previewHeading} tabIndex={-1}>分组建议预览</h2><span className="workspace-caption">{active.data ? proposalStatus[active.data.status] ?? active.data.status : '正在读取'}</span></header>
      {active.isError && <p role="alert" className="workspace-error">{workspaceError(active.error)}<button type="button" onClick={() => void active.refetch()}>重试</button></p>}
      {processing && <div className="workspace-processing" role="status"><Sparkles size={24} aria-hidden="true" /><strong>{proposalStatus[active.data!.status]}</strong><p>任务已持久化，关闭页面后可从记录恢复。若长时间排队，请确认 channel_worker 已启动。</p><button type="button" className="workspace-button secondary" disabled={busy || change.isError || active.isError} onClick={() => change.mutate({ id: activeId, action: 'cancel' })}>取消任务</button></div>}
      {active.data?.status === 'ready' && <ProposalEditor key={active.data.id} proposal={active.data} topics={catalog.topics} groups={groups} mode={initialConfig.mode} busy={busy || change.isError || active.isError || active.isFetching}
        onApply={body => change.mutate({ id: activeId, action: 'apply', body })} onCancel={() => change.mutate({ id: activeId, action: 'cancel' })} />}
      {active.data?.status === 'failed' && <p role="alert" className="workspace-error">{errorMessages[active.data.error_code] ?? '任务失败，未应用变更。请重新生成或改用资料推荐。'}</p>}
      {active.data?.status === 'applied' && <div className="workspace-applied"><Check size={22} aria-hidden="true" /><p>已新增 {active.data.applied_count} 条分组归属。</p><Link className="workspace-button" to="/channels/groups">查看分组</Link><button type="button" className="workspace-button secondary" disabled={busy || change.isError || active.isError} onClick={() => change.mutate({ id: activeId, action: 'undo' })}>撤销本次新增归属</button></div>}
      {active.data && ['cancelled', 'undone'].includes(active.data.status) && <p role="status" className="workspace-muted">{proposalStatus[active.data.status]}，可以重新选择预设进行整理。</p>}
    </section>}
    <section className="workspace-panel"><header className="workspace-panel-heading"><h2>整理记录与待确认建议</h2><button type="button" className="workspace-link" onClick={() => void history.refetch()}>刷新记录</button></header>
      {history.isError && <p role="alert" className="workspace-error">记录加载失败。</p>}
      <ul className="workspace-job-list">{(history.data?.results ?? []).filter(item => item.target !== 'groups').map(item => <li key={item.id}><span><strong>{item.engine === 'ai' ? 'AI 精细分类' : '来源资料推荐'}</strong><small>{new Date(item.created_at).toLocaleString()} · {item.source_ids.length} 个频道</small></span><span>{proposalStatus[item.status] ?? item.status}</span><button type="button" className="workspace-button secondary" disabled={busy || change.isError} onClick={() => { focusRequested.current = true; setActiveId(item.id); client.setQueryData(workspaceKeys.proposal(viewer, item.id), item) }}>查看</button></li>)}</ul>
      <nav aria-label="主题整理记录翻页" className="mt-3 flex flex-wrap items-center gap-3">
        <Button type="button" variant="outline" disabled={busy || history.isFetching || historyPage === 1} onClick={() => setHistoryPage(page => page - 1)}>较新记录</Button>
        <span className="text-sm text-muted-foreground">第 {historyPage} 页</span>
        <Button type="button" variant="outline" disabled={busy || history.isFetching || history.isError || !history.data?.has_more} onClick={() => setHistoryPage(page => page + 1)}>较早记录</Button>
      </nav>
      {history.data && !history.data.results.some(item => item.target !== 'groups') && <p className="workspace-muted">还没有整理记录。新增订阅的建议也会出现在这里。</p>}
    </section>
    <section className="workspace-panel" aria-label="后续整理设置"><h2>以后新增订阅时</h2>
      <p className="workspace-caption">独立保存此设置；本次预览和确认不会提交这里尚未保存的修改。</p>
        <fieldset className="workspace-mode-options"><legend>以后新增订阅时</legend>{modeOptions.map(option => <label key={option.value}><input type="radio" disabled={busy} name="grouping-mode" value={option.value} checked={mode === option.value} onChange={() => setMode(option.value)} /><span><strong>{option.title}</strong><small>{option.description}</small></span></label>)}</fieldset>
        <button type="button" className="workspace-button secondary" disabled={busy || mode === initialConfig.mode} onClick={() => saveMode.mutate(mode)}>保存后续整理模式</button>
      {mode !== initialConfig.mode && <p role="status">后续整理模式尚未保存。</p>}
    </section>
    {admin && <SiteClassifierPanel viewer={viewer} />}
    <details className="workspace-panel"><summary>阅读记录与隐私</summary><p className="workspace-muted">文章详情可见并停留三秒后按日去重累计。AI 分类不使用个人阅读记录、收藏、对话或私人分组名称。</p><button type="button" className="workspace-button secondary" onClick={() => setClearHistory(true)}>清除我的阅读统计</button></details>
    {clearHistory && <WorkspaceModal title="清除阅读记录" busy={clear.isPending} onClose={() => setClearHistory(false)}><p>这会删除你的阅读计数，不影响收藏、订阅、频道分组或文章。</p>{clear.isError && <p role="alert" className="workspace-error">{workspaceError(clear.error)}</p>}
      <footer className="workspace-modal-actions"><button type="button" className="workspace-button secondary" disabled={clear.isPending} onClick={() => setClearHistory(false)}>取消</button><button type="button" className="workspace-button danger" disabled={clear.isPending} onClick={() => clear.mutate()}>确认清除</button></footer></WorkspaceModal>}
  </div>
}

interface CreateRequest { model_config_id?: string; source_ids: number[]; topic_keys: string[]; engine: 'rules' | 'ai'; consent: boolean; request_id: string }

interface DraftGroup { topic_key: string; group_id: string; name: string; source_ids: number[] }
export function ProposalEditor({ proposal, topics, groups, mode, busy, onApply, onCancel }: {
  proposal: Proposal; topics: Topic[]; groups: ChannelGroup[]; mode: GroupingMode; busy: boolean
  onApply: (body: unknown) => void; onCancel: () => void
}) {
  const [drafts, setDrafts] = useState<DraftGroup[]>(() => proposal.topic_keys.map(key => ({ topic_key: key, group_id: '', name: topics.find(topic => topic.key === key)?.name ?? key,
    source_ids: proposal.result.filter(item => item.topic_keys.includes(key)).map(item => item.source_id) })))
  const editorId = useId()
  const [expanded, setExpanded] = useState<string | null>(null)
  const update = (key: string, values: Partial<DraftGroup>) => setDrafts(current => current.map(draft => draft.topic_key === key ? { ...draft, ...values } : draft))
  const selected = drafts.filter(draft => draft.source_ids.length > 0)
  const unknown = proposal.result.filter(item => !item.topic_keys.length)
  const invalidNames = selected.some(draft => !draft.group_id && (!draft.name.trim() || groups.some(group => group.name === draft.name.trim())))
  const groupOptions = [{ value: '', label: '创建新分组', description: '仅旧版主题预设可创建新分组' },
    ...groups.map(group => ({ value: String(group.id), label: group.name, description: `已有分组 · ID ${group.id}` }))]
  return <>
    <p className="workspace-caption">{proposal.engine === 'ai' ? '以下为 AI 建议，尚未写入个人分组。' : '以下基于已登记频道资料，不消耗模型额度。'} 选择已有组可合并；空组不会创建。</p>
    {unknown.length > 0 && <p className="workspace-soft-panel">待确认：{unknown.map(item => item.name).join('、')}。可展开任意分组手动勾选，或暂时保持未分组。</p>}
    {proposal.result.some(item => item.needs_review) && <p className="workspace-caption">其中 {proposal.result.filter(item => item.needs_review).length} 个频道需要人工确认；推荐依据可在“调整频道归属”中查看。</p>}
    <div className="workspace-preview-groups">{drafts.map(draft => <section className="workspace-preview-group" key={draft.topic_key}>
      <header><strong>{topics.find(topic => topic.key === draft.topic_key)?.name ?? draft.topic_key}</strong><span>{draft.source_ids.length} 个频道</span></header>
      <div className="mb-3 min-w-0"><span className="text-sm">放入分组</span><div className="mt-1"><ModelCombobox label={'目标分组 ' + draft.topic_key} value={draft.group_id} disabled={busy} options={groupOptions}
        onChange={value => update(draft.topic_key, { group_id: value })} searchLabel={'搜索目标分组 ' + draft.topic_key} searchPlaceholder="搜索分组名称或 ID…"
        emptyText="没有匹配的已有分组。" placeholder="搜索并选择分组" wrapLabels /></div></div>
      {!draft.group_id && <label>新分组名称<Input className="mt-1" aria-label={'新分组名称 ' + draft.topic_key} value={draft.name} maxLength={40} disabled={busy} onChange={event => update(draft.topic_key, { name: event.target.value })} /></label>}
      <Button type="button" variant="link" size="sm" className="h-auto px-0" id={editorId + draft.topic_key + "-toggle"} aria-controls={editorId + draft.topic_key} aria-expanded={expanded === draft.topic_key} onClick={() => setExpanded(current => current === draft.topic_key ? null : draft.topic_key)}>调整频道归属</Button>
      {expanded === draft.topic_key ? <div id={editorId + draft.topic_key} className="workspace-preview-members" onKeyDown={event => {
        if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); setExpanded(null)
          document.getElementById(editorId + draft.topic_key + '-toggle')?.focus() }
      }}>{proposal.result.map(item => <label key={item.source_id}><Input className="size-4 shrink-0" type="checkbox" disabled={busy} checked={draft.source_ids.includes(item.source_id)} onChange={event => update(draft.topic_key, { source_ids: event.target.checked ? [...draft.source_ids, item.source_id] : draft.source_ids.filter(id => id !== item.source_id) })} /><span><strong>{item.name}</strong><small>{originLabel[item.origin] ?? item.origin} · {item.reason}</small></span></label>)}</div>
        : <p className="workspace-caption">{proposal.result.filter(item => draft.source_ids.includes(item.source_id)).map(item => item.name).join('、') || '暂无建议频道'}</p>}
    </section>)}</div>
    {invalidNames && <p role="alert" className="workspace-error">新分组名称不能为空或与已有分组重复；请选择已有组进行合并，或修改新名称。</p>}
    <footer className="workspace-preview-actions"><span>将处理 {selected.length} 个主题、{new Set(selected.flatMap(draft => draft.source_ids)).size} 个频道；仅新增归属。</span><div className="workspace-actions"><Button type="button" variant="outline" className="flex-1 sm:flex-none" disabled={busy} onClick={onCancel}>取消预览</Button><Button type="button" className="flex-1 sm:flex-none" disabled={busy || !selected.length || invalidNames} onClick={() => onApply({ mode, groups: selected.map(draft => ({ topic_key: draft.topic_key, source_ids: draft.source_ids, ...(draft.group_id ? { group_id: Number(draft.group_id) } : { name: draft.name.trim() }) })) })}>{busy ? '正在应用…' : '确认应用分组'}</Button></div></footer>
  </>
}

export function SiteClassifierPanel({ viewer }: { viewer: number }) {
  const client = useQueryClient()
  const classification = useClassificationModel(viewer, true)
  const data = useQuery({ queryKey: ['workspace', viewer, 'site-classifier'], queryFn: ({ signal }) => workspaceRequest<SiteClassifier>('/admin/smart-channels/', { signal }) })
  const save = useMutation({ mutationFn: (body: unknown) => workspaceRequest<SiteClassifier>('/admin/smart-channels/', { method: 'PATCH', body }), onSuccess: value => client.setQueryData(['workspace', viewer, 'site-classifier'], value) })
  return <details className="workspace-panel"><summary>管理员：全站新增来源分类</summary><p className="workspace-muted">默认关闭。开启后，后台仅对信息充足但主题未知的全站来源调用本管理员的模型连接；不使用其他用户额度，不替任何人订阅。</p>
    {data.isError && <p role="alert" className="workspace-error">读取失败。<button type="button" onClick={() => void data.refetch()}>重试</button></p>}
    {data.data?.runtime && <div className="workspace-soft-panel" aria-label="后台分类状态">
      <p role="status">{!data.data.enabled ? '后台分类已关闭' : !data.data.runtime.feature_enabled
        ? '站点 AI 开关已关闭，不会派发分类' : !data.data.runtime.model_binding_valid
          ? '后台模型授权不可用，请重新确认并保存' : '后台模型授权与开关就绪'}</p>
      <p>今日已入队 {data.data.runtime.daily_used} / {data.data.daily_limit} 个任务，剩余 {data.data.runtime.daily_remaining} 个。</p>
      <p>排队 {data.data.runtime.job_counts.queued ?? 0}，执行中 {data.data.runtime.job_counts.running ?? 0}，失败 {data.data.runtime.job_counts.failed ?? 0}，已取消 {data.data.runtime.job_counts.cancelled ?? 0}。</p>
      {data.data.runtime.expired_leases > 0 && <p className="workspace-error">{data.data.runtime.expired_leases} 个任务运行已过期，等待后台核对；不会自动重发已派发的调用。</p>}
      {data.data.runtime.failed_dispatched_jobs > 0 && <p>有 {data.data.runtime.failed_dispatched_jobs} 个已派发任务失败，请查看下方记录；此处不重新调用模型。</p>}
      {data.data.runtime.next_retry_at && <p>下一次限流等待时间：{new Date(data.data.runtime.next_retry_at).toLocaleString()}</p>}
      <button type="button" className="workspace-button secondary" disabled={data.isFetching || save.isPending} onClick={() => void data.refetch()}>刷新后台状态</button>
    </div>}
    {data.data && <SiteClassifierForm key={JSON.stringify([data.data.enabled, data.data.daily_limit, data.data.is_owner, data.data.model_id])} config={data.data} classification={classification} busy={save.isPending} onSave={body => save.mutate(body)} />}
    {save.isError && <p role="alert" className="workspace-error">{workspaceError(save.error)}</p>}
    {save.isSuccess && <p role="status" className="workspace-notice">站点分类设置已保存。</p>}
    {data.data && <><h3>最近分类任务</h3><ul className="workspace-job-list">{data.data.jobs.map(job => <li key={job.id}><span>{job.source_ids.length} 个来源 · {new Date(job.created_at).toLocaleString()}</span><span>{proposalStatus[job.status] ?? job.status}</span><small>{job.error_code && (errorMessages[job.error_code] ?? job.error_code)}</small></li>)}</ul>
      <h3>待接入申请</h3><p className="workspace-caption">这些地址未启用抓取；需另行核验官方 API/RSS 并登记采集策略。</p><ul className="workspace-intake-list">{data.data.intake_requests.map(item => <li key={item.id}><code>{item.url}</code><span>{item.status === 'pending' ? '待审核接入' : item.status}</span></li>)}</ul></>}
  </details>
}
function SiteClassifierForm({ config, classification, busy, onSave }: { config: SiteClassifier; classification: ReturnType<typeof useClassificationModel>; busy: boolean; onSave: (body: unknown) => void }) {
  const [enabled, setEnabled] = useState(config.enabled)
  const [limit, setLimit] = useState(config.daily_limit)
  const [confirmedModel, setConfirmedModel] = useState<string | null>(null)
  const consent = Boolean(classification.id && confirmedModel === classification.consentKey)
  return <form className="workspace-soft-panel" onSubmit={event => { event.preventDefault(); onSave({ enabled, daily_limit: limit, consent, ...(enabled ? { model_config_id: classification.id } : {}) }); setConfirmedModel(null) }}>
    <p className="workspace-caption">关闭、更换授权模型或降低预算会中止未完成的全站分类；在途请求可能仍产生费用，但旧任务不会再写入结果。已完成的主题和私人分组保留。</p>
    <label className="workspace-check"><input type="checkbox" checked={enabled} disabled={busy} onChange={event => setEnabled(event.target.checked)} />开启全站新来源 AI 分类</label>
    <label>每日任务上限（仅明确限流拒绝时最多重试一次）<input type="number" min={1} max={20} required value={limit} disabled={busy} onChange={event => setLimit(Number(event.target.value))} /></label>
    {enabled && <>
      <p>后台分类授权模型：{classification.model ? `${classification.model.display_name} (${classification.model.model_id})` : '请先配置并验证个人默认模型'}；保存后固定本次授权，修改默认偏好不会静默更换后台模型。</p>
      <label className="workspace-check"><input type="checkbox" checked={consent} disabled={busy || !classification.id}
        onChange={event => setConfirmedModel(event.target.checked ? classification.consentKey : null)} />单独授权上述本人模型及本站每日预算处理公开来源；不使用其他用户额度。</label>
    </>}
    <button className="workspace-button" disabled={busy || (enabled && !consent)}>保存站点设置</button>
  </form>
}
