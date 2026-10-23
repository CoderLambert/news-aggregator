import { useQuery } from '@tanstack/react-query'
import { CircleCheck, CircleMinus, CircleX, RefreshCw, ServerCog } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  runtimeHealthCheckNames,
  runtimeHealthOptions,
  type RuntimeHealthCheck,
  type RuntimeHealthCheckName,
} from '@/services/runtimeHealthAdminApi'

const CHECK_LABELS: Record<RuntimeHealthCheckName, string> = {
  database: '应用数据库',
  rss_worker: 'RSS 同步 Worker',
  rss_engine: 'RSS 引擎',
  channel_worker: '频道处理 Worker',
  search_index: '搜索索引 Worker',
  translation_redis: '翻译 Redis',
  ai_gateway: 'AI 网关',
}

const READY_DETAILS: Record<RuntimeHealthCheckName, string> = {
  database: '数据库查询正常。',
  rss_worker: '同步心跳有效。',
  rss_engine: '同步 Worker 已确认引擎可用。',
  channel_worker: '频道处理心跳有效。',
  search_index: '索引 Worker 心跳有效。',
  translation_redis: 'Redis PING 正常。',
  ai_gateway: '网关及其数据库已就绪。',
}

const UNAVAILABLE_DETAILS: Record<RuntimeHealthCheckName, string> = {
  database: '数据库查询失败。',
  rss_worker: '同步心跳缺失、过期或配置无效。',
  rss_engine: '同步 Worker 尚未确认引擎可用。',
  channel_worker: '频道处理心跳缺失或过期。',
  search_index: '索引配置缺失或 Worker 心跳无效。',
  translation_redis: 'Redis 当前不可连接。',
  ai_gateway: '网关配置无效或就绪检查失败。',
}

function CheckBadge({ check }: { check: RuntimeHealthCheck }) {
  const label = check.status === 'ready' ? '正常' : check.status === 'disabled' ? '未启用' : '异常'
  const variant = check.status === 'ready' ? 'green' : check.status === 'disabled' ? 'gray' : 'red'
  return <Badge variant={variant}>{label}</Badge>
}

function CheckIcon({ check }: { check: RuntimeHealthCheck }) {
  if (check.status === 'ready') return <CircleCheck aria-hidden="true" className="size-4 shrink-0 text-emerald-600" />
  if (check.status === 'disabled') return <CircleMinus aria-hidden="true" className="size-4 shrink-0 text-muted-foreground" />
  return <CircleX aria-hidden="true" className="size-4 shrink-0 text-red-600" />
}

function checkDetail(name: RuntimeHealthCheckName, check: RuntimeHealthCheck): string {
  if (check.status === 'ready') return READY_DETAILS[name]
  if (check.status === 'disabled') return '当前部署未启用此可选服务。'
  return UNAVAILABLE_DETAILS[name]
}

function formatCheckedAt(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '时间未知' : date.toLocaleString('zh-CN')
}

export default function RuntimeHealthCard({ viewer }: { viewer: number }) {
  const health = useQuery(runtimeHealthOptions(viewer))
  if (health.isLoading) {
    return <div className="h-64 animate-pulse rounded-xl bg-muted" aria-label="正在检查服务健康状态" />
  }
  if (health.isError || !health.data) {
    return (
      <Card role="alert">
        <CardHeader><CardTitle>服务健康状态不可用</CardTitle><CardDescription>无法读取受保护的运行状态。</CardDescription></CardHeader>
        <CardContent><Button onClick={() => void health.refetch()}><RefreshCw aria-hidden="true" />重试</Button></CardContent>
      </Card>
    )
  }

  const snapshot = health.data
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><ServerCog aria-hidden="true" />服务健康状态</CardTitle>
        <CardDescription>只检查本机基础设施与 Worker 心跳，不调用模型、Provider 或订阅源。</CardDescription>
        <CardAction><Button variant="outline" disabled={health.isFetching} onClick={() => void health.refetch()}><RefreshCw aria-hidden="true" />刷新</Button></CardAction>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <Badge variant={snapshot.ready ? 'green' : 'red'}>{snapshot.ready ? '所有已配置服务正常' : '存在异常服务'}</Badge>
          <span className="text-xs text-muted-foreground">检查时间：{formatCheckedAt(snapshot.checkedAt)}</span>
        </div>
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {runtimeHealthCheckNames.map((name) => {
            const check = snapshot.checks[name]
            return (
              <div key={name} className="flex items-start gap-3 rounded-lg border p-3">
                <CheckIcon check={check} />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center justify-between gap-2"><strong className="text-sm">{CHECK_LABELS[name]}</strong><CheckBadge check={check} /></div>
                  <p className="mt-1 text-xs text-muted-foreground">{checkDetail(name, check)}</p>
                </div>
              </div>
            )
          })}
        </div>
      </CardContent>
    </Card>
  )
}
