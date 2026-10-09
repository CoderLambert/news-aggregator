import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Activity, AlertCircle, CheckCircle2, Clock3, Pause, Play, RefreshCw,
  RotateCcw, Server, Square, TimerReset, XCircle,
} from 'lucide-react'
import AdminLayout from '@/components/admin/AdminLayout'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import {
  CrawlerAdminApiError,
  cancelCrawlRun,
  createCrawlBatch,
  retryCrawlRun,
  updateCrawlerSettings,
  updateCrawlerTarget,
} from '@/services/crawlerAdminApi'
import { crawlerAdminKeys, crawlerDashboardOptions } from '@/services/crawlerAdminQueries'
import type { CrawlBatch, CrawlerSettings, CrawlerTarget, CrawlRun } from '@/types/crawlerAdmin'
import { useAuth } from '@/context/AuthContext'

function formatDate(value: string | null): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit',
  }).format(date)
}

function formatDuration(seconds: number | null): string {
  if (seconds === null) return '—'
  const minutes = Math.floor(seconds / 60)
  const remainder = seconds % 60
  return minutes ? `${minutes}分 ${remainder}秒` : `${remainder}秒`
}

function statusLabel(status: string): string {
  return ({
    queued: '排队中', running: '运行中', succeeded: '成功', failed: '失败',
    partial: '部分成功', cancel_requested: '正在停止', cancelled: '已取消', skipped: '已跳过',
  } as Record<string, string>)[status] ?? (status || '尚未运行')
}

function StatusBadge({ status }: { status: string }) {
  const variant = status === 'succeeded' ? 'green'
    : ['failed', 'cancelled'].includes(status) ? 'red'
      : ['queued', 'running', 'cancel_requested', 'partial'].includes(status) ? 'amber' : 'gray'
  return <Badge variant={variant}>{statusLabel(status)}</Badge>
}

