import { useEffect, useId, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { NativeSelect } from '@/components/ui/native-select'
import { useDefaultAIModel } from '@/hooks/useDefaultAIModel'
import { channelKeys } from '@/services/channelQueries'
import { newsKeys } from '@/services/newsQueries'
import { workspaceError, workspaceKeys, workspaceRequest, proposalStatus, type GroupingConfig, type GroupingMode, type Proposal, type ProposalPage } from '@/services/workspaceApi'
import type { ChannelGroup } from '@/types/channels'

interface CreateSnapshot { target: 'groups'; source_ids: number[]; engine: 'rules'; consent: false; request_id: string }
export default function ExistingGroupOrganizer({ viewer, initialConfig, groups, subscriptions }: {
  viewer: number; initialConfig: GroupingConfig; groups: ChannelGroup[]; subscriptions: Array<{ id: number; groupIds: number[] }>
}) {
  const client = useQueryClient()
  // Only explicitly edited fields are drafts. Untouched fields follow the
  // authoritative query when another settings entry point updates it.
  const [draft, setDraft] = useState<{ mode?: GroupingMode; matchExisting?: boolean; aiEnabled?: boolean; limit?: number }>({})
  const mode = draft.mode ?? initialConfig.mode
  const matchExisting = draft.matchExisting ?? initialConfig.match_existing ?? true
  const aiEnabled = draft.aiEnabled ?? initialConfig.ai_enabled ?? false
  const limit = draft.limit ?? initialConfig.daily_limit ?? 5
  const effectiveAiEnabled = aiEnabled && mode !== 'off'
  const model = useDefaultAIModel(viewer, 'default', aiEnabled)
  const consentKey = JSON.stringify([model.selection?.model_config_id, model.data?.revision])
  const [confirmedModel, setConfirmedModel] = useState<string | null>(null)
  const consent = !!model.selection?.model_config_id && !model.isError && confirmedModel === consentKey
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
    onSuccess: value => { if (!current()) return; setSnapshot(null); client.setQueryData(workspaceKeys.proposal(viewer, value.id), value); setActiveId(value.id); void refresh() },
    onSettled: () => { writing.current = false } })
  const change = useMutation({ mutationFn: ({ id, action, body }: { id: string; action: 'apply' | 'cancel' | 'undo'; body?: unknown }) =>
    workspaceRequest<Proposal>('/me/smart-channels/proposals/' + id + '/' + action + '/', { ...options(), method: 'POST', body: body ?? {} }),
    onSuccess: value => { if (!current()) return; client.setQueryData(workspaceKeys.proposal(viewer, value.id), value)
      setNotice(value.status === 'applied' ? '已加入确认的已有分组。' : value.status === 'undone' ? '已撤销本次新增归属，后续人工调整保留。' : '任务已取消。'); void refresh() },
    onSettled: () => { writing.current = false } })
  const save = useMutation({ mutationFn: (body: unknown) => workspaceRequest<GroupingConfig>('/me/smart-channels/settings/', { ...options(), method: 'PATCH', body }),
    onSuccess: value => { if (!current()) return; client.setQueryData(workspaceKeys.config(viewer), value); setDraft({}); setConfirmedModel(null); setNotice('自动整理设置已保存。'); void refresh() },
    onSettled: () => { writing.current = false } })
  const busy = create.isPending || change.isPending || save.isPending
  const processing = !!active.data && ['queued', 'running'].includes(active.data.status)
  const ungrouped = subscriptions.filter(item => item.groupIds.length === 0)
  const start = () => {
    if (!current() || writing.current || !groups.length || !ungrouped.length) return
    const body = snapshot ?? { target: 'groups', source_ids: ungrouped.slice(0, 200).map(item => item.id), engine: 'rules', consent: false, request_id: crypto.randomUUID() } satisfies CreateSnapshot
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
  return <div className="workspace-page workspace-smart">
    <header className="workspace-page-heading"><div><Badge variant="sage" className="mb-2">主流程</Badge><p className="workspace-eyebrow">按你的方式阅读</p><h1>智能整理</h1><p>将新订阅匹配到已有个人分组；人工调整始终优先。</p></div><Button asChild variant="outline"><Link to="/channels/groups">管理分组</Link></Button></header>
    <nav aria-label="已有分组整理步骤"><ol className="smart-steps">
      {['频道', '建议的已有分组', '匹配依据', '调整并确认'].map((label, index) => <li key={label}><span>{index + 1}</span>{label}</li>)}
    </ol></nav>
    <section className="workspace-panel"><h2>整理已有订阅</h2><p>基于已保存的频道资料，把未分组频道匹配到已有个人分组；不调用模型，也不会新建分组。</p>
      <p className="workspace-caption">已订阅 {subscriptions.length} 个 · 未分组 {ungrouped.length} 个 · 已有分组 {groups.length} 个</p>
      <Button type="button" disabled={busy || processing || change.isError || !groups.length || !ungrouped.length} onClick={start}>{snapshot && create.isError ? '重试同一次整理' : '整理未分组频道'}</Button>
      {!groups.length && <p role="status">请先创建个人分组，再整理频道。</p>}
      {!ungrouped.length && <p role="status">所有已订阅频道都已分组。</p>}
      {ungrouped.length > 200 && <p>每次最多整理 200 个频道，本次处理前 200 个未分组频道；确认后可继续整理余下频道。</p>}
      {create.isError && <p role="alert">{workspaceError(create.error)} 创建结果尚未确认，重试会复用同一个请求编号。</p>}
    </section>
    <section className="workspace-panel" aria-label="自动整理设置"><h2>以后新增订阅时</h2>
      <p className="workspace-caption">首次开启仅处理之后新增的订阅；已有频道请使用上方按钮。修改选项后需保存。</p>
      <label>自动整理模式<NativeSelect aria-label="自动整理模式" value={mode} disabled={busy} onChange={event => {
        const nextMode = event.target.value as GroupingMode
        setDraft(current => ({ ...current, mode: nextMode, ...(nextMode === 'off' ? { aiEnabled: false } : {}) }))
        if (nextMode === 'off') setConfirmedModel(null)
      }}>
        <option value="auto">自动加入已有分组</option><option value="suggest">仅生成待确认建议</option><option value="off">关闭自动整理</option>
      </NativeSelect></label>
      <p className="workspace-caption">自动模式仅应用可信资料的明确匹配；AI 和模糊结果始终等待你确认。</p>
      <label className="workspace-check"><Input className="size-4 shrink-0" type="checkbox" checked={matchExisting} disabled={busy} onChange={event => setDraft(current => ({ ...current, matchExisting: event.target.checked }))} />匹配已有个人分组</label>
      <label className="workspace-check"><Input className="size-4 shrink-0" type="checkbox" checked={aiEnabled} disabled={busy || (!aiEnabled && (!initialConfig.ai_available || mode === 'off'))} onChange={event => { setDraft(current => ({ ...current, aiEnabled: event.target.checked })); setConfirmedModel(null) }} />后台 AI 生成待确认建议</label>
      {!initialConfig.ai_available && <p className="workspace-caption">当前站点未开放 AI 整理；资料规则整理仍可使用。</p>}
      {aiEnabled && <div className="workspace-soft-panel">
        <p>授权模型：{model.selection?.model ? `${model.selection.model.display_name} (${model.selection.model.model_id})` : model.isError ? '默认模型读取失败，请重试。' : '请先在 AI 设置中保存并验证默认模型。'}</p>
        {model.isError && <Button type="button" variant="outline" onClick={() => void model.refetch()}>重试读取模型</Button>}
        <p className="workspace-caption">保存后固定本次授权模型。后台可能产生费用；仅使用频道简介、近期标题和已有分组，不使用阅读记录或对话。关闭授权会阻止后续派发和旧结果写入。</p>
        {initialConfig.ai_model_id && <p className="workspace-caption">当前后台已授权模型：{initialConfig.ai_model_id}</p>}
        <label>每日 AI 任务上限（1–20）<Input type="number" min={1} max={20} value={limit} disabled={busy} onChange={event => setDraft(current => ({ ...current, limit: Number(event.target.value) }))} /></label>
        <label className="workspace-check"><Input className="size-4 shrink-0" type="checkbox" checked={consent} disabled={busy || !model.selection || model.isError} onChange={event => setConfirmedModel(event.target.checked ? consentKey : null)} />单独授权上述本人模型及每日预算，在后台生成待确认建议。</label>
      </div>}
      <Button type="button" variant="outline" disabled={busy || (effectiveAiEnabled && (!initialConfig.ai_available || !consent || !matchExisting)) || !Number.isInteger(limit) || limit < 1 || limit > 20} onClick={() => {
        if (!current() || writing.current) return
        writing.current = true
        save.mutate({ mode, match_existing: matchExisting, ai_enabled: effectiveAiEnabled, daily_limit: limit, ...(effectiveAiEnabled ? { consent: true, model_config_id: model.selection?.model_config_id } : {}) })
      }}>保存自动整理设置</Button>
      {save.isError && <p role="alert">{workspaceError(save.error)} 请重新读取设置核对保存结果。</p>}
      {initialConfig.error_code === 'too_many_groups' && <p role="status">个人分组超过本次整理上限（200 个），后台整理已暂停；可先调整分组。</p>}
      {summary && <p role="status">等待处理 {summary.pending} · 待确认 {summary.suggested} · 已应用 {summary.applied}</p>}
    </section>
    {notice && <p role="status" className="workspace-notice">{notice}</p>}
    {activeId && <section className="workspace-panel" aria-label="已有分组建议"><h2 ref={previewHeading} tabIndex={-1}>分组建议</h2>
      {active.isPending && <p role="status">正在读取建议…</p>}
      {active.isError && <p role="alert">建议读取失败。<Button variant="outline" onClick={() => void active.refetch()}>重试读取建议</Button></p>}
      {change.isError && <div role="alert"><p>{workspaceError(change.error)} 操作结果尚未确认，请先核对状态；不会自动重复应用或撤销。</p>
        <Button disabled={active.isFetching} variant="outline" onClick={async () => { const result = await active.refetch(); if (current() && result.isSuccess) change.reset() }}>读取操作结果</Button></div>}
      {!active.isError && active.data && <>
        <p role="status">{proposalStatus[active.data.status] ?? active.data.status}</p>
        {processing && <p>任务已保存，可稍后从记录恢复。</p>}
        {active.data.status === 'failed' && <p role="alert">任务未完成，未应用分组。请重新整理或检查频道资料。</p>}
        {active.data.status === 'ready' && active.data.target === 'groups' && <ExistingAssignments key={active.data.id} proposal={active.data} groups={groups} busy={busy || change.isError || active.isFetching} onApply={assignments => act('apply', { assignments })} />}
        {active.data.status === 'ready' && active.data.target !== 'groups' && <p>这是主题预设任务，请在高级整理入口中查看。</p>}
        {['queued', 'running', 'ready'].includes(active.data.status) && <Button type="button" variant="outline" disabled={busy || change.isError || active.isFetching} onClick={() => act('cancel')}>取消任务</Button>}
        {active.data.status === 'applied' && <><p>已新增 {active.data.applied_count} 条分组归属。</p><Button type="button" variant="outline" disabled={busy || change.isError || active.isFetching} onClick={() => act('undo')}>撤销本次新增归属</Button></>}
      </>}
    </section>}
    <section className="workspace-panel"><header className="workspace-panel-heading"><h2>建议与整理记录</h2><Button type="button" variant="ghost" disabled={busy || history.isFetching} onClick={() => void history.refetch()}>刷新记录</Button></header>
      {history.isError ? <p role="alert">记录加载失败，请刷新重试。</p> : history.isPending ? <p role="status">正在读取记录…</p> : <ul className="workspace-job-list">{(history.data?.results ?? []).filter(item => item.target === 'groups').map(item => <li key={item.id}>
        <span><strong>{item.engine === 'ai' ? 'AI 建议' : '频道资料匹配'}</strong><small>{new Date(item.created_at).toLocaleString()} · {item.source_ids.length} 个频道</small></span><span>{proposalStatus[item.status] ?? item.status}</span>
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

function ExistingAssignments({ proposal, groups, busy, onApply }: { proposal: Proposal; groups: ChannelGroup[]; busy: boolean; onApply: (assignments: Array<{ source_id: number; group_ids: number[] }>) => void }) {
  const editorId = useId()
  const [expanded, setExpanded] = useState<number | null>(null)
  const [assignments, setAssignments] = useState(() => proposal.result.map(item => ({ source_id: item.source_id, group_ids: (item.group_ids ?? []).filter(id => groups.some(group => group.id === id)) })))
  const selected = assignments.map(item => ({ ...item, group_ids: item.group_ids.filter(id => groups.some(group => group.id === id)) })).filter(item => item.group_ids.length)
  return <>
    <p>以下建议尚未写入个人分组。勾选已有分组后确认，仅新增归属。</p>
    {proposal.result.map(item => {
      const row = assignments.find(assignment => assignment.source_id === item.source_id)
      const groupNames = (row?.group_ids ?? []).map(id => groups.find(group => group.id === id)?.name).filter(Boolean)
      const unmatched = groupNames.length === 0
      return <fieldset key={item.source_id} className="workspace-soft-panel" onKeyDown={event => {
        if (event.key === 'Escape' && expanded === item.source_id) { event.preventDefault(); event.stopPropagation(); setExpanded(null); document.getElementById(editorId + item.source_id + '-toggle')?.focus() }
      }}><legend className="flex flex-wrap items-center gap-2"><span>{item.name}</span><Badge variant={unmatched ? 'gray' : item.needs_review ? 'amber' : 'sage'}>{unmatched ? '未匹配' : item.needs_review ? '待确认' : '建议匹配'}</Badge></legend>
        <dl className="grid gap-2 text-sm"><div><dt className="font-medium">建议的已有分组</dt><dd className="break-words text-muted-foreground">{unmatched ? '未匹配到可靠的已有分组' : groupNames.join('、')}</dd></div>
          <div><dt className="font-medium">匹配依据</dt><dd className="break-words text-muted-foreground">{item.reason}</dd></div></dl>
        {unmatched ? <p className="workspace-caption">待确认：保持未分组，或手动选择已有分组。</p>
          : item.needs_review ? <p className="workspace-caption">待确认：请核对建议的已有分组与匹配依据。</p>
            : <p className="workspace-caption">建议已匹配到已有分组，确认前仍可调整。</p>}
        <Button type="button" variant="ghost" id={editorId + item.source_id + '-toggle'} aria-label={'调整 ' + item.name + ' 的建议分组'}
          aria-controls={editorId + item.source_id} aria-expanded={expanded === item.source_id}
          onClick={() => setExpanded(current => current === item.source_id ? null : item.source_id)}>调整建议分组</Button>
        {expanded === item.source_id && <div id={editorId + item.source_id} className="flex max-h-64 flex-wrap gap-3 overflow-y-auto">{groups.map(group => <label key={group.id} className="workspace-check break-words"><Input className="size-4 shrink-0" type="checkbox" disabled={busy} checked={row?.group_ids.includes(group.id) ?? false}
          onChange={event => setAssignments(current => current.map(assignment => assignment.source_id === item.source_id ? { ...assignment, group_ids: event.target.checked ? [...assignment.group_ids, group.id] : assignment.group_ids.filter(id => id !== group.id) } : assignment))} />{group.name}</label>)}</div>}
      </fieldset>
    })}
    <Button type="button" disabled={busy || !selected.length} onClick={() => onApply(selected)}>确认加入分组</Button>
  </>
}
