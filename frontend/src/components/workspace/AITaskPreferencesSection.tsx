import { useEffect, useRef, useState } from 'react'
import {
  ConnectionRequestError, listAIModels, listAITaskPreferences, saveAITaskPreferences,
  type AIConnection, type AIModel, type AITaskKind, type AITaskPreferences,
  type AITaskPreferenceInput,
} from '@/services/aiConnectionsApi'

type Draft = Record<AITaskKind, string | null>
const OPTIONS: Array<{ kind: AITaskKind; label: string; description: string }> = [
  { kind: 'default', label: '全局默认', description: '其他用途留空时跟随默认；不自动借用站点模型。' },
  { kind: 'article_qa', label: '新闻问答', description: '下一阶段接入新闻问答；目前仅保存用途。' },
  { kind: 'full_translation', label: '全文翻译', description: '独立选择用于私人全文翻译的模型。' },
  { kind: 'deep_research', label: '深度研究', description: '需要文本和工具调用能力均已验证。' },
  { kind: 'question_suggestions', label: '问题推荐', description: '单独指定或继承个人默认模型。' },
]
function selections(prefs: AITaskPreferences): Draft {
  const result: Draft = { default: null, article_qa: null, full_translation: null,
    deep_research: null, question_suggestions: null }
  for (const entry of prefs.preferences) result[entry.task_kind] = entry.model_config_id
  return result
}
function same(a: Draft, b: Draft) {
  return OPTIONS.every(option => a[option.kind] === b[option.kind])
}
function safeMessage(reason: unknown) {
  return reason instanceof ConnectionRequestError ? reason.message : '状态未知，请重新读取用途偏好。'
}

