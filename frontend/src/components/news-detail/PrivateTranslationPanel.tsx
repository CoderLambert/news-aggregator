import { useEffect, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import MarkdownContent from '@/components/news-detail/MarkdownContent'
import { ConnectionRequestError, listAIConnections, listAIModels } from '@/services/aiConnectionsApi'
import { WorkspaceError } from '@/services/workspaceApi'
import {
  cancelPrivateTranslation, latestPrivateTranslation, retryPrivateTranslation, startPrivateTranslation,
} from '@/services/privateTranslationApi'

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
  const tooLarge = [...sourceMarkdown].length > 64000 || new TextEncoder().encode(sourceMarkdown).length > 256000
  const hidden = models.error instanceof ConnectionRequestError && models.error.status === 403
  const recoverable = task?.status === 'queued'
  const active = task !== null && task !== undefined && ['queued', 'running'].includes(task.status)
  const retryable = task !== null && task !== undefined &&
    ['succeeded', 'failed', 'cancelled', 'interrupted'].includes(task.status)
  const eligible = models.data?.some(model => model.id === selected) === true
  const runMutation = async (kind: 'start' | 'retry' | 'cancel') => {
    if (hidden || inFlight.current || sending || recovery.isPending || recovery.isError) return
    if (kind === 'start' && (!consent || (!recoverable && (!eligible || task || unknown || tooLarge)))) return
    if (kind === 'retry' && (!task || !retryable || !consent || !eligible || unknown || tooLarge)) return
    if (kind === 'cancel' && (!task || !active)) return
    inFlight.current = true
    setSending(true)
    setRejection('')
    setConsent(false)
    controller.current = new AbortController()
    try {
      if (kind === 'cancel') {
        const receipt = await cancelPrivateTranslation(
          task!.task_id, task!.generation, viewer, controller.current.signal,
        )
        if (mounted.current) {
          // Drop any cached private text immediately. A refresh may be denied
          // after source/credential access changes; the cancel receipt itself
          // intentionally contains no result or progress.
          client.setQueryData(key, {
            ...task!, status: receipt.status, error_code: receipt.error_code,
            progress: '', result: null, previous_result: null,
          })
          setUnknown(false)
          setObserving(true)
          void recovery.refetch()
        }
        return
      }
      const result = kind === 'retry'
        ? await retryPrivateTranslation(task!.task_id, selected, crypto.randomUUID(), viewer, controller.current.signal)
        : recoverable && task!.retry_of
          ? await retryPrivateTranslation(
            task!.retry_of, task!.model_config_id, task!.request_id, viewer, controller.current.signal,
          )
          : await startPrivateTranslation(
            newsId, recoverable ? task!.model_config_id : selected,
            recoverable ? task!.request_id : crypto.randomUUID(), viewer, controller.current.signal,
          )
      if (mounted.current) {
        client.setQueryData(key, result)
        setUnknown(false)
        setObserving(true)
      }
    } catch (reason) {
      if (mounted.current) {
        if (reason instanceof WorkspaceError && [400, 403, 404, 409, 429].includes(reason.status)) {
          setRejection(reason.status === 429 ? '排队数量达到上限，请稍后重新确认。' :
            reason.status === 400 ? '请求未获接受：原文可能超出预算，或包含暂不支持的引用围栏、列表行内围栏或四格及以上缩进围栏。请检查完整 Markdown 后重新确认。' :
            '权限、模型或任务已变化，请读取最新状态后重新确认。')
          void recovery.refetch()
        } else {
          setUnknown(true)
          // Reconcile only through GET. Never automatically resubmit a lost POST.
          void recovery.refetch().then(result => {
            if (mounted.current && result.data) setUnknown(false)
          })
        }
      }
    } finally {
      inFlight.current = false
      if (mounted.current) setSending(false)
    }
  }
  const refresh = async () => {
    setObserving(true)
    const result = await recovery.refetch()
    if (result.data) { setUnknown(false); setRejection('') }
  }
  if (hidden && !task) return null
  const canChooseConsent = recoverable || (!task && eligible) || (retryable && eligible)
  return <section aria-label="个人全文翻译" className="my-6 rounded-xl border border-border p-4">
    <h2 className="font-semibold">个人全文翻译（私有）</h2>
    {hidden ? <p className="my-2 text-sm text-muted-foreground">个人模型调用已关闭，可继续查看已保存的翻译记录。</p> : <>
      <p className="my-2 text-sm text-muted-foreground">短中篇仍使用一次请求。较长文章按完整 Markdown 块顺序拆分，每次最多 8000 字符 / 32000 UTF-8 字节，整篇最多 64000 字符 / 256000 UTF-8 字节、8 次请求和 262144 字符输出。不可拆分的大块会被拒绝，不截断、不自动重试；长文最多可能产生 8 次服务商费用。取消不会保证已派发请求停止或免除费用；重新生成会创建新的付费尝试。</p>
      <label>翻译模型
        <select aria-label="翻译模型" value={selected} disabled={sending || active}
          onChange={event => { setSelected(event.target.value); setConsent(false) }}
          className="mx-2 rounded border border-input bg-background p-2">
          <option value="">请选择已验证的个人模型</option>
          {models.data?.map(model => <option key={model.id} value={model.id}>{model.name}</option>)}
        </select>
      </label>
      <Link to="/settings/ai" className="text-primary underline">模型设置</Link>
      {models.isError && <p role="alert">暂时无法读取个人模型。</p>}
      {models.data?.length === 0 && <p>此用途暂只支持已验证的 DeepSeek Flash 流式模型。</p>}
      {canChooseConsent && <label className="my-2 block">
        <input type="checkbox" checked={consent} disabled={sending}
          onChange={event => setConsent(event.target.checked)} />
        我确认这次全文翻译可能产生费用；长文最多顺序发送 8 次个人模型请求，已派发的请求即使失败也可能计费。重新生成会再次发送并可能再次计费。
      </label>}
      {!task || recoverable ? <button type="button" onClick={() => void runMutation('start')}
        disabled={!consent || sending || (!recoverable && (!eligible || unknown || tooLarge)) || recovery.isPending || recovery.isError}
        className="rounded bg-primary px-3 py-2 text-primary-foreground disabled:opacity-50">
        {sending ? '正在提交…' : recoverable ? '恢复排队任务' : '开始私有翻译'}
      </button> : null}
      {task && retryable && <button type="button" onClick={() => void runMutation('retry')}
        disabled={!consent || sending || !eligible || unknown || tooLarge || recovery.isPending || recovery.isError}
        className="rounded bg-primary px-3 py-2 text-primary-foreground disabled:opacity-50">
        {sending ? '正在提交…' : '重新生成（新任务）'}
      </button>}
      {task && active && <button type="button" onClick={() => void runMutation('cancel')}
        disabled={sending || recovery.isPending || recovery.isError}
        className="ml-3 rounded border px-3 py-2 disabled:opacity-50">
        {sending ? '正在处理…' : '明确取消任务'}
      </button>}
      {tooLarge && <p role="alert">原文超过全文翻译上限，请保留完整原文；不会截断后发送。</p>}
      {rejection && <p role="alert">{rejection}</p>}
      {(unknown && !task) && <p role="alert">提交结果未知。请读取任务状态，不要重复发送收费请求。</p>}
      {recovery.isError && <p role="alert">无法读取当前任务，原文、权限或模型可能已变化。</p>}
    </>}
    <button type="button" className="ml-3 underline" onClick={() => void refresh()}>
      读取任务状态
    </button>
    {task && <div className="mt-3">
      <p role="status">{task.status === 'succeeded' ? '私有翻译已完成' :
        task.status === 'queued' ? '任务已排队' : task.status === 'running' ? '正在翻译，以下内容尚未完成' :
        task.status === 'cancelled' ? '任务已取消；已派发的服务商请求仍可能产生费用。' :
        '本次翻译未完成。已派发的服务商请求仍可能产生费用，不会自动重复收费请求。'}</p>
      <p className="text-xs text-muted-foreground">任务：{task.task_id}</p>
      {active && <button type="button" className="underline"
        onClick={() => setObserving(false)}>停止等待（后台任务继续）</button>}
      {task.status === 'succeeded' && task.result
        ? <><p>来源：{task.result.provider} · {task.result.model}；私有结果 #{task.result.result_id}</p>
          <MarkdownContent content={task.result.content} /></>
        : task.progress && <pre className="whitespace-pre-wrap break-words text-sm">{task.progress}</pre>}
      {task.previous_result && <section aria-label="此前成功的私有译文" className="mt-3 border-t pt-3">
        <p>此前成功的私有译文（结果 #{task.previous_result.result_id}）</p>
        <MarkdownContent content={task.previous_result.content} />
      </section>}
    </div>}
    <p className="mt-2 text-xs text-muted-foreground">关闭页面或停止等待不会取消后台任务，也不能撤销已经派发的供应商费用。重新打开只读取同一任务。</p>
  </section>
}
