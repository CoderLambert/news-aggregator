import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertCircle, Pause, Play, RefreshCw, RotateCcw, SearchCheck, Square } from 'lucide-react'
import AdminLayout from '@/components/admin/AdminLayout'
import ConnectionStatus from '@/features/rss/ConnectionStatus'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { cancelSearchIndexRun, createSearchIndexRun, updateSearchIndexSettings } from '@/services/searchIndexAdminApi'
import { searchIndexAdminKeys, searchIndexDashboardOptions } from '@/services/searchIndexAdminQueries'
import type { SearchIndexRun, SearchIndexSettings } from '@/types/searchIndexAdmin'
import { useAuth } from '@/context/AuthContext'

const dateFormatter = new Intl.DateTimeFormat('zh-CN', {
  month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit',
})

function formatDate(value: string | null): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return dateFormatter.format(date)
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
    deferred: '等待执行', rate_limited: '限流等待', blocked: '源站拒绝',
    network_error: '网络异常', http_error: '源站响应异常', filtered: '请求被过滤', parse_failed: '解析异常',
    unsupported: '渠道受限',
  } as Record<string, string>)[status] ?? (status || '尚未运行')
}

function StatusBadge({ status }: { status: string }) {
  const variant = status === 'succeeded' ? 'green'
    : ['failed', 'cancelled', 'blocked', 'network_error', 'http_error', 'filtered', 'parse_failed'].includes(status) ? 'red'
      : ['queued', 'running', 'cancel_requested', 'partial', 'deferred', 'rate_limited'].includes(status) ? 'amber' : 'gray'
  return <Badge variant={variant}>{statusLabel(status)}</Badge>
}

function Metric({ label, value }: { label: string; value: number }) {
  return <div className="rounded-lg bg-muted px-3 py-2"><span className="block text-xs text-muted-foreground">{label}</span><strong>{value}</strong></div>
}

function IndexSettingsCard({ settings, busy, onSave }: {
  settings: SearchIndexSettings
  busy: boolean
  onSave: (payload: { enabled?: boolean; interval_seconds?: number; batch_size?: number }) => void
}) {
  const [minutes, setMinutes] = useState(() => String(Math.round(settings.intervalSeconds / 60)))
  const [batchSize, setBatchSize] = useState(() => String(settings.batchSize))
  const parsedMinutes = Number(minutes)
  const parsedBatchSize = Number(batchSize)
  const valid = Number.isInteger(parsedMinutes) && parsedMinutes >= 1 && parsedMinutes <= 1440
    && Number.isInteger(parsedBatchSize) && parsedBatchSize >= 1 && parsedBatchSize <= 500
  return (
    <Card>
      <CardHeader><CardTitle>自动同步</CardTitle><CardDescription>周期核对会修复遗漏、变化和孤立向量。</CardDescription></CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-center gap-3"><StatusBadge status={settings.enabled ? 'running' : 'cancelled'} /><span className="text-sm text-muted-foreground">下次核对：{formatDate(settings.nextRunAt)}</span></div>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="grid gap-1.5 text-sm font-medium">同步间隔（分钟）<Input inputMode="numeric" min={1} max={1440} type="number" value={minutes} onChange={(event) => setMinutes(event.target.value)} /></label>
          <label className="grid gap-1.5 text-sm font-medium">批大小<Input inputMode="numeric" min={1} max={500} type="number" value={batchSize} onChange={(event) => setBatchSize(event.target.value)} /></label>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" disabled={busy || !valid} onClick={() => onSave({ interval_seconds: parsedMinutes * 60, batch_size: parsedBatchSize })}>保存设置</Button>
          <Button disabled={busy} variant={settings.enabled ? 'outline' : 'default'} onClick={() => onSave({ enabled: !settings.enabled })}>{settings.enabled ? <Pause aria-hidden="true" /> : <Play aria-hidden="true" />}{settings.enabled ? '暂停自动同步' : '启用自动同步'}</Button>
        </div>
      </CardContent>
    </Card>
  )
}

function IndexRunSummary({ run, busy, onCancel }: { run: SearchIndexRun; busy: boolean; onCancel: (id: string) => void }) {
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2"><StatusBadge status={run.status} /><strong>{run.mode === 'rebuild' ? '完整重建' : '增量同步'}</strong><span className="text-sm text-muted-foreground">{run.trigger} · {formatDuration(run.durationSeconds)}</span></div>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
        <Metric label="新闻" value={run.newsCount} /><Metric label="写入" value={run.upsertedCount} /><Metric label="删除" value={run.deletedCount} /><Metric label="变化" value={run.changedCount} /><Metric label="失败" value={run.failedCount} />
      </div>
      {run.safeErrorMessage ? <p className="text-sm text-red-700">{run.safeErrorMessage}</p> : null}
      {['queued', 'running'].includes(run.status) ? <Button variant="destructive" disabled={busy} onClick={() => onCancel(run.id)}><Square aria-hidden="true" />请求停止</Button> : null}
      {run.status === 'cancel_requested' ? <p role="status" className="text-sm text-amber-700">将在当前批次边界安全停止。</p> : null}
    </div>
  )
}

