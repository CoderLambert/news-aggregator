import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Button } from '@/components/ui/button'
import { useDefaultAIModel } from '@/hooks/useDefaultAIModel'
import { observePrivateTranslation } from '@/services/privateTranslationStream'
import { ConnectionRequestError } from '@/services/aiConnectionsApi'
import { WorkspaceError } from '@/services/workspaceApi'
import { newsKeys } from '@/services/newsQueries'
import {
  cancelPrivateTranslation, latestPrivateTranslation, retryPrivateTranslation, startPrivateTranslation, type PrivateTranslationTask,
} from '@/services/privateTranslationApi'

interface Props { viewer: number; newsId: number; sourceRevision: number; sourceMarkdown: string; onTaskChange?: (task: PrivateTranslationTask | null) => void; onStart?: () => void }
export default function PrivateTranslationPanel(props: Props) {
  return <TranslationSession key={`${props.viewer}:${props.newsId}:${props.sourceRevision}`} {...props} />
}
function TranslationSession({ viewer, newsId, sourceRevision, sourceMarkdown, onTaskChange, onStart }: Props) {
  const client = useQueryClient()
  const key = useMemo(() => ['private', 'byok-translation', viewer, newsId, sourceRevision] as const, [viewer, newsId, sourceRevision])
  const [sending, setSending] = useState(false)
  const [unknown, setUnknown] = useState(false)
  const [rejection, setRejection] = useState('')
  const [live, setLive] = useState(false)
  const mounted = useRef(true)
  const inFlight = useRef(false)
  const controller = useRef<AbortController | null>(null)
  useEffect(() => {
    mounted.current = true
    return () => { mounted.current = false; controller.current?.abort() }
  }, [])
  const models = useDefaultAIModel(viewer, 'full_translation')
  const [streamVersion, setStreamVersion] = useState(0)
  const [observationLost, setObservationLost] = useState(false)
  const recovery = useQuery({
    queryKey: key,
    queryFn: ({ signal }) => latestPrivateTranslation(newsId, signal),
    retry: false,

  })
  const task = recovery.isError ? null : recovery.data
  const selected = models.selection?.model_config_id ?? ''
  const refetch = recovery.refetch
  const taskId = task?.task_id, taskGeneration = task?.generation, taskStatus = task?.status
  useEffect(() => { onTaskChange?.(task ?? null) }, [onTaskChange, task])
  useEffect(() => {
    if (taskStatus === 'succeeded') void client.invalidateQueries({ queryKey: newsKeys.viewerDetails(viewer) })
  }, [client, viewer, taskId, taskStatus])
  useEffect(() => {
    if (!taskId || !['queued', 'running'].includes(taskStatus ?? '')) return
    const current = client.getQueryData<PrivateTranslationTask | null>(key)
    if (!current) return
    return observePrivateTranslation(current, {
      onTask: value => { if (mounted.current) { setLive(true); setObservationLost(false); client.setQueryData<PrivateTranslationTask | null>(key, current => {
        if (current && !['queued', 'running'].includes(current.status) && current.status !== value.status) return current
        return value
      }) } },
      onLost: () => { if (mounted.current) { setLive(false); setObservationLost(true); void refetch() } },
    })
  }, [taskId, taskGeneration, taskStatus, client, key, refetch, streamVersion])
  const tooLarge = [...sourceMarkdown].length > 64000 || new TextEncoder().encode(sourceMarkdown).length > 256000
  const hidden = models.error instanceof ConnectionRequestError && models.error.status === 403
  const recoverable = task?.status === 'queued'
  const active = task !== null && task !== undefined && ['queued', 'running'].includes(task.status)
  const retryable = task !== null && task !== undefined &&
    ['succeeded', 'failed', 'cancelled', 'interrupted'].includes(task.status)
  const eligible = Boolean(selected)
  const runMutation = async (kind: 'start' | 'retry' | 'cancel') => {
    if (hidden || inFlight.current || sending || recovery.isPending || recovery.isError) return
    if (kind === 'start' && ((!recoverable && (!eligible || task || unknown || tooLarge)))) return
    if (kind === 'retry' && (!task || !retryable || !eligible || unknown || tooLarge)) return
    if (kind === 'cancel' && (!task || !active)) return
    if (kind !== 'cancel') onStart?.()
    inFlight.current = true
    setSending(true)
    setRejection('')
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
    setObservationLost(false)
    setStreamVersion(value => value + 1)
    const [result] = await Promise.all([recovery.refetch(), models.refetch()])
    if (result.data) { setUnknown(false); setRejection('') }
  }
  if (hidden) return <p className="text-sm text-muted-foreground">个人模型调用已关闭；已保存译文仍可阅读。</p>
  const pending = models.isPending || recovery.isPending
  const uncertain = unknown || recovery.isError || models.isError || observationLost
  const canStart = !pending && !uncertain && !tooLarge && eligible && !sending
  const label = sending ? '正在提交…' : pending ? '正在读取翻译配置…' : uncertain ? '读取翻译状态' :
    active ? (task?.status === 'queued' ? '继续翻译' : '正在翻译…') : task?.status === 'succeeded' ? '重新翻译' :
    retryable ? '重试翻译' : '翻译为中文'
  return <div aria-label="全文翻译" className="flex max-w-full flex-wrap items-center gap-2">
    <Button type="button" size="sm" className="rounded-full" disabled={(!uncertain && active && !recoverable) || sending || (!uncertain && !canStart)}
      title="使用已保存的默认模型翻译全文"
      onClick={() => uncertain ? void refresh() : void runMutation(retryable ? 'retry' : 'start')}>
      {label}
    </Button>
    {active && <Button type="button" size="sm" variant="outline" className="rounded-full" disabled={sending}
      onClick={() => void runMutation('cancel')}>取消翻译</Button>}
    {!pending && !eligible && !active && !models.isError && <span role="status" className="text-xs text-muted-foreground">默认翻译模型当前不可用。</span>}
    {active && <span role="status" className="text-xs text-muted-foreground">{live && task?.progress ? '正在接收译文' : '正在等待模型响应'}。</span>}
    {task && ['failed', 'cancelled', 'interrupted'].includes(task.status) && <span role="status" className="text-xs text-muted-foreground">
      {task.status === 'cancelled' ? '翻译已取消' : '翻译未完成'}。
    </span>}
    {tooLarge && <span role="alert">文章过长，暂无法全文翻译；不会截断原文。</span>}
    {rejection && <span role="alert">{rejection}</span>}
    {uncertain && <span role="alert">状态尚未确认，请先读取状态；不会重复发送收费请求。</span>}
  </div>
}