function SchedulerCard({ settings, busy, onSave }: {
  settings: CrawlerSettings
  busy: boolean
  onSave: (payload: { scheduler_enabled?: boolean; interval_seconds?: number }) => void
}) {
  const [minutes, setMinutes] = useState(() => String(Math.round(settings.intervalSeconds / 60)))
  const parsedMinutes = Number(minutes)
  const intervalValid = Number.isInteger(parsedMinutes) && parsedMinutes >= 1 && parsedMinutes <= 10080

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><TimerReset aria-hidden="true" className="size-5" />自动调度</CardTitle>
        <CardDescription>暂停只阻止创建新批次，当前任务会继续完成。</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-center gap-3">
          <StatusBadge status={settings.schedulerEnabled ? 'running' : 'cancelled'} />
          <span className="text-sm text-muted-foreground">下次执行：{formatDate(settings.nextRunAt)}</span>
        </div>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
          <label className="grid gap-1.5 text-sm font-medium">
            抓取间隔（分钟）
            <Input className="w-40" inputMode="numeric" min={1} max={10080} type="number" value={minutes} onChange={(event) => setMinutes(event.target.value)} />
          </label>
          <Button variant="outline" disabled={busy || !intervalValid} onClick={() => onSave({ interval_seconds: parsedMinutes * 60 })}>
            保存间隔
          </Button>
          <Button disabled={busy} variant={settings.schedulerEnabled ? 'outline' : 'default'} onClick={() => onSave({ scheduler_enabled: !settings.schedulerEnabled })}>
            {settings.schedulerEnabled ? <Pause aria-hidden="true" /> : <Play aria-hidden="true" />}
            {settings.schedulerEnabled ? '暂停调度' : '启用调度'}
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

function ActiveRunCard({ run, busy, onCancel }: { run: CrawlRun | null; busy: boolean; onCancel: (id: string) => void }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><Activity aria-hidden="true" className="size-5" />当前任务</CardTitle>
        <CardDescription>Worker 全局保持单个 Spider 并发。</CardDescription>
      </CardHeader>
      <CardContent>
        {!run ? (
          <p className="text-sm text-muted-foreground">当前没有排队或运行任务。</p>
        ) : (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-3">
              <strong>{run.targetName}</strong><StatusBadge status={run.status} />
              <span className="text-sm text-muted-foreground">{formatDuration(run.durationSeconds)}</span>
            </div>
            <div className="grid grid-cols-3 gap-3 text-sm">
              <Metric label="条目" value={run.items} />
              <Metric label="响应" value={run.responses} />
              <Metric label="错误" value={run.errors} />
            </div>
            {run.status !== 'cancel_requested' ? (
              <Button variant="destructive" disabled={busy} onClick={() => onCancel(run.id)}><Square aria-hidden="true" />请求停止</Button>
            ) : <p className="text-sm text-amber-700" role="status">停止请求已发送，正在等待 Worker 结束进程。</p>}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function Metric({ label, value }: { label: string; value: number }) {
  return <div className="rounded-lg bg-muted px-3 py-2"><span className="block text-xs text-muted-foreground">{label}</span><strong>{value}</strong></div>
}

function TargetRow({ target, busy, onToggle, onRun }: {
  target: CrawlerTarget
  busy: boolean
  onToggle: (target: CrawlerTarget) => void
  onRun: (spiderName: string) => void
}) {
  return (
    <tr className="border-b last:border-0">
      <td className="px-4 py-4"><strong className="block">{target.displayName}</strong><code className="text-xs text-muted-foreground">{target.spiderName}</code></td>
      <td className="px-4 py-4"><StatusBadge status={target.activeRun?.status || target.lastStatus} /></td>
      <td className="px-4 py-4 text-sm tabular-nums">{target.lastItems} / {target.lastResponses} / {target.lastErrors}</td>
      <td className="px-4 py-4 text-sm text-muted-foreground">{formatDate(target.lastFinishedAt)}</td>
      <td className="px-4 py-4">
        <div className="flex justify-end gap-2">
          <Button size="sm" variant="outline" disabled={busy || !target.enabled || Boolean(target.activeRun)} onClick={() => onRun(target.spiderName)}><Play aria-hidden="true" />运行</Button>
          <Button size="sm" variant="ghost" disabled={busy || Boolean(target.activeRun)} onClick={() => onToggle(target)}>{target.enabled ? '停用' : '启用'}</Button>
        </div>
      </td>
    </tr>
  )
}

function BatchCard({ batch, busy, onRetry, onCancel }: {
  batch: CrawlBatch
  busy: boolean
  onRetry: (id: string) => void
  onCancel: (id: string) => void
}) {
  return (
    <article className="rounded-xl border bg-background p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2"><StatusBadge status={batch.status} /><span className="text-sm font-medium">{batch.trigger}</span></div>
          <p className="mt-2 text-sm text-muted-foreground">{formatDate(batch.queuedAt)} · 共 {batch.total} 个来源</p>
        </div>
        <div className="text-right text-sm tabular-nums"><span className="text-emerald-700">成功 {batch.succeeded}</span> · <span className="text-red-700">失败 {batch.failed}</span> · 取消 {batch.cancelled}</div>
      </div>
      {batch.runs.map((run) => (
        <div key={run.id} className="mt-3 flex flex-wrap items-center justify-between gap-3 border-t pt-3 text-sm">
          <div><strong>{run.targetName}</strong><span className="ml-2 text-muted-foreground">{run.items} 条 · {formatDuration(run.durationSeconds)}</span>{run.safeError ? <p className="mt-1 text-red-700">{run.safeError}</p> : null}</div>
          <div className="flex items-center gap-2">
            <StatusBadge status={run.status} />
            {['failed', 'cancelled', 'skipped'].includes(run.status) ? <Button size="sm" variant="outline" disabled={busy} onClick={() => onRetry(run.id)}><RotateCcw aria-hidden="true" />重试</Button> : null}
            {['queued', 'running'].includes(run.status) ? <Button size="sm" variant="destructive" disabled={busy} onClick={() => onCancel(run.id)}><Square aria-hidden="true" />停止</Button> : null}
          </div>
        </div>
      ))}
    </article>
  )
}

export default function CrawlerAdminPage() {
  const queryClient = useQueryClient()
  const { refresh: refreshAuth } = useAuth()
  const dashboard = useQuery(crawlerDashboardOptions())
  const [actionError, setActionError] = useState('')

  useEffect(() => {
    if (dashboard.error instanceof CrawlerAdminApiError && dashboard.error.status === 403) {
      void refreshAuth()
    }
  }, [dashboard.error, refreshAuth])

  const refresh = async () => {
    setActionError('')
    await queryClient.invalidateQueries({ queryKey: crawlerAdminKeys.all })
  }

  const settingsMutation = useMutation({
    mutationFn: updateCrawlerSettings,
    onSuccess: refresh,
    onError: (error) => setActionError(error instanceof Error ? error.message : '保存调度设置失败。'),
  })
  const targetMutation = useMutation({
    mutationFn: ({ target, enabled }: { target: string; enabled: boolean }) => updateCrawlerTarget(target, enabled),
    onSuccess: refresh,
    onError: (error) => setActionError(error instanceof Error ? error.message : '更新来源失败。'),
  })
  const runMutation = useMutation({
    mutationFn: (spiders?: string[]) => createCrawlBatch(spiders),
    onSuccess: refresh,
    onError: (error) => setActionError(error instanceof Error ? error.message : '创建抓取任务失败。'),
  })
  const cancelMutation = useMutation({
    mutationFn: cancelCrawlRun,
    onSuccess: refresh,
    onError: (error) => setActionError(error instanceof Error ? error.message : '停止任务失败。'),
  })
  const retryMutation = useMutation({
    mutationFn: retryCrawlRun,
    onSuccess: refresh,
    onError: (error) => setActionError(error instanceof Error ? error.message : '重试任务失败。'),
  })
  const busy = settingsMutation.isPending || targetMutation.isPending || runMutation.isPending || cancelMutation.isPending || retryMutation.isPending

  if (dashboard.isLoading) return <AdminLayout><div className="h-72 animate-pulse rounded-xl bg-muted" aria-label="正在加载爬虫控制台" /></AdminLayout>
  if (dashboard.isError || !dashboard.data) {
    const message = dashboard.error instanceof Error ? dashboard.error.message : '无法读取爬虫控制台。'
    return <AdminLayout><Card><CardHeader><CardTitle>控制台加载失败</CardTitle><CardDescription>{message}</CardDescription></CardHeader><CardContent><Button onClick={() => void dashboard.refetch()}><RefreshCw aria-hidden="true" />重试</Button></CardContent></Card></AdminLayout>
  }

  const data = dashboard.data
  return (
    <AdminLayout>
      <div id="overview" className="space-y-6 scroll-mt-20">
        <div className="grid gap-4 sm:grid-cols-3">
          <Card className="gap-3 py-5"><CardContent className="flex items-center gap-3"><div className={`flex size-11 items-center justify-center rounded-full ${data.settings.workerOnline ? 'bg-emerald-50 text-emerald-700' : 'bg-red-50 text-red-700'}`}><Server aria-hidden="true" /></div><div><p className="font-semibold">Worker {data.settings.workerOnline ? '在线' : '离线'}</p><p className="text-xs text-muted-foreground">心跳 {formatDate(data.settings.workerHeartbeatAt)}</p></div></CardContent></Card>
          <Card className="gap-3 py-5"><CardContent className="flex items-center gap-3"><div className="flex size-11 items-center justify-center rounded-full bg-blue-50 text-blue-700"><Clock3 aria-hidden="true" /></div><div><p className="font-semibold">{Math.round(data.settings.intervalSeconds / 60)} 分钟一次</p><p className="text-xs text-muted-foreground">Docker 自动调度</p></div></CardContent></Card>
          <Card className="gap-3 py-5"><CardContent className="flex items-center gap-3"><div className="flex size-11 items-center justify-center rounded-full bg-violet-50 text-violet-700"><CheckCircle2 aria-hidden="true" /></div><div><p className="font-semibold">{data.targets.filter((target) => target.enabled).length} 个来源启用</p><p className="text-xs text-muted-foreground">共 {data.targets.length} 个注册来源</p></div></CardContent></Card>
        </div>

        {actionError ? <div role="alert" className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800"><AlertCircle aria-hidden="true" className="mt-0.5 size-4 shrink-0" />{actionError}</div> : null}
        {!data.settings.workerOnline ? <div role="status" className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900"><XCircle aria-hidden="true" className="mt-0.5 size-4 shrink-0" />Worker 当前没有有效心跳。任务会保留在队列中，恢复容器后继续处理。</div> : null}

        <div className="grid gap-6 lg:grid-cols-2">
          <SchedulerCard key={data.settings.updatedAt} settings={data.settings} busy={busy} onSave={(payload) => settingsMutation.mutate(payload)} />
          <ActiveRunCard run={data.activeRun} busy={busy} onCancel={(id) => { if (window.confirm('确认停止当前爬虫任务？')) cancelMutation.mutate(id) }} />
        </div>
      </div>

      <section id="sources" className="mt-10 scroll-mt-20">
        <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
          <div><h2 className="text-xl font-semibold">来源管理</h2><p className="mt-1 text-sm text-muted-foreground">定时批次只包含已启用来源，运行中的来源不能停用。</p></div>
          <div className="flex gap-2"><Button variant="outline" disabled={dashboard.isFetching} onClick={() => void dashboard.refetch()}><RefreshCw aria-hidden="true" className={dashboard.isFetching ? 'animate-spin' : ''} />刷新</Button><Button disabled={busy || Boolean(data.activeRun)} onClick={() => runMutation.mutate(undefined)}><Play aria-hidden="true" />立即抓取全部</Button></div>
        </div>
        <div className="overflow-x-auto rounded-xl border bg-background">
          <table className="w-full min-w-[780px] text-left">
            <thead className="bg-muted/60 text-xs text-muted-foreground"><tr><th className="px-4 py-3">来源</th><th className="px-4 py-3">状态</th><th className="px-4 py-3">条目 / 响应 / 错误</th><th className="px-4 py-3">最后完成</th><th className="px-4 py-3 text-right">操作</th></tr></thead>
            <tbody>{data.targets.map((target) => <TargetRow key={target.spiderName} target={target} busy={busy} onToggle={(item) => targetMutation.mutate({ target: item.spiderName, enabled: !item.enabled })} onRun={(spider) => runMutation.mutate([spider])} />)}</tbody>
          </table>
        </div>
      </section>

      <section id="history" className="mt-10 scroll-mt-20">
        <div className="mb-4"><h2 className="text-xl font-semibold">最近抓取历史</h2><p className="mt-1 text-sm text-muted-foreground">展示最近 8 个批次及脱敏后的失败原因。</p></div>
        <div className="space-y-3">{data.recentBatches.length ? data.recentBatches.map((batch) => <BatchCard key={batch.id} batch={batch} busy={busy} onRetry={(id) => retryMutation.mutate(id)} onCancel={(id) => { if (window.confirm('确认停止这个爬虫任务？')) cancelMutation.mutate(id) }} />) : <Card><CardContent className="py-8 text-center text-sm text-muted-foreground">暂无抓取历史。</CardContent></Card>}</div>
      </section>
    </AdminLayout>
  )
}
