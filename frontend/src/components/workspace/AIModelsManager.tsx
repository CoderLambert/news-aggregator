import { Box, Plus } from 'lucide-react'
import { ModelCombobox } from '@/components/ui/model-combobox'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { useEffect, useRef, useState, type FormEvent } from 'react'
import {
  ConnectionRequestError, createAIModel, deleteAIModel, listAIModelCatalog, listAIModels,
  discoverAIModels, getAIConnectionDiagnostics, patchAIModel, probeAIModel,
  type AIConnection, type AIConnectionDiagnostics, type AIModel, type AIModelCatalogEntry,
  type AIModelProbeReceipt,
} from '@/services/aiConnectionsApi'

const stateLabel = { supported: '已验证支持', unsupported: '已验证不支持', unknown: '未知 / 待验证' }
type ProbeFeedback = { tone: 'success' | 'warning'; message: string }

function probeResultMessage(receipt: AIModelProbeReceipt): ProbeFeedback {
  const capability = receipt.probe_kind === 'text' ? '文本' : '工具调用'
  if (receipt.status === 'succeeded' && receipt.capability === 'supported' && !receipt.stale) {
    return { tone: 'success', message: `${capability}能力测试通过，已验证支持。` }
  }
  if (receipt.status === 'unsupported' || receipt.capability === 'unsupported') {
    return { tone: 'warning', message: `${capability}能力测试完成，已验证不支持。` }
  }
  const reason = {
    result_unknown: '本地 AI 网关或网络未返回可验证结果。',
    incomplete_or_invalid: '模型返回了不完整或无法验证的响应。',
    tool_call_not_observed: '模型未按要求调用测试工具。',
    gateway_unavailable: '本地 AI 网关未启动或配置不可用。',
    gateway_rejected: '本地 AI 网关拒绝了请求。',
    authorization_changed: '授权或模型配置在测试期间发生变化，结果已丢弃。',
  }[receipt.safe_error_code]
  if (receipt.stale || receipt.status === 'stale') {
    return { tone: 'warning', message: '测试结果未确认：授权或模型配置已变化，旧结果未写入。不会自动重试。' }
  }
  return {
    tone: 'warning',
    message: `测试结果未确认：${reason ?? '未获得可验证的能力结论。'}不会自动重试。`,
  }
}

function safeError(error: unknown) {
  return error instanceof ConnectionRequestError ? error.message : '操作结果未知。请重新读取模型与探针状态。'
}

