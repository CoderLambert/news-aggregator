import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { ModelCombobox } from '@/components/ui/model-combobox'
import { ChevronDown, RefreshCw, SlidersHorizontal, Sparkles } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import {
  ConnectionRequestError, listAIModels, listAITaskPreferences, saveAITaskPreferences,
  hasAIConnectionAuthentication,
  type AIConnection, type AIModel, type AITaskKind, type AITaskPreferences,
  type AITaskPreferenceInput,
} from '@/services/aiConnectionsApi'

type Draft = Record<AITaskKind, string | null>
const OPTIONS: Array<{ kind: AITaskKind; label: string; description: string }> = [
  { kind: 'default', label: '全局默认', description: '其他用途留空时跟随默认；不自动借用站点模型。' },
  { kind: 'article_qa', label: '新闻问答', description: '选择文章阅读页个人模型问答使用的模型。' },
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
  viewer, connections, refreshToken = 0,
}: { viewer: number; connections: AIConnection[]; refreshToken?: number }) {
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
  }, [viewer, connections, version, refreshToken])

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
    return Boolean(model && connection?.is_enabled && hasAIConnectionAuthentication(connection) &&
      model.has_trusted_route && model.capabilities.text === 'supported' &&
      (!['article_qa', 'full_translation'].includes(kind) || model.article_chat_supported === true) &&
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
      setNotice('用途偏好已保存。问答、翻译和研究按已选模型执行；已有任务保持原模型，不自动切换。')
    } catch (reason) {
      if (controller.signal.aborted) return
      setReconcileRequired(true)
      setError(safeMessage(reason) + ' 请先重新读取，不自动重发保存。')
    } finally {
      writing.current = false
      if (!controller.signal.aborted) setBusy(false)
    }
  }

  const renderField = ({ kind, label, description }: typeof OPTIONS[number]) => {
    if (!remote || !choices || !models) return null
    const id = choices[kind]
    const savedEntry = remote.preferences.find(entry => entry.task_kind === kind)
    const available = models.filter(model => validModel(model.id, kind))
    return <fieldset key={kind} className={kind === 'default' ? 'min-w-0 rounded-xl border border-primary/15 bg-primary/5 p-5' : 'min-w-0 rounded-xl border p-4'}>
      <label className="mb-2 flex items-center gap-2 text-sm font-medium">{kind === 'default' && <Sparkles className="size-4 text-primary" />}{label}模型</label>
      <ModelCombobox label={label + '模型'} value={id ?? ''} disabled={busy || reconcileRequired}
        onChange={value => change(kind, value)} options={[
          { value: '', label: kind === 'default' ? '不设置默认模型' : '跟随个人默认模型' },
          ...(id && !validModel(id, kind) ? [{ value: id, label: '原模型已失效，需重新选择', disabled: true }] : []),
          ...available.map(model => ({ value: model.id, label: model.display_name,
            description: (connectionsById.get(model.connection_id)?.display_name ?? '已保存连接') + ' · ' + model.model_id })),
        ]} />
      <p className="mt-2 text-xs leading-relaxed text-muted-foreground">{description}</p>
      {id && id === savedEntry?.model_config_id && savedEntry.selection_state === 'needs_reselection' && <p role="alert" className="mt-2 text-xs text-destructive">已选模型停用或删除，必须重新选择。</p>}
      {id && id === savedEntry?.model_config_id && savedEntry.selection_state === 'needs_verification' && <p role="alert" className="mt-2 text-xs text-destructive">已选模型的必要能力尚未验证。</p>}
      {kind === 'deep_research' && !id && choices.default && !validModel(choices.default, kind) && <p className="mt-2 text-xs text-amber-700">当前默认模型未通过工具能力验证，深度研究仍不可用。</p>}
    </fieldset>
  }
  const overrides = choices ? OPTIONS.filter(option => option.kind !== 'default' && choices[option.kind] !== null).length : 0
  return <section className="mt-7 min-w-0" aria-label="个人模型用途偏好">
    <Card className="gap-4 p-5 shadow-none">
      <div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="flex items-center gap-2 text-base font-semibold"><SlidersHorizontal className="size-4 text-primary" />模型用途偏好</h2>
        <p className="mt-1 text-xs text-muted-foreground">设置一次，阅读时直接使用。仅显示已验证且可用的模型。</p></div>
        <Button variant="ghost" size="sm" disabled={busy || loading} onClick={reload}><RefreshCw />重新读取用途偏好</Button></div>
      {loading && <p role="status">正在读取模型用途…</p>}
      {error && <p role="alert" className="workspace-error">{error}</p>}
      {notice && <p role="status" className="text-sm text-primary">{notice}</p>}
      {!loading && !remote && <p role="status">用途偏好状态未知，确认当前账号的数据前不能保存。</p>}
      {remote && choices && models && <>
        {renderField(OPTIONS[0])}
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg bg-secondary/30 p-3">
          <p className="text-xs text-muted-foreground">{overrides ? `${overrides} 个用途已单独指定模型，可统一跟随默认。` : '问答、翻译、研究和问题推荐均跟随默认配置。'}</p>
          <Button variant="outline" size="sm" disabled={busy || reconcileRequired || overrides === 0} onClick={() => {
            const next: Draft = { default: choices.default, article_qa: null, full_translation: null, deep_research: null, question_suggestions: null }
            setDraft(saved && same(next, saved) ? null : next); setNotice('请保存用途偏好以应用变更。')
          }}>所有用途跟随默认</Button>
        </div>
        <details className="ai-task-overrides rounded-lg border">
          <summary className="flex cursor-pointer list-none items-center justify-between p-4 text-sm font-medium">按用途单独配置<Badge variant="secondary">{overrides ? `${overrides} 项单独配置` : '可选'}<ChevronDown className="ml-1 size-3" /></Badge></summary>
          <div className="grid gap-3 border-t p-4 sm:grid-cols-2">{OPTIONS.slice(1).map(renderField)}</div>
        </details>
      </>}
      {remote && choices && <footer className="flex flex-wrap items-center justify-between gap-3 border-t pt-4">
        <p role="status" className={`text-xs ${invalid ? 'text-destructive' : 'text-muted-foreground'}`}>{invalid ? '存在不符合当前能力和连接状态的模型。' : dirty ? '存在未保存的用途变更。' : '当前没有未保存的变更。'}</p>
        <div className="flex gap-2"><Button type="button" variant="ghost" size="sm" disabled={!dirty || busy || reconcileRequired}
          onClick={() => { setDraft(null); setNotice('已撤销未保存的修改。') }}>撤销修改</Button>
        <Button type="button" size="sm" disabled={!dirty || invalid || busy || loading || reconcileRequired} onClick={() => { void save() }}>{busy ? '正在保存…' : '保存用途偏好'}</Button></div>
      </footer>}
    </Card>
  </section>
}
