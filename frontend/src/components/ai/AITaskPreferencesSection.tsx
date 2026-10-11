import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Button } from '@/components/ui/button'
import type { AIConnection, AIModelConfig, AITaskKind, AITaskPreference, SaveAITaskPreference } from '@/services/api'
import { fetchAITaskPreferences, saveAITaskPreferences } from '@/services/api'

const PREFERENCES_KEY = 'aiTaskPreferences'
const NEEDS_RESELECTION = '__needs_reselection__'

const TASK_OPTIONS: Array<{ kind: AITaskKind; title: string; label: string; description: string }> = [
  { kind: 'default', title: '全局默认', label: '默认模型', description: '其它用途选择“跟随默认”时使用。' },
  { kind: 'article_qa', title: '新闻问答', label: '使用模型', description: '可单独指定；留空时跟随默认模型。' },
  { kind: 'full_translation', title: '全文翻译', label: '使用模型', description: '可单独指定；留空时跟随默认模型。' },
  { kind: 'deep_research', title: '深度研究', label: '使用模型', description: '可单独指定；留空时跟随默认模型。' },
  { kind: 'question_suggestions', title: '问题推荐', label: '使用模型', description: '可单独指定；留空时跟随默认模型。' },
]

type DraftValue = string | null | typeof NEEDS_RESELECTION
type PreferencesDraft = Record<AITaskKind, DraftValue>

function preferenceMap(preferences: AITaskPreference[] | undefined): PreferencesDraft {
  const result: PreferencesDraft = {
    default: null,
    article_qa: null,
    full_translation: null,
    deep_research: null,
    question_suggestions: null,
  }
  for (const preference of preferences ?? []) {
    result[preference.task_kind] = preference.selection_state === 'needs_reselection' && preference.model_config_id === null
      ? NEEDS_RESELECTION
      : preference.model_config_id
  }
  return result
}

function sameDraft(left: PreferencesDraft, right: PreferencesDraft): boolean {
  return TASK_OPTIONS.every(({ kind }) => left[kind] === right[kind])
}

function toSavePayload(draft: PreferencesDraft): SaveAITaskPreference[] | null {
  if (TASK_OPTIONS.some(({ kind }) => draft[kind] === NEEDS_RESELECTION)) return null
  return TASK_OPTIONS.map(({ kind }) => ({ task_kind: kind, model_config_id: draft[kind] }))
}

function modelLabel(model: AIModelConfig, connectionsById: Map<string, AIConnection>): string {
  const connection = connectionsById.get(model.connection_id)
  return `${connection?.display_name ?? '已保存连接'} · ${model.display_name}`
}