/** Personal models only: no automatic model requests on render, save or reload. */
export default function AIModelsManager({ connection, viewer, onModelsChanged }: { connection: AIConnection; viewer: number; onModelsChanged?: () => void }) {
  const [models, setModels] = useState<AIModel[] | null>(null)
  const [catalog, setCatalog] = useState<AIModelCatalogEntry[]>([])
  const [catalogNotice, setCatalogNotice] = useState('')
  const [diagnostics, setDiagnostics] = useState<AIConnectionDiagnostics | null>(null)
  const [loading, setLoading] = useState(true)
  const [revision, setRevision] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [probeFeedback, setProbeFeedback] = useState<ProbeFeedback | null>(null)
  const [selected, setSelected] = useState('')
  const [manualId, setManualId] = useState('')
  const [edit, setEdit] = useState<{ model: AIModel; field: 'model_id' | 'display_name'; value: string } | null>(null)
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)
  const [billingConsent, setBillingConsent] = useState(false)
  const alive = useRef<AbortController | null>(null)
  const writing = useRef(false)

  useEffect(() => {
    const controller = new AbortController()
    alive.current = controller
    void Promise.allSettled([listAIModels(connection, controller.signal), listAIModelCatalog(connection, controller.signal)])
      .then(([rows, known]) => {
        if (controller.signal.aborted) return
        if (rows.status === 'rejected') throw rows.reason
        setModels(rows.value)
        setCatalog(known.status === 'fulfilled' ? known.value.models : [])
        setCatalogNotice(known.status === 'fulfilled' ? '' : '预置目录暂不可用，仍可手动填写模型 ID。')
        if (known.status === 'fulfilled') setSelected(previous => previous || known.value.models[0]?.model_id || '')
      })
      .catch(reason => {
        if (controller.signal.aborted) return
        setModels(null)
        setError(safeError(reason))
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => { controller.abort(); alive.current = null }
  }, [connection, viewer, revision])

  const reload = () => {
    if (writing.current || loading) return
    setLoading(true); setError(''); setNotice(''); setProbeFeedback(null); setRevision(value => value + 1)
  }
  const perform = async <T,>(action: (signal: AbortSignal) => Promise<T>, feedback: string | ((result: T) => ProbeFeedback)) => {
    const controller = alive.current
    if (writing.current || !controller || controller.signal.aborted || !models) return
    writing.current = true
    setBusy(true); setError(''); setNotice(''); setProbeFeedback(null)
    try {
      const result = await action(controller.signal)
      if (controller.signal.aborted) return
      const updated = await listAIModels(connection, controller.signal)
      if (controller.signal.aborted) return
      setModels(updated)
      onModelsChanged?.()
      if (typeof feedback === 'function') setProbeFeedback(feedback(result))
      else setNotice(feedback)
      setEdit(null); setConfirmDelete(null); setBillingConsent(false)
    } catch (reason) {
      if (!controller.signal.aborted) {
        // An ambiguous write/paid probe must be reconciled by GET, not blindly resent.
        setModels(null); setError(safeError(reason)); setBillingConsent(false)
      }
    } finally {
      writing.current = false
      if (!controller.signal.aborted) setBusy(false)
    }
  }
  const add = (event: FormEvent) => {
    event.preventDefault()
    const requested = (manualId.trim() || selected).trim()
    if (!requested) return
    void perform(signal => createAIModel(connection, requested, viewer, signal), '模型配置已保存；保存不等于能力验证。')
    setManualId('')
  }
  const saveEdit = (event: FormEvent) => {
    event.preventDefault()
    if (!edit?.value.trim()) return
    const { model, field, value } = edit
    void perform(signal => patchAIModel(connection, model, { [field]: value.trim() }, viewer, signal),
      '模型已更新；旧能力验证失效。')
  }
  const probe = (model: AIModel, kind: 'text' | 'tools') => {
    if (!billingConsent || !connection.is_enabled || !model.has_trusted_route) return
    const requestId = crypto.randomUUID()
    void perform(signal => probeAIModel(connection, model, kind, requestId, viewer, signal),
      probeResultMessage)
  }
  const inspect = async (kind: 'discover' | 'diagnostics') => {
    const controller = alive.current
    if (writing.current || !controller || controller.signal.aborted || !models) return
    writing.current = true; setBusy(true); setError(''); setNotice(''); setProbeFeedback(null)
    try {
      if (kind === 'diagnostics') {
        const result = await getAIConnectionDiagnostics(connection, controller.signal)
        if (!controller.signal.aborted) setDiagnostics(result)
      } else {
        const result = await discoverAIModels(connection, viewer, controller.signal)
        if (controller.signal.aborted) return
        setCatalog(current => [...new Map([...current, ...result.models.map(id => ({ model_id: id,
          display_name: id, catalog_version: 'discovered', context_window_tokens: null,
          text: 'unknown' as const, tools: 'unknown' as const }))].map(item => [item.model_id, item])).values()])
        setCatalogNotice(`发现 ${result.models.length} 个模型${result.truncated ? '（目录已截断）' : ''}；未验证能力，未添加配置。`)
      }
    } catch (reason) {
      if (!controller.signal.aborted) setError(safeError(reason) + ' 可继续手动填写模型 ID。')
    } finally {
      writing.current = false
      if (!controller.signal.aborted) setBusy(false)
    }
  }
  return <div className="ai-models-manager min-w-0" aria-label={`${connection.display_name}的模型配置`}>
    <h3 className="text-sm font-semibold">模型配置</h3>
    <p className="workspace-caption">添加服务商提供的模型，验证后即可设为默认。</p>
    {error && <p role="alert" className="workspace-error">{error}</p>}
    {notice && <p role="status" className="workspace-notice">{notice}</p>}
    {probeFeedback && <p role="status" className={probeFeedback.tone === 'success'
      ? 'workspace-notice'
      : 'rounded-lg border border-amber-500/25 bg-amber-500/10 px-3 py-2 text-sm text-amber-900 dark:text-amber-200'}>{probeFeedback.message}</p>}
    {catalogNotice && <p role="status" className="workspace-caption">{catalogNotice}</p>}
    <div className="workspace-actions flex-wrap"><Button type="button" variant="outline" size="sm" disabled={busy || loading} onClick={reload}>重新读取模型</Button>
      {connection.model_discovery_supported && <Button type="button" variant="outline" size="sm"
        disabled={busy || loading || !models || !connection.is_enabled} onClick={() => { void inspect('discover') }}>发现服务端模型</Button>}
      <Button type="button" variant="outline" size="sm" disabled={busy || loading || !models}
        onClick={() => { void inspect('diagnostics') }}>检查配置（不调用模型）</Button></div>
    {diagnostics && <div className="workspace-soft-panel" role="status">
      <p>连接：{diagnostics.connection_status === 'active' ? '授权有效' : '授权不可用'} · 端点：{diagnostics.endpoint_status === 'approved' ? '管理员已批准' : '不可用'}</p>
      <p>{diagnostics.data_destination_label}</p><p>此检查未发送推理请求；模型能力以独立测试结果为准。</p>
    </div>}
    {loading && <p role="status">正在读取模型…</p>}
    {!loading && !models && <p role="status">模型状态未知。重新读取成功前无法再次提交操作或收费探针。</p>}
    {models && <>
      <details className="ai-model-add mt-4 rounded-lg border border-dashed bg-secondary/15" open={models.length === 0}>
        <summary className="flex cursor-pointer list-none items-center gap-2 px-4 py-3 text-sm font-medium"><Plus className="size-4" />添加模型<span className="ml-auto text-xs font-normal text-muted-foreground">搜索目录或填写 ID</span></summary>
        <form onSubmit={add} className="grid min-w-0 gap-3 border-t p-4">
          <label className="grid gap-2 text-xs font-medium">预置模型（可选）
            <ModelCombobox label="预置模型（可选）" value={selected} disabled={busy || catalog.length === 0} onChange={setSelected}
              options={catalog.map(item => ({ value: item.model_id, label: item.display_name, description: item.display_name !== item.model_id ? item.model_id : undefined }))} />
          </label>
          <label className="grid gap-2 text-xs font-medium">或手动填写模型 ID<Input value={manualId} disabled={busy} maxLength={160} placeholder="例如：minimax-m3.1-flash" onChange={event => setManualId(event.target.value)} /></label>
          <Button type="submit" variant="outline" size="sm" className="justify-self-start" disabled={busy || models.length >= 30 || !(manualId.trim() || selected)}><Plus />添加模型（不调用服务商）</Button>
        </form>
      </details>
      {models.length === 0 && <p>尚未添加模型。</p>}
      {models.map(model => <section key={model.id} aria-label={`模型 ${model.display_name}`} className="my-4 rounded-xl border bg-secondary/10 p-4">
        <div className="mb-2 flex items-center gap-2"><Box className="size-4 text-primary" /><strong className="text-sm">{model.display_name}</strong></div><p className="workspace-caption">{model.model_id} · {model.has_trusted_route ? '可主动测试' : '暂不可测试'}</p>
        {!model.has_trusted_route && <p className="workspace-caption">请检查模型 ID；GLM、百炼和 Kimi 的旧默认连接需新建为对应地域连接后再测试。</p>}
        <div className="my-3 flex flex-wrap gap-2"><Badge variant="outline" className={model.capabilities.text === 'supported' ? 'border-primary/20 bg-primary/5 text-primary' : 'text-muted-foreground'}>文本：{stateLabel[model.capabilities.text]}</Badge>
          <Badge variant="outline" className={model.capabilities.tools === 'supported' ? 'border-primary/20 bg-primary/5 text-primary' : 'text-muted-foreground'}>工具调用：{stateLabel[model.capabilities.tools]}</Badge></div>
        <p className="workspace-caption">输出方式：{model.delivery_mode === 'streaming' && model.stream_verified === true ? '已验证终态的逐步输出'
          : model.delivery_mode === 'buffered' ? '完整生成后显示（buffered）' : '尚未核实'}；费用未知。</p>
        <p className="workspace-caption">上下文上限：未核实 · 配置版本 {model.config_revision}</p>
        <div className="workspace-actions flex-wrap">
          <Button type="button" variant="outline" size="sm" disabled={busy} onClick={() => setEdit({ model, field: 'display_name', value: model.display_name })}>修改模型名称</Button>
          <Button type="button" variant="outline" size="sm" disabled={busy} onClick={() => setEdit({ model, field: 'model_id', value: model.model_id })}>修改模型 ID</Button>
          <Button type="button" variant="outline" size="sm" disabled={busy || !billingConsent || !connection.is_enabled || !model.has_trusted_route}
            onClick={() => probe(model, 'text')}>测试文本能力</Button>
          <Button type="button" variant="outline" size="sm" disabled={busy || !billingConsent || !connection.is_enabled || !model.has_trusted_route}
            onClick={() => probe(model, 'tools')}>测试工具能力</Button>
          {confirmDelete === model.id
            ? <><Button type="button" variant="ghost" size="sm" className="text-destructive hover:text-destructive" disabled={busy} onClick={() => void perform(signal => deleteAIModel(connection, model, viewer, signal), '模型已删除。')}>确认删除模型</Button>
                <Button type="button" variant="outline" size="sm" disabled={busy} onClick={() => setConfirmDelete(null)}>取消删除</Button></>
            : <Button type="button" variant="ghost" size="sm" className="text-destructive hover:text-destructive" disabled={busy} onClick={() => setConfirmDelete(model.id)}>删除模型</Button>}
        </div>
        {edit?.model.id === model.id && <form className="grid gap-2 py-2" onSubmit={saveEdit}>
          <label>{edit.field === 'model_id' ? '模型 ID' : '模型名称'}
            <Input value={edit.value} maxLength={edit.field === 'model_id' ? 160 : 64} required disabled={busy}
              onChange={event => setEdit({ ...edit, value: event.target.value })} /></label>
          <div className="workspace-actions"><Button type="submit" size="sm" disabled={busy || !edit.value.trim()}>保存模型修改</Button>
            <Button type="button" variant="outline" size="sm" onClick={() => setEdit(null)}>取消修改</Button></div>
        </form>}
      </section>)}
      <label className="mt-3 flex items-start gap-2 rounded-lg bg-secondary/40 p-3 text-xs leading-relaxed text-muted-foreground">
        <input type="checkbox" checked={billingConsent} disabled={busy}
          onChange={event => setBillingConsent(event.target.checked)} />
        <span>我确认主动测试可能产生服务商费用。仅发送固定短提示，不自动重试。</span>
      </label>
    </>}
  </div>
}
