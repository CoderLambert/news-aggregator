import { useEffect, useId, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Sparkles } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { NativeSelect } from '@/components/ui/native-select'
import { useDefaultAIModel } from '@/hooks/useDefaultAIModel'
import { channelKeys } from '@/services/channelQueries'
import { newsKeys } from '@/services/newsQueries'
import { workspaceError, workspaceKeys, workspaceRequest, proposalStatus, type GroupingConfig, type GroupingMode, type NewGroupPath, type Proposal, type ProposalItem, type ProposalPage } from '@/services/workspaceApi'
import { channelGroupPath, type ChannelGroup, type ChannelGroupRoot } from '@/types/channels'

interface CreateSnapshot {
  target: 'groups'; source_ids: number[]; engine: 'rules' | 'ai'; consent: boolean; request_id: string; model_config_id?: string
}
export default function ExistingGroupOrganizer({ viewer, initialConfig, roots, groups, subscriptions }: {
  viewer: number; initialConfig: GroupingConfig; roots: ChannelGroupRoot[]; groups: ChannelGroup[]; subscriptions: Array<{ id: number; groupIds: number[] }>
}) {
  const client = useQueryClient()
  const [engine, setEngine] = useState<'rules' | 'ai'>(initialConfig.ai_available ? 'ai' : 'rules')
  const [scope, setScope] = useState<'ungrouped' | 'all'>('ungrouped')
  // Only explicitly edited fields are drafts. Untouched fields follow the
  // authoritative query when another settings entry point updates it.
  const [draft, setDraft] = useState<{ mode?: GroupingMode; matchExisting?: boolean; aiEnabled?: boolean; limit?: number }>({})
  const mode = draft.mode ?? initialConfig.mode
  const matchExisting = draft.matchExisting ?? initialConfig.match_existing ?? true
  const aiEnabled = draft.aiEnabled ?? initialConfig.ai_enabled ?? false
  const limit = draft.limit ?? initialConfig.daily_limit ?? 5
  const effectiveAiEnabled = aiEnabled && mode !== 'off'
  const model = useDefaultAIModel(viewer, 'default', aiEnabled || engine === 'ai')
  const consentKey = JSON.stringify([model.selection?.model_config_id, model.data?.revision])
  const [confirmedModel, setConfirmedModel] = useState<string | null>(null)
  const [confirmedPreviewModel, setConfirmedPreviewModel] = useState<string | null>(null)
  const backgroundConsent = !!model.selection?.model_config_id && !model.isError && confirmedModel === consentKey
  const previewConsent = !!model.selection?.model_config_id && !model.isError && confirmedPreviewModel === consentKey
  const [historyPage, setHistoryPage] = useState(1)
  const [activeId, setActiveId] = useState<string | null>(null)
  const [snapshot, setSnapshot] = useState<CreateSnapshot | null>(null)
  const [notice, setNotice] = useState('')
  const lifetime = useRef<AbortController | null>(null)
  const writing = useRef(false)
  const previewHeading = useRef<HTMLHeadingElement>(null)
  const focusPreview = useRef(false)
  useEffect(() => {
    const controller = new AbortController(); lifetime.current = controller
    return () => { controller.abort(); lifetime.current = null }
  }, [])
  const current = () => !!lifetime.current && !lifetime.current.signal.aborted
  const options = () => ({ viewer, signal: lifetime.current?.signal })
  const history = useQuery({ queryKey: workspaceKeys.proposalHistory(viewer, 'groups', historyPage), retry: false, refetchOnWindowFocus: false,
    queryFn: ({ signal }) => workspaceRequest<ProposalPage>('/me/smart-channels/proposals/?target=groups&page=' + historyPage, { signal, viewer }),
    refetchInterval: query => query.state.status !== 'error' && query.state.data?.results.some(item => ['queued', 'running'].includes(item.status)) ? 3000 : false })
  const active = useQuery({ queryKey: workspaceKeys.proposal(viewer, activeId), enabled: !!activeId, retry: false, refetchOnWindowFocus: false,
    queryFn: ({ signal }) => workspaceRequest<Proposal>('/me/smart-channels/proposals/' + activeId + '/', { signal, viewer }),
    refetchInterval: query => query.state.status !== 'error' && ['queued', 'running'].includes(query.state.data?.status ?? '') ? 2000 : false })
  const refresh = async () => {
    if (!current()) return
    await Promise.all([client.invalidateQueries({ queryKey: workspaceKeys.config(viewer) }), client.invalidateQueries({ queryKey: workspaceKeys.proposals(viewer) }),
      client.invalidateQueries({ queryKey: channelKeys.personal(viewer) }), client.invalidateQueries({ queryKey: newsKeys.lists() })])
  }
  const create = useMutation({ mutationFn: (body: CreateSnapshot) => workspaceRequest<Proposal>('/me/smart-channels/proposals/', { ...options(), method: 'POST', body }),
    onSuccess: value => {
      if (!current()) return
      setSnapshot(null); setConfirmedPreviewModel(null)
      client.setQueryData(workspaceKeys.proposal(viewer, value.id), value); setActiveId(value.id); void refresh()
    },
    onSettled: () => { writing.current = false } })
  const change = useMutation({ mutationFn: ({ id, action, body }: { id: string; action: 'apply' | 'cancel' | 'undo'; body?: unknown }) =>
    workspaceRequest<Proposal>('/me/smart-channels/proposals/' + id + '/' + action + '/', { ...options(), method: 'POST', body: body ?? {} }),
    onSuccess: value => {
      if (!current()) return
      client.setQueryData(workspaceKeys.proposal(viewer, value.id), value)
      setNotice(value.status === 'applied' ? '全部确认的分组已一次应用。' : value.status === 'undone' ? '已撤销本次新增归属，后续人工调整保留。' : '任务已取消。')
      void refresh()
    },
    onSettled: () => { writing.current = false } })
  const save = useMutation({ mutationFn: (body: unknown) => workspaceRequest<GroupingConfig>('/me/smart-channels/settings/', { ...options(), method: 'PATCH', body }),
    onSuccess: value => { if (!current()) return; client.setQueryData(workspaceKeys.config(viewer), value); setDraft({}); setConfirmedModel(null); setNotice('自动整理设置已保存。'); void refresh() },
    onSettled: () => { writing.current = false } })
  const busy = create.isPending || change.isPending || save.isPending
  const processing = !!active.data && ['queued', 'running'].includes(active.data.status)
  const ungrouped = subscriptions.filter(item => item.groupIds.length === 0)
  const candidates = scope === 'all' ? subscriptions : ungrouped
  const batchLimit = engine === 'ai' ? 40 : 200
  const sourceIds = candidates.slice(0, batchLimit).map(item => item.id)
  const setupLocked = busy || processing || !!snapshot
  const start = () => {
    const modelConfigId = model.selection?.model_config_id ?? undefined
    if (!current() || writing.current || !sourceIds.length || (engine === 'rules' && !groups.length)
      || (engine === 'ai' && (!previewConsent || !modelConfigId))) return
    const body: CreateSnapshot = snapshot ?? {
      target: 'groups', source_ids: sourceIds, engine, consent: engine === 'ai',
      request_id: crypto.randomUUID(), ...(engine === 'ai' ? { model_config_id: modelConfigId } : {}),
    }
    setSnapshot(body); writing.current = true; focusPreview.current = true; create.mutate(body)
  }
  const act = (action: 'apply' | 'cancel' | 'undo', body?: unknown) => {
    if (!current() || writing.current || !activeId || active.isError || change.isError) return
    writing.current = true; change.mutate({ id: activeId, action, body })
  }
  useEffect(() => {
    if (focusPreview.current && active.data && previewHeading.current) { previewHeading.current.focus(); focusPreview.current = false }
  }, [active.data])
  const summary = initialConfig.summary
  const step = processing ? 2 : active.data?.status === 'ready' ? 3 : ['applied', 'undone'].includes(active.data?.status ?? '') ? 4 : 1
  return <div className="workspace-page workspace-smart">
    <header className="workspace-page-heading"><div><Badge variant="sage" className="mb-2">批量整理</Badge><p className="workspace-eyebrow">少一点整理，多一点阅读</p><h1>AI 自动分组</h1><p>一次分析多个频道，复用合适的已有分组，并建议必要的新分组；确认一次即可批量应用。</p></div><Button asChild variant="outline"><Link to="/channels/groups">管理分组</Link></Button></header>
    <nav aria-label="自动分组步骤"><ol className="smart-steps">
      {['选择范围', 'AI 分析', '检查建议', '批量应用'].map((label, index) => <li key={label} aria-current={step === index + 1 ? 'step' : undefined}><span>{index + 1}</span>{label}</li>)}
    </ol></nav>
    <section className="workspace-panel"><header className="workspace-panel-heading"><div><h2>生成分组建议</h2><p className="workspace-caption">默认只整理未分组频道，不会移动或删除已有归属。</p></div></header>
      <div className="workspace-engine-options" role="group" aria-label="分组建议方式">
        <Button type="button" variant="outline" aria-pressed={engine === 'ai'} disabled={!initialConfig.ai_available || setupLocked} onClick={() => setEngine('ai')}><Sparkles size={14} aria-hidden="true" />AI 自动规划</Button>
        <Button type="button" variant="outline" aria-pressed={engine === 'rules'} disabled={setupLocked} onClick={() => { setEngine('rules'); setConfirmedPreviewModel(null) }}>免费规则匹配</Button>
      </div>
      <label>整理范围<NativeSelect className="mt-1" aria-label="整理范围" value={scope} disabled={setupLocked} onChange={event => setScope(event.target.value === 'all' ? 'all' : 'ungrouped')}>
        <option value="ungrouped">仅未分组频道（推荐）</option><option value="all">全部已订阅频道</option>
      </NativeSelect></label>
      <p className="workspace-caption">已订阅 {subscriptions.length} 个 · 未分组 {ungrouped.length} 个 · 本次 {sourceIds.length} 个 · 已有分组 {groups.length} 个</p>
      {engine === 'ai' && <div className="workspace-soft-panel">
        <p><strong>本次模型：</strong>{model.selection?.model ? `${model.selection.model.display_name} (${model.selection.model.model_id})`
          : model.isError ? '模型设置读取失败。' : '请先保存并验证默认模型。'} <Link className="workspace-link" to="/settings/ai">模型设置</Link></p>
        {model.isError && <Button type="button" variant="outline" onClick={() => void model.refetch()}>重试读取模型</Button>}
        <p className="workspace-caption">模型会读取所选频道的公开简介、近期标题，以及你的已有分组名称和少量示例。它可以建议最多 8 个新分组，但不会直接写入，所有结果都需你确认。</p>
        <label className="workspace-check"><Input className="size-4 shrink-0" type="checkbox" checked={previewConsent} disabled={setupLocked || !model.selection || model.isError}
          onChange={event => setConfirmedPreviewModel(event.target.checked ? consentKey : null)} />同意本次使用上述个人模型额度生成分组建议。</label>
      </div>}
      {!initialConfig.ai_available && <p className="workspace-caption">当前站点未开放 AI 整理；仍可使用免费规则匹配。<Link to="/settings/ai">检查模型设置</Link></p>}
      {engine === 'rules' && <p className="workspace-caption">规则匹配只复用名称对应的已有分组，不调用模型，也不会创建新分组。</p>}
      <div className="workspace-actions"><Button type="button" disabled={busy || processing || change.isError || !sourceIds.length || (engine === 'rules' && !groups.length)
        || (engine === 'ai' && !previewConsent)} onClick={start}>{create.isPending ? '正在创建任务…' : snapshot && create.isError ? '重试同一次建议' : engine === 'ai' ? '生成 AI 分组建议' : '匹配到已有分组'}</Button></div>
      {engine === 'rules' && !groups.length && <p role="status">还没有个人分组；请选择 AI 自动规划，或先创建一个分组。</p>}
      {!candidates.length && <p role="status">{scope === 'ungrouped' ? '所有已订阅频道都已分组，可切换为“全部已订阅频道”。' : '还没有已订阅频道。'}</p>}
      {candidates.length > batchLimit && <p role="status">本次最多处理 {batchLimit} 个频道；应用后可继续整理剩余频道。</p>}
      {create.isError && <div role="alert" className="workspace-soft-panel"><p>{workspaceError(create.error)} 创建结果尚未确认，重试会复用同一个请求编号。</p>
        <Button type="button" variant="ghost" onClick={() => { setSnapshot(null); create.reset() }}>放弃本次请求并重新选择</Button></div>}
    </section>
    <section className="workspace-panel" aria-label="自动整理设置"><h2>以后新增订阅时</h2>
      <p className="workspace-caption">这是独立的后台设置。首次开启只处理之后新增的订阅；已有频道请使用上方的一次性整理。</p>
      <label>自动整理模式<NativeSelect aria-label="自动整理模式" value={mode} disabled={busy} onChange={event => {
        const nextMode = event.target.value as GroupingMode
        setDraft(current => ({ ...current, mode: nextMode, ...(nextMode === 'off' ? { aiEnabled: false } : {}) }))
        if (nextMode === 'off') setConfirmedModel(null)
      }}>
        <option value="auto">自动加入已有分组</option><option value="suggest">仅生成待确认建议</option><option value="off">关闭自动整理</option>
      </NativeSelect></label>
      <p className="workspace-caption">自动模式只应用可信资料的明确匹配；AI 和模糊结果始终等待你确认，也不会在后台创建新分组。</p>
      <label className="workspace-check"><Input className="size-4 shrink-0" type="checkbox" checked={matchExisting} disabled={busy} onChange={event => setDraft(current => ({ ...current, matchExisting: event.target.checked }))} />匹配已有个人分组</label>
      <label className="workspace-check"><Input className="size-4 shrink-0" type="checkbox" checked={aiEnabled} disabled={busy || (!aiEnabled && (!initialConfig.ai_available || mode === 'off'))} onChange={event => { setDraft(current => ({ ...current, aiEnabled: event.target.checked })); setConfirmedModel(null) }} />后台 AI 生成待确认建议</label>
      {!initialConfig.ai_available && <p className="workspace-caption">当前站点未开放 AI 整理；资料规则整理仍可使用。</p>}
      {aiEnabled && <div className="workspace-soft-panel">
        <p>授权模型：{model.selection?.model ? `${model.selection.model.display_name} (${model.selection.model.model_id})` : model.isError ? '默认模型读取失败，请重试。' : '请先在 AI 设置中保存并验证默认模型。'}</p>
        {model.isError && <Button type="button" variant="outline" onClick={() => void model.refetch()}>重试读取模型</Button>}
        <p className="workspace-caption">保存后固定本次授权模型。后台可能产生费用；仅使用频道简介、近期标题和已有分组，不使用阅读记录或对话。关闭授权会阻止后续派发和旧结果写入。</p>
        {initialConfig.ai_model_id && <p className="workspace-caption">当前后台已授权模型：{initialConfig.ai_model_id}</p>}
        <label>每日 AI 任务上限（1–20）<Input type="number" min={1} max={20} value={limit} disabled={busy} onChange={event => setDraft(current => ({ ...current, limit: Number(event.target.value) }))} /></label>
        <label className="workspace-check"><Input className="size-4 shrink-0" type="checkbox" checked={backgroundConsent} disabled={busy || !model.selection || model.isError} onChange={event => setConfirmedModel(event.target.checked ? consentKey : null)} />单独授权上述本人模型及每日预算，在后台生成待确认建议。</label>
      </div>}
      <Button type="button" variant="outline" disabled={busy || (effectiveAiEnabled && (!initialConfig.ai_available || !backgroundConsent || !matchExisting)) || !Number.isInteger(limit) || limit < 1 || limit > 20} onClick={() => {
        if (!current() || writing.current) return
        writing.current = true
        save.mutate({ mode, match_existing: matchExisting, ai_enabled: effectiveAiEnabled, daily_limit: limit, ...(effectiveAiEnabled ? { consent: true, model_config_id: model.selection?.model_config_id } : {}) })
      }}>保存自动整理设置</Button>
      {save.isError && <p role="alert">{workspaceError(save.error)} 请重新读取设置核对保存结果。</p>}
      {initialConfig.error_code === 'too_many_groups' && <p role="status">个人分组超过本次整理上限（200 个），后台整理已暂停；可先调整分组。</p>}
      {summary && <p role="status">等待处理 {summary.pending} · 待确认 {summary.suggested} · 已应用 {summary.applied}</p>}
    </section>
    {notice && <p role="status" className="workspace-notice">{notice}</p>}
    {activeId && <section className="workspace-panel" aria-label="分组建议"><header className="workspace-panel-heading"><h2 ref={previewHeading} tabIndex={-1}>分组建议</h2>{active.data && <Badge variant="outline">{active.data.engine === 'ai' ? 'AI 规划' : '规则匹配'}</Badge>}</header>
      {active.isPending && <p role="status">正在读取建议…</p>}
      {active.isError && <p role="alert">建议读取失败。<Button variant="outline" onClick={() => void active.refetch()}>重试读取建议</Button></p>}
      {change.isError && <div role="alert"><p>{workspaceError(change.error)} 操作结果尚未确认，请先核对状态；不会自动重复应用或撤销。</p>
        <Button disabled={active.isFetching} variant="outline" onClick={async () => { const result = await active.refetch(); if (current() && result.isSuccess) change.reset() }}>读取操作结果</Button></div>}
      {!active.isError && active.data && <>
        <p role="status">{proposalStatus[active.data.status] ?? active.data.status}</p>
        {processing && <p>{active.data.engine === 'ai' ? 'AI 正在规划分组' : '任务正在处理'}，任务已保存，可关闭页面并稍后从记录恢复。</p>}
        {active.data.status === 'failed' && <p role="alert">任务未完成，未应用分组。请重新整理或检查模型与频道资料。</p>}
        {active.data.status === 'ready' && active.data.target === 'groups' && <ExistingAssignments key={active.data.id} proposal={active.data} roots={roots} groups={groups} busy={busy || change.isError || active.isFetching} onApply={assignments => act('apply', { assignments })} />}
        {active.data.status === 'ready' && active.data.target !== 'groups' && <p>这是主题预设任务，请在高级整理入口中查看。</p>}
        {['queued', 'running', 'ready'].includes(active.data.status) && <Button type="button" variant="outline" disabled={busy || change.isError || active.isFetching} onClick={() => act('cancel')}>取消任务</Button>}
        {active.data.status === 'applied' && <><p>已新增 {active.data.applied_count} 条分组归属。AI 新建的空分组会保留，避免撤销时误删你后续的调整。</p><Button type="button" variant="outline" disabled={busy || change.isError || active.isFetching} onClick={() => act('undo')}>撤销本次新增归属</Button></>}
      </>}
    </section>}
    <section className="workspace-panel"><header className="workspace-panel-heading"><h2>建议与整理记录</h2><Button type="button" variant="ghost" disabled={busy || history.isFetching} onClick={() => void history.refetch()}>刷新记录</Button></header>
      {history.isError ? <p role="alert">记录加载失败，请刷新重试。</p> : history.isPending ? <p role="status">正在读取记录…</p> : <ul className="workspace-job-list">{(history.data?.results ?? []).filter(item => item.target === 'groups').map(item => <li key={item.id}>
        <span><strong>{item.engine === 'ai' ? 'AI 自动分组' : '频道资料匹配'}</strong><small>{new Date(item.created_at).toLocaleString()} · {item.source_ids.length} 个频道</small></span><span>{proposalStatus[item.status] ?? item.status}</span>
        <Button type="button" variant="outline" disabled={busy || change.isError} onClick={() => { focusPreview.current = true; setActiveId(item.id); client.setQueryData(workspaceKeys.proposal(viewer, item.id), item) }}>{item.status === 'ready' ? '查看建议' : '查看任务'}</Button>
      </li>)}</ul>}
      <nav aria-label="分组整理记录翻页" className="mt-3 flex flex-wrap items-center gap-3">
        <Button type="button" variant="outline" disabled={busy || history.isFetching || historyPage === 1} onClick={() => setHistoryPage(page => page - 1)}>较新记录</Button>
        <span className="text-sm text-muted-foreground">第 {historyPage} 页</span>
        <Button type="button" variant="outline" disabled={busy || history.isFetching || history.isError || !history.data?.has_more} onClick={() => setHistoryPage(page => page + 1)}>较早记录</Button>
      </nav>
      {!history.isPending && !history.isError && !(history.data?.results ?? []).some(item => item.target === 'groups') && <p>{historyPage > 1 ? '本页没有更早的分组记录。' : '暂无分组建议或整理记录。'}</p>}
    </section>
  </div>
}

