import { useEffect, useRef, useState, type FormEvent } from 'react'
import {
  ConnectionRequestError, createAIModel, deleteAIModel, listAIModelCatalog, listAIModels,
  patchAIModel, probeAIModel, type AIConnection, type AIModel, type AIModelCatalogEntry,
} from '@/services/aiConnectionsApi'

const stateLabel = { supported: '已验证支持', unsupported: '已验证不支持', unknown: '未知 / 待验证' }
function safeError(error: unknown) {
  return error instanceof ConnectionRequestError ? error.message : '操作结果未知。请重新读取模型与探针状态。'
}

/** Personal models only: no automatic model requests on render, save or reload. */
export default function AIModelsManager({ connection, viewer }: { connection: AIConnection; viewer: number }) {
  const [models, setModels] = useState<AIModel[] | null>(null)
  const [catalog, setCatalog] = useState<AIModelCatalogEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [revision, setRevision] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
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
    setLoading(true)
    void Promise.all([listAIModels(connection, controller.signal), listAIModelCatalog(connection, controller.signal)])
      .then(([rows, known]) => {
        if (controller.signal.aborted) return
        setModels(rows)
        setCatalog(known.models)
        setSelected(previous => previous || known.models[0]?.model_id || '')
      })
      .catch(reason => {
        if (controller.signal.aborted) return
        setModels(null)
        setError(safeError(reason))
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => { controller.abort(); alive.current = null }
  }, [connection.id, viewer, revision])

  const reload = () => {
    if (writing.current || loading) return
    setError(''); setNotice(''); setRevision(value => value + 1)
  }
  const perform = async (action: (signal: AbortSignal) => Promise<unknown>, note: string) => {
    const controller = alive.current
    if (writing.current || !controller || controller.signal.aborted || !models) return
    writing.current = true
    setBusy(true); setError(''); setNotice('')
    try {
      await action(controller.signal)
      if (controller.signal.aborted) return
      const updated = await listAIModels(connection, controller.signal)
      if (controller.signal.aborted) return
      setModels(updated)
      setNotice(note)
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
      '已记录本次显式探针结果。请查看两种能力的独立状态；未知结果不会自动重试。')
  }
  return <div className="mt-4 min-w-0 border-t pt-3" aria-label={`${connection.display_name}的模型配置`}>
    <h3>模型配置</h3>
    <p className="workspace-caption">仅经过批准的模型路由可以测试。能力未验证及未设置用途时，个人 AI 业务调用仍不可用。</p>
    {error && <p role="alert" className="workspace-error">{error}</p>}
    {notice && <p role="status" className="workspace-notice">{notice}</p>}
    <button type="button" className="workspace-button secondary" disabled={busy || loading} onClick={reload}>重新读取模型</button>
    {loading && <p role="status">正在读取模型…</p>}
    {!loading && !models && <p role="status">模型状态未知。重新读取成功前无法再次提交操作或收费探针。</p>}
    {models && <>
      <form onSubmit={add} className="grid min-w-0 gap-2 py-3">
        <label>已批准模型<select value={selected} disabled={busy} onChange={event => setSelected(event.target.value)}>
          {catalog.length ? catalog.map(item => <option key={item.model_id} value={item.model_id}>{item.display_name} · {item.model_id}</option>)
            : <option value="">当前连接无批准模型</option>}
        </select></label>
        <label>或手动填写模型 ID<input value={manualId} disabled={busy} maxLength={160} placeholder="填写后仍需路由审核" onChange={event => setManualId(event.target.value)} /></label>
        <button type="submit" className="workspace-button secondary" disabled={busy || models.length >= 30 || !(manualId.trim() || selected)}>添加模型（不调用服务商）</button>
      </form>
      {models.length === 0 && <p>尚未添加模型。</p>}
      {models.map(model => <section key={model.id} aria-label={`模型 ${model.display_name}`} className="my-3 border-t pt-3">
        <strong>{model.display_name}</strong><p className="workspace-caption">{model.model_id} · {model.has_trusted_route ? '受信路由' : '未批准路由'}</p>
        <p>文本：{stateLabel[model.capabilities.text]} · 工具调用：{stateLabel[model.capabilities.tools]}</p>
        <p className="workspace-caption">上下文上限：未核实 · 配置版本 {model.config_revision}</p>
        <div className="workspace-actions flex-wrap">
          <button type="button" className="workspace-button secondary" disabled={busy} onClick={() => setEdit({ model, field: 'display_name', value: model.display_name })}>修改模型名称</button>
          <button type="button" className="workspace-button secondary" disabled={busy} onClick={() => setEdit({ model, field: 'model_id', value: model.model_id })}>修改模型 ID</button>
          <button type="button" className="workspace-button secondary" disabled={busy || !billingConsent || !connection.is_enabled || !model.has_trusted_route}
            onClick={() => probe(model, 'text')}>测试文本能力</button>
          <button type="button" className="workspace-button secondary" disabled={busy || !billingConsent || !connection.is_enabled || !model.has_trusted_route}
            onClick={() => probe(model, 'tools')}>测试工具能力</button>
          {confirmDelete === model.id
            ? <><button type="button" className="workspace-button danger" disabled={busy} onClick={() => void perform(signal => deleteAIModel(connection, model, viewer, signal), '模型已删除。')}>确认删除模型</button>
                <button type="button" className="workspace-button secondary" disabled={busy} onClick={() => setConfirmDelete(null)}>取消删除</button></>
            : <button type="button" className="workspace-button danger" disabled={busy} onClick={() => setConfirmDelete(model.id)}>删除模型</button>}
        </div>
        {edit?.model.id === model.id && <form className="grid gap-2 py-2" onSubmit={saveEdit}>
          <label>{edit.field === 'model_id' ? '模型 ID' : '模型名称'}
            <input value={edit.value} maxLength={edit.field === 'model_id' ? 160 : 64} required disabled={busy}
              onChange={event => setEdit({ ...edit, value: event.target.value })} /></label>
          <div className="workspace-actions"><button type="submit" className="workspace-button" disabled={busy || !edit.value.trim()}>保存模型修改</button>
            <button type="button" className="workspace-button secondary" onClick={() => setEdit(null)}>取消修改</button></div>
        </form>}
      </section>)}
      <label className="flex items-start gap-2">
        <input type="checkbox" checked={billingConsent} disabled={busy}
          onChange={event => setBillingConsent(event.target.checked)} />
        <span>我确认主动测试可能产生服务商费用。不会自动测试、重试或切换模型；测试仅使用固定短提示。</span>
      </label>
    </>}
  </div>
}