export default function AITaskPreferencesSection({
  userId,
  models,
  connections,
  dataLoading,
  dataError,
}: {
  userId: number
  models: AIModelConfig[]
  connections: AIConnection[]
  dataLoading: boolean
  dataError: boolean
}) {
  const queryClient = useQueryClient()
  const queryKey = [PREFERENCES_KEY, userId]
  const preferencesQuery = useQuery({
    queryKey,
    queryFn: ({ signal }) => fetchAITaskPreferences(signal),
    retry: false,
  })
  const savedDraft = preferenceMap(preferencesQuery.data)
  const [draft, setDraft] = useState<PreferencesDraft | null>(null)
  const [notice, setNotice] = useState('')
  const currentDraft = draft ?? savedDraft
  const isDirty = draft !== null && !sameDraft(draft, savedDraft)
  const activeConnectionIds = new Set(
    connections.filter((connection) => connection.is_enabled && connection.key_saved).map((connection) => connection.id),
  )
  const selectableModels = models.filter((model) => activeConnectionIds.has(model.connection_id))
  const connectionsById = new Map(connections.map((connection) => [connection.id, connection]))
  const preferenceByKind = new Map((preferencesQuery.data ?? []).map((preference) => [preference.task_kind, preference]))
  const hasStalePreference = (preferencesQuery.data ?? []).some((preference) => preference.selection_state === 'needs_reselection')
  const invalidSelection = TASK_OPTIONS.some(({ kind }) => {
    const selected = currentDraft[kind]
    return selected === NEEDS_RESELECTION || (typeof selected === 'string' && !selectableModels.some((model) => model.id === selected))
  })

  const saveMutation = useMutation({
    mutationFn: (preferences: SaveAITaskPreference[]) => saveAITaskPreferences(preferences),
    retry: false,
    onSuccess: (saved) => {
      queryClient.setQueryData(queryKey, saved)
      setDraft(null)
      setNotice('用途偏好已保存，只影响之后开始的任务；已开始的任务和历史结果保持不变。')
    },
    onError: () => setNotice('保存失败。未保存的选择仍留在本页，请检查连接状态后重试。'),
  })

  function changeSelection(taskKind: AITaskKind, value: string) {
    const nextValue: DraftValue = value === '' ? null : value
    const next = { ...currentDraft, [taskKind]: nextValue }
    setDraft(sameDraft(next, savedDraft) ? null : next)
    setNotice('')
  }

  function save() {
    const payload = toSavePayload(currentDraft)
    if (!payload || !isDirty || saveMutation.isPending || invalidSelection) return
    setNotice('')
    saveMutation.mutate(payload)
  }

  return (
    <section aria-labelledby="ai-task-preferences" className="rounded-2xl border border-border bg-card p-5 sm:p-6">
      <header>
        <p className="text-sm font-medium text-orange-600">模型偏好</p>
        <h2 id="ai-task-preferences" className="mt-1 text-xl font-semibold">为不同用途选择模型</h2>
        <p className="mt-2 text-sm leading-6 text-muted-foreground">添加连接或模型不会自动更改偏好。用途模型只会在明确保存后生效；未设置默认模型时，系统不会改用站点或 ChatGPT 订阅凭据。</p>
      </header>

      {preferencesQuery.isPending ? (
        <p className="mt-5 text-sm text-muted-foreground" role="status">正在读取用途偏好…</p>
      ) : preferencesQuery.isError ? (
        <p className="mt-5 text-sm text-destructive" role="alert">用途偏好暂不可用，请稍后重试。</p>
      ) : dataLoading ? (
        <p className="mt-5 text-sm text-muted-foreground" role="status">正在读取可用模型…</p>
      ) : dataError ? (
        <p className="mt-5 text-sm text-destructive" role="alert">模型或连接信息暂不可用，当前选择没有改变。</p>
      ) : selectableModels.length === 0 && !hasStalePreference ? (
        <div className="mt-5 rounded-xl bg-muted/40 p-4">
          <p className="text-sm font-medium">还没有可分配的模型</p>
          <p className="mt-1 text-sm text-muted-foreground">先添加服务商连接，再保存至少一个模型配置。这里不会自动选择站点或订阅模型。</p>
          <a href="#add-ai-connection" className="mt-3 inline-flex min-h-11 items-center rounded-md border border-border px-3 text-sm font-medium hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">添加服务商连接</a>
        </div>
      ) : (
        <>
          <div className="mt-5 grid min-w-0 gap-3 md:grid-cols-2">
            {TASK_OPTIONS.map(({ kind, title, label, description }) => {
              const value = currentDraft[kind]
              const savedPreference = preferenceByKind.get(kind)
              const savedModel = savedPreference?.model
              const needsReselection = savedPreference?.selection_state === 'needs_reselection' && !isDirty
              const defaultPreference = preferenceByKind.get('default')
              const inheritedDefaultUnavailable = kind !== 'default' && value === null &&
                defaultPreference?.selection_state !== 'available'
              return (
                <fieldset key={kind} className="min-w-0 rounded-xl border border-border p-4">
                  <legend className="px-1 text-sm font-semibold">{title}</legend>
                  <label className="mt-2 block space-y-2 text-sm font-medium">
                    <span>{label}</span>
                    <select
                      aria-label={`${title}：${label}`}
                      value={value ?? ''}
                      onChange={(event) => changeSelection(kind, event.target.value)}
                      disabled={saveMutation.isPending}
                      className="h-11 w-full min-w-0 rounded-md border border-input bg-background px-3 text-sm"
                    >
                      {kind === 'default' ? (
                        <option value="">{savedPreference?.selection_state === 'needs_reselection' ? '请选择有效默认模型' : '暂不设置默认模型'}</option>
                      ) : (
                        <option value="">{savedPreference?.selection_state === 'needs_reselection' && value === NEEDS_RESELECTION ? '请选择用途模型或跟随默认' : '跟随默认模型'}</option>
                      )}
                      {savedModel && !selectableModels.some((model) => model.id === savedModel.id) && (
                        <option value={savedModel.id} disabled>{savedModel.display_name}（连接不可用，需重选）</option>
                      )}
                      {value === NEEDS_RESELECTION && (
                        <option value={NEEDS_RESELECTION} disabled>原模型已删除，请重新选择</option>
                      )}
                      {selectableModels.map((model) => (
                        <option key={model.id} value={model.id}>{modelLabel(model, connectionsById)}</option>
                      ))}
                    </select>
                  </label>
                  <p className="mt-2 break-words text-xs leading-5 text-muted-foreground">{description}</p>
                  {needsReselection && (
                    <p className="mt-2 text-xs font-medium text-amber-700" role="alert">
                      {kind === 'default'
                        ? '默认模型已停用或删除。请选择有效默认模型。'
                        : '原模型已停用或删除。请明确选择可用模型，或对该用途选择跟随默认。'}
                    </p>
                  )}
                  {inheritedDefaultUnavailable && defaultPreference?.selection_state !== 'available' && (
                    <p className="mt-2 text-xs text-amber-700">当前默认模型尚未设置或需要重选；该用途暂时没有可解析的模型。</p>
                  )}
                </fieldset>
              )
            })}
          </div>

          {notice && <p className="mt-4 text-sm text-muted-foreground" role="status">{notice}</p>}
          <div className="mt-5 flex min-w-0 flex-wrap items-center justify-between gap-3 border-t border-border pt-4">
            <p className="min-w-0 flex-1 text-sm text-muted-foreground" role="status">
              {invalidSelection ? '有用途指向不可用模型，请重新选择后保存。' : isDirty ? '当前选择尚未保存。' : '已保存的偏好只应用于之后开始的任务。'}
            </p>
            <div className="flex flex-wrap gap-2">
              <Button type="button" variant="outline" className="min-h-11" disabled={!isDirty || saveMutation.isPending} onClick={() => { setDraft(null); setNotice('已撤销本页尚未保存的选择。') }}>撤销修改</Button>
              <Button type="button" className="min-h-11" disabled={!isDirty || invalidSelection || saveMutation.isPending} onClick={save}>
                {saveMutation.isPending ? '正在保存…' : '保存用途偏好'}
              </Button>
            </div>
          </div>
        </>
      )}
    </section>
  )
}