/** Never dispatches a model request. Reconciliation is GET-only after uncertain saves. */
export default function AITaskPreferencesSection({
  viewer, connections,
}: { viewer: number; connections: AIConnection[] }) {
  const [remote, setRemote] = useState<AITaskPreferences | null>(null)
  const [models, setModels] = useState<AIModel[] | null>(null)
  const [draft, setDraft] = useState<Draft | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [reconcileRequired, setReconcileRequired] = useState(false)
  const [version, setVersion] = useState(0)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const alive = useRef<AbortController | null>(null)
  const writing = useRef(false)

  useEffect(() => {
    const controller = new AbortController()
    alive.current = controller
    void Promise.all([
      listAITaskPreferences(controller.signal),
      Promise.all(connections.map(connection => listAIModels(connection, controller.signal))),
    ]).then(([preferences, loaded]) => {
      if (controller.signal.aborted) return
      setRemote(preferences)
      setModels(loaded.flat())
      setReconcileRequired(false)
    }).catch(reason => {
      if (controller.signal.aborted) return
      setRemote(null)
      setModels(null)
      setError(safeMessage(reason))
    }).finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => { controller.abort(); alive.current = null }
  }, [viewer, connections, version])

  const reload = () => {
    if (loading || writing.current) return
    setLoading(true); setError(''); setNotice(''); setVersion(value => value + 1)
  }
  const saved = remote ? selections(remote) : null
  const choices = draft ?? saved
  const dirty = Boolean(draft && saved && !same(draft, saved))
  const modelsById = new Map((models ?? []).map(model => [model.id, model]))
  const connectionsById = new Map(connections.map(row => [row.id, row]))
  const validModel = (id: string, kind: AITaskKind) => {
    const model = modelsById.get(id)
    const connection = model && connectionsById.get(model.connection_id)
    return Boolean(model && connection?.is_enabled && connection.key_saved &&
      model.has_trusted_route && model.capabilities.text === 'supported' &&
      (kind !== 'deep_research' || model.capabilities.tools === 'supported'))
  }
  const invalid = Boolean(choices && OPTIONS.some(({ kind }) => {
    const id = choices[kind]
    return id !== null && !validModel(id, kind)
  }))
  const change = (kind: AITaskKind, selected: string) => {
    if (!choices || !saved) return
    const next: Draft = { ...choices, [kind]: selected || null }
    setDraft(same(next, saved) ? null : next)
    setNotice('')
  }
  const save = async () => {
    if (!remote || !choices || !dirty || invalid || busy || reconcileRequired || writing.current) return
    const controller = alive.current
    if (!controller || controller.signal.aborted) return
    writing.current = true
    setBusy(true); setError(''); setNotice('')
    const payload: AITaskPreferenceInput[] = OPTIONS.map(({ kind }) => ({
      task_kind: kind, model_config_id: choices[kind],
    }))
    try {
      const updated = await saveAITaskPreferences(remote.revision, payload, viewer, controller.signal)
      if (controller.signal.aborted) return
      setRemote(updated)
      setDraft(null)
      setNotice('用途偏好已保存。既有任务快照不重新绑定；业务调用仍需独立接入和授权。')
    } catch (reason) {
      if (controller.signal.aborted) return
      setReconcileRequired(true)
      setError(safeMessage(reason) + ' 请先重新读取，不自动重发保存。')
    } finally {
      writing.current = false
      if (!controller.signal.aborted) setBusy(false)
    }
  }

  return <section className="workspace-panel mt-5 min-w-0" aria-label="个人模型用途偏好">
    <h2>模型用途偏好</h2>
    <p className="workspace-caption">五种用途需要明确保存。只能选择已验证的个人模型；未通过独立工具能力探针的模型不能直接指定给深度研究。此页不会发送模型请求。</p>
    <button type="button" className="workspace-button secondary" disabled={busy || loading} onClick={reload}>重新读取用途偏好</button>
    {loading && <p role="status">正在读取模型用途…</p>}
    {error && <p role="alert" className="workspace-error">{error}</p>}
    {notice && <p role="status">{notice}</p>}
    {!loading && !remote && <p role="status">用途偏好状态未知，确认当前账号的数据前不能保存。</p>}
    {remote && choices && models && <div className="grid min-w-0 gap-3 py-3 sm:grid-cols-2">
      {OPTIONS.map(({ kind, label, description }) => {
        const id = choices[kind]
        const savedEntry = remote.preferences.find(entry => entry.task_kind === kind)
        const available = models.filter(model => validModel(model.id, kind))
        return <fieldset key={kind} className="min-w-0 border p-3">
          <legend>{label}</legend>
          <label className="grid gap-1">{label}模型
            <select aria-label={label + '模型'} value={id ?? ''} disabled={busy || reconcileRequired}
              onChange={event => change(kind, event.target.value)}>
              <option value="">{kind === 'default' ? '不设置默认模型' : '跟随个人默认模型'}</option>
              {id && !validModel(id, kind) && <option value={id} disabled>原模型已失效，需重新选择</option>}
              {available.map(model => <option key={model.id} value={model.id}>
                {(connectionsById.get(model.connection_id)?.display_name ?? '已保存连接') + ' · ' + model.display_name}
              </option>)}
            </select>
          </label>
          <p className="workspace-caption">{description}</p>
          {savedEntry?.selection_state === 'needs_reselection' && <p role="alert">已选模型停用或删除，必须重新选择。</p>}
          {savedEntry?.selection_state === 'needs_verification' && <p role="alert">已选模型的必要能力尚未验证。</p>}
          {kind === 'deep_research' && !id && choices.default &&
            !validModel(choices.default, kind) && <p className="workspace-caption">当前默认模型未通过工具能力验证，深度研究仍不可用。</p>}
        </fieldset>
      })}
    </div>}
    {remote && choices && <footer className="workspace-actions flex-wrap">
      <p role="status">{invalid ? '存在不符合当前能力和连接状态的模型。' :
        dirty ? '存在未保存的用途变更。' : '当前没有未保存的变更。'}</p>
      <button type="button" className="workspace-button secondary"
        disabled={!dirty || busy || reconcileRequired}
        onClick={() => { setDraft(null); setNotice('已撤销未保存的修改。') }}>撤销修改</button>
      <button type="button" className="workspace-button"
        disabled={!dirty || invalid || busy || loading || reconcileRequired}
        onClick={() => { void save() }}>{busy ? '正在保存…' : '保存用途偏好'}</button>
    </footer>}
  </section>
}
