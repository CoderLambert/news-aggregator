import { useEffect, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import MarkdownContent from '@/components/news-detail/MarkdownContent'
import { ConnectionRequestError, listAIConnections, listAIModels } from '@/services/aiConnectionsApi'
import { WorkspaceError } from '@/services/workspaceApi'
import { latestPrivateTranslation, startPrivateTranslation } from '@/services/privateTranslationApi'

interface Props { viewer: number; newsId: number; sourceRevision: number; sourceMarkdown: string }
export default function PrivateTranslationPanel(props: Props) {
  return <TranslationSession key={`${props.viewer}:${props.newsId}:${props.sourceRevision}`} {...props} />
}
function TranslationSession({ viewer, newsId, sourceRevision, sourceMarkdown }: Props) {
  const client = useQueryClient()
  const key = ['private', 'byok-translation', viewer, newsId, sourceRevision] as const
  const [selected, setSelected] = useState('')
  const [consent, setConsent] = useState(false)
  const [sending, setSending] = useState(false)
  const [unknown, setUnknown] = useState(false)
  const [rejection, setRejection] = useState('')
  const [observing, setObserving] = useState(true)
  const mounted = useRef(true)
  const inFlight = useRef(false)
  const controller = useRef<AbortController | null>(null)
  useEffect(() => {
    mounted.current = true
    return () => { mounted.current = false; controller.current?.abort() }
  }, [])
  const models = useQuery({
    queryKey: ['private', 'byok-translation-models', viewer],
    queryFn: async ({ signal }) => {
      const connections = (await listAIConnections(signal)).filter(c => c.is_enabled && c.key_saved)
      const lists = await Promise.all(connections.map(c => listAIModels(c, signal)))
      return connections.flatMap((connection, index) => lists[index]
        .filter(model => model.has_trusted_route && model.capabilities.text === 'supported' &&
          model.article_chat_supported === true && model.model_id === 'deepseek-flash')
        .map(model => ({ id: model.id, name: connection.display_name + ' · ' + model.display_name })))
    },
    retry: false,
  })
  const recovery = useQuery({
    queryKey: key,
    queryFn: ({ signal }) => latestPrivateTranslation(newsId, signal),
    retry: false,
    refetchInterval: query => observing && ['queued', 'running'].includes(query.state.data?.status ?? '') ? 1000 : false,
  })
  const task = recovery.isError ? null : recovery.data
  const tooLong = [...sourceMarkdown].length > 8000 || new TextEncoder().encode(sourceMarkdown).length > 32000
  const hidden = models.error instanceof ConnectionRequestError && models.error.status === 403
  const recoverable = task?.status === 'queued'
  const eligible = models.data?.some(model => model.id === selected) === true
  const start = async () => {
    if (inFlight.current || !consent || (!recoverable && (!eligible || task || unknown || tooLong)) || recovery.isPending || recovery.isError) return
    inFlight.current = true
    setSending(true)
    setRejection('')
    setConsent(false)
    controller.current = new AbortController()
    const requestId = recoverable ? task.request_id : crypto.randomUUID()
    try {
      const result = await startPrivateTranslation(newsId, recoverable ? task.model_config_id : selected, requestId, viewer, controller.current.signal)
      if (mounted.current) { client.setQueryData(key, result); setObserving(true) }
    } catch (reason) {
      if (mounted.current) {
        if (reason instanceof WorkspaceError && [400, 403, 404, 409, 429].includes(reason.status)) {
          setRejection(reason.status === 429 ? '排队数量达到上限，请稍后重新确认。' :
            reason.status === 400 ? '请求未获接受，请检查原文预算和模型，再重新确认。' :
            '权限、模型或任务已变化，请读取最新状态后重新确认。')
          void recovery.refetch()
        } else {
          setUnknown(true)
          // Reconcile with GET only. Never resubmit a timed-out/lost POST.
          void recovery.refetch()
        }
      }
    } finally {
      inFlight.current = false
      if (mounted.current) setSending(false)
    }
  }
  if (hidden) return null
  return <section aria-label="个人全文翻译" className="my-6 rounded-xl border border-border p-4">
    <h2 className="font-semibold">个人全文翻译（私有）</h2>
    <p className="my-2 text-sm text-muted-foreground">仅限短中篇：最多 8000 字符 / 32000 UTF-8 字节，翻译为简体中文。超限会拒绝，不截断、不自动重试。结果不发布到共享译文。</p>
    <label>翻译模型
      <select aria-label="翻译模型" value={selected} disabled={sending || !!task}
        onChange={event => { setSelected(event.target.value); setConsent(false) }}
        className="mx-2 rounded border border-input bg-background p-2">
        <option value="">请选择已验证的个人模型</option>
        {models.data?.map(model => <option key={model.id} value={model.id}>{model.name}</option>)}
      </select>
    </label>
    <Link to="/settings/ai" className="text-primary underline">模型设置</Link>
    {models.isError && <p role="alert">暂时无法读取个人模型。</p>}
    {models.data?.length === 0 && <p>此用途暂只支持已验证的 DeepSeek Flash 流式模型。</p>}
    <label className="my-2 block">
      <input type="checkbox" checked={consent} disabled={sending || (!recoverable && (!eligible || !!task))}
        onChange={event => setConsent(event.target.checked)} />
      我确认这次全文翻译可能产生服务商费用。
    </label>
    <button type="button" onClick={() => void start()} disabled={!consent || sending || (!recoverable && (!eligible || !!task || unknown || tooLong)) || recovery.isPending || recovery.isError}
      className="rounded bg-primary px-3 py-2 text-primary-foreground disabled:opacity-50">
      {sending ? '正在提交…' : recoverable ? '恢复排队任务' : '开始私有翻译'}
    </button>
    {tooLong && <p role="alert">原文超过本次短中篇预算，请保留完整原文；长文翻译尚未开放。</p>}
    {rejection && <p role="alert">{rejection}</p>}
    {(unknown && !task) && <p role="alert">提交结果未知。请读取任务状态，不要重复发送收费请求。</p>}
    {recovery.isError && <p role="alert">无法读取当前任务，原文、权限或模型可能已变化。</p>}
    <button type="button" className="ml-3 underline" onClick={() => { setObserving(true); void recovery.refetch() }}>
      读取任务状态
    </button>
    {task && <div className="mt-3">
      <p role="status">{task.status === 'succeeded' ? '私有翻译已完成' :
        task.status === 'queued' ? '任务已排队' : task.status === 'running' ? '正在翻译，以下内容尚未完成' :
        '本次翻译未完成，不会自动重复收费请求。失败任务的显式重试尚未开放。'}</p>
      <p className="text-xs text-muted-foreground">任务：{task.task_id}</p>
      {['queued', 'running'].includes(task.status) && <button type="button" className="underline"
        onClick={() => setObserving(false)}>停止等待（后台任务继续）</button>}
      {task.status === 'succeeded' && task.result
        ? <><p>来源：{task.result.provider} · {task.result.model}；私有结果 #{task.result.result_id}</p>
          <MarkdownContent content={task.result.content} /></>
        : task.progress && <pre className="whitespace-pre-wrap break-words text-sm">{task.progress}</pre>}
    </div>}
    <p className="mt-2 text-xs text-muted-foreground">关闭页面或停止等待不会取消后台任务，也不能撤销已经派发的供应商费用。重新打开只读取同一任务。</p>
  </section>
}