function SearchIndexSection() {
  const queryClient = useQueryClient()
  const dashboard = useQuery(searchIndexDashboardOptions())
  const [actionError, setActionError] = useState('')
  const refresh = async () => {
    setActionError('')
    await queryClient.invalidateQueries({ queryKey: searchIndexAdminKeys.all })
  }
  const settingsMutation = useMutation({ mutationFn: updateSearchIndexSettings, onSuccess: refresh, onError: (error) => setActionError(error instanceof Error ? error.message : '保存索引设置失败。') })
  const runMutation = useMutation({ mutationFn: createSearchIndexRun, onSuccess: refresh, onError: (error) => setActionError(error instanceof Error ? error.message : '创建索引任务失败。') })
  const cancelMutation = useMutation({ mutationFn: cancelSearchIndexRun, onSuccess: refresh, onError: (error) => setActionError(error instanceof Error ? error.message : '停止索引任务失败。') })
  const busy = settingsMutation.isPending || runMutation.isPending || cancelMutation.isPending

  if (dashboard.isLoading) return <section id="search-index" className="mt-10 h-56 animate-pulse rounded-xl bg-muted" aria-label="正在加载搜索索引状态" />
  if (dashboard.isError || !dashboard.data) return <section id="search-index" className="mt-10"><Card><CardHeader><CardTitle>搜索索引状态不可用</CardTitle><CardDescription>{dashboard.error instanceof Error ? dashboard.error.message : '无法读取索引状态。'}</CardDescription></CardHeader><CardContent><Button onClick={() => void dashboard.refetch()}><RefreshCw aria-hidden="true" />重试</Button></CardContent></Card></section>

  const data = dashboard.data
  const drift = data.audit.missingCount + data.audit.changedCount + data.audit.orphanedCount
  return (
    <section id="search-index" className="mt-10 scroll-mt-20 space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div><h2 className="flex items-center gap-2 text-xl font-semibold"><SearchCheck aria-hidden="true" />搜索索引</h2><p className="mt-1 text-sm text-muted-foreground">自动修复新增、变化和删除；每分钟刷新，核对统计最多缓存 60 秒。</p></div>
        <div className="flex flex-wrap gap-2"><Button variant="outline" disabled={busy || dashboard.isFetching} onClick={() => void dashboard.refetch()}><RefreshCw aria-hidden="true" />刷新</Button><Button variant="outline" disabled={busy || Boolean(data.activeRun)} onClick={() => runMutation.mutate('sync')}>立即同步</Button><Button disabled={busy || Boolean(data.activeRun)} onClick={() => { if (window.confirm('确认构建新的完整索引？当前索引会持续服务，校验成功后才切换。')) runMutation.mutate('rebuild') }}><RotateCcw aria-hidden="true" />完整重建</Button></div>
      </div>
      {actionError ? <div role="alert" className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800 dark:border-red-900/60 dark:bg-red-950/35 dark:text-red-200"><AlertCircle aria-hidden="true" className="mt-0.5 size-4 shrink-0" />{actionError}</div> : null}
      {!data.settings.workerOnline ? <div role="status" className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-900/60 dark:bg-amber-950/35 dark:text-amber-200">索引 Worker 当前离线；搜索仍可使用现有索引，排队任务会在 Worker 恢复后继续。</div> : null}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
        <Metric label="新闻" value={data.audit.newsCount} /><Metric label="向量" value={data.audit.vectorCount} /><Metric label="缺失" value={data.audit.missingCount} /><Metric label="需更新" value={data.audit.changedCount} /><Metric label="孤立" value={data.audit.orphanedCount} />
      </div>
      <div className="grid gap-6 lg:grid-cols-2">
        <IndexSettingsCard key={data.settings.updatedAt} settings={data.settings} busy={busy} onSave={(payload) => settingsMutation.mutate(payload)} />
        <Card><CardHeader><CardTitle>运行状态</CardTitle><CardDescription>{data.settings.workerOnline ? `Worker 在线 · 最近成功 ${formatDate(data.settings.lastSuccessAt)}` : 'Worker 没有有效心跳'} · {data.settings.schemaVersion}</CardDescription></CardHeader><CardContent>{data.activeRun ? <IndexRunSummary run={data.activeRun} busy={busy} onCancel={(id) => cancelMutation.mutate(id)} /> : <p className={`text-sm ${drift ? 'text-amber-700' : 'text-emerald-700'}`}>{drift ? `检测到 ${drift} 项待同步。` : '数据库与向量索引一致。'}</p>}</CardContent></Card>
      </div>
      <Card><CardHeader><CardTitle>最近索引任务</CardTitle><CardDescription>错误信息经过脱敏，不包含文章正文、文件路径或凭据。</CardDescription></CardHeader><CardContent className="space-y-3">{data.recentRuns.length ? data.recentRuns.map((run) => <div key={run.id} className="border-b pb-3 last:border-0 last:pb-0"><IndexRunSummary run={run} busy={busy} onCancel={(id) => cancelMutation.mutate(id)} /></div>) : <p className="text-sm text-muted-foreground">暂无索引任务。</p>}</CardContent></Card>
    </section>
  )
}

export default function AdminPage() {
  const { user } = useAuth()
  return <AdminLayout>
    <section id="overview" className="scroll-mt-20 space-y-4">
      <h1 className="text-2xl font-semibold">RSS 与搜索管理</h1>
      <p className="text-sm text-muted-foreground">查看订阅源连接和文章同步状态，管理搜索索引。</p>
      {user && <ConnectionStatus key={user.id} viewer={user.id} admin={user.isSuperuser} />}
    </section>
    <SearchIndexSection />
  </AdminLayout>
}