interface Assignment { source_id: number; group_ids: number[]; new_group_paths: NewGroupPath[] }
const pathKey = (path: NewGroupPath) => JSON.stringify([path.root_id, path.root_name, path.name])
const newPathLabel = (path: NewGroupPath, roots: ChannelGroupRoot[]) =>
  `${path.root_id ? roots.find(root => root.id === path.root_id)?.name ?? '未知根分类' : path.root_name} / ${path.name}`

function ExistingAssignments({ proposal, roots, groups, busy, onApply }: {
  proposal: Proposal; roots: ChannelGroupRoot[]; groups: ChannelGroup[]; busy: boolean; onApply: (assignments: Assignment[]) => void
}) {
  const editorId = useId()
  const [expanded, setExpanded] = useState<number | null>(null)
  const results = proposal.result as ProposalItem[]
  const proposedPaths = Array.from(new Map(results.flatMap(item => item.new_group_paths ?? []).map(path => [pathKey(path), path])).values())
  const [assignments, setAssignments] = useState<Assignment[]>(() => results.map(item => ({
    source_id: item.source_id,
    group_ids: (item.group_ids ?? []).filter(id => groups.some(group => group.id === id)),
    new_group_paths: item.new_group_paths ?? [],
  })))
  const selected = assignments.map(item => ({
    ...item,
    group_ids: item.group_ids.filter(id => groups.some(group => group.id === id)),
    new_group_paths: item.new_group_paths.filter(path => proposedPaths.some(candidate => pathKey(candidate) === pathKey(path))),
  })).filter(item => item.group_ids.length || item.new_group_paths.length)
  return <>
    <p>建议尚未写入。已为 {selected.length} 个频道规划 {new Set(selected.flatMap(item => [...item.group_ids.map(String), ...item.new_group_paths.map(pathKey)])).size} 个子分组；确认一次才会批量应用。</p>
    {proposedPaths.length > 0 && <p className="workspace-caption">AI 建议新建：{proposedPaths.map(path => newPathLabel(path, roots)).join('、')}。建议中的根分类和子分组在确认前都不会创建。</p>}
    {results.map(item => {
      const row = assignments.find(assignment => assignment.source_id === item.source_id)
      const existingNames = (row?.group_ids ?? []).map(id => groups.find(group => group.id === id)).filter((group): group is ChannelGroup => !!group).map(group => channelGroupPath(group, roots))
      const newPaths = row?.new_group_paths ?? []
      const assignedNames = [...existingNames, ...newPaths.map(path => newPathLabel(path, roots))]
      const unmatched = assignedNames.length === 0
      const status = unmatched ? '未匹配' : proposal.engine === 'ai' ? '待确认 AI 建议' : item.needs_review ? '待分析' : '已自动归类'
      return <fieldset key={item.source_id} className="workspace-soft-panel" onKeyDown={event => {
        if (event.key === 'Escape' && expanded === item.source_id) { event.preventDefault(); event.stopPropagation(); setExpanded(null); document.getElementById(editorId + item.source_id + '-toggle')?.focus() }
      }}><legend className="flex flex-wrap items-center gap-2"><span>{item.name}</span><Badge variant={unmatched ? 'gray' : newPaths.length ? 'amber' : 'sage'}>{status}</Badge></legend>
        <dl className="grid gap-2 text-sm"><div><dt className="font-medium">建议分组</dt><dd className="break-words text-muted-foreground">{unmatched ? '资料不足，暂时保持未分组' : assignedNames.join('、')}</dd></div>
          <div><dt className="font-medium">建议依据</dt><dd className="break-words text-muted-foreground">{item.reason}</dd></div></dl>
        <p className="workspace-caption">{unmatched ? '可手动选择任一已有或 AI 建议的新路径。' : '确认前可调整；不会删除这个频道原有的分组。'}</p>
        <Button type="button" variant="ghost" id={editorId + item.source_id + '-toggle'} aria-label={'调整 ' + item.name + ' 的建议分组'}
          aria-controls={editorId + item.source_id} aria-expanded={expanded === item.source_id}
          onClick={() => setExpanded(current => current === item.source_id ? null : item.source_id)}>调整建议分组</Button>
        {expanded === item.source_id && <div id={editorId + item.source_id} className="grid max-h-72 gap-3 overflow-y-auto">
          {groups.length > 0 && <fieldset><legend className="mb-2 text-sm font-medium">已有子分组</legend><div className="flex flex-wrap gap-3">{groups.map(group => <label key={group.id} className="workspace-check break-words"><Input className="size-4 shrink-0" type="checkbox" disabled={busy || (!(row?.group_ids.includes(group.id)) && (row?.group_ids.length ?? 0) + (row?.new_group_paths.length ?? 0) >= 3)} checked={row?.group_ids.includes(group.id) ?? false}
            onChange={event => setAssignments(current => current.map(assignment => assignment.source_id === item.source_id ? { ...assignment, group_ids: event.target.checked ? [...assignment.group_ids, group.id] : assignment.group_ids.filter(id => id !== group.id) } : assignment))} />{channelGroupPath(group, roots)}</label>)}</div></fieldset>}
          {proposedPaths.length > 0 && <fieldset><legend className="mb-2 text-sm font-medium">AI 建议新建路径</legend><div className="flex flex-wrap gap-3">{proposedPaths.map(path => <label key={pathKey(path)} className="workspace-check break-words"><Input className="size-4 shrink-0" type="checkbox" disabled={busy || (!(row?.new_group_paths.some(value => pathKey(value) === pathKey(path))) && (row?.group_ids.length ?? 0) + (row?.new_group_paths.length ?? 0) >= 3)} checked={row?.new_group_paths.some(value => pathKey(value) === pathKey(path)) ?? false}
            onChange={event => setAssignments(current => current.map(assignment => assignment.source_id === item.source_id ? { ...assignment, new_group_paths: event.target.checked ? [...assignment.new_group_paths, path] : assignment.new_group_paths.filter(value => pathKey(value) !== pathKey(path)) } : assignment))} />新建：{newPathLabel(path, roots)}</label>)}</div></fieldset>}
        </div>}
      </fieldset>
    })}
    <div className="workspace-preview-actions"><span>将处理 {selected.length} 个频道；只新增子分组与归属。</span><Button type="button" disabled={busy || !selected.length} onClick={() => onApply(selected)}>确认并批量应用</Button></div>
  </>
}
