import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertCircle, ExternalLink, Plus, RefreshCw, ShieldCheck } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { createJinaPolicy, fetchArticleBodyReviews, updateJinaPolicy } from '@/services/articleFetchAdminApi'
import { articleFetchAdminKeys, articleFetchDashboardOptions } from '@/services/articleFetchAdminQueries'
import type { ArticleFetchFailureCode, JinaFallbackPolicy } from '@/types/articleFetchAdmin'

function formatDate(value: string | null): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit',
  }).format(date)
}

function FailureCodes({ values }: { values: ArticleFetchFailureCode[] }) {
  if (!values.length) return <span className="text-muted-foreground">—</span>
  return (
    <div className="flex max-w-xl flex-wrap gap-1">
      {values.map((value, index) => (
        <code key={`${value.provider}:${value.code}:${index}`} className="rounded bg-muted px-1.5 py-0.5 text-xs">
          {value.provider}:{value.code}
        </code>
      ))}
    </div>
  )
}

function Metric({ label, value, detail }: { label: string; value: string | number; detail: string }) {
  return (
    <Card className="gap-2 py-5">
      <CardContent>
        <p className="text-sm text-muted-foreground">{label}</p>
        <p className="mt-1 text-2xl font-semibold tabular-nums">{value}</p>
        <p className="mt-1 text-xs text-muted-foreground">{detail}</p>
      </CardContent>
    </Card>
  )
}

function PolicyRow({ policy, busy, onToggle }: {
  policy: JinaFallbackPolicy
  busy: boolean
  onToggle: (policy: JinaFallbackPolicy) => void
}) {
  return (
    <tr className="border-b last:border-0">
      <td className="px-4 py-3">
        <strong className="block font-medium">{policy.domain}</strong>
        <span className="text-xs text-muted-foreground">
          {policy.autoDiscovered ? '抓取失败后自动发现' : '管理员确认'} · 最近 {formatDate(policy.lastSeenAt)}
        </span>
      </td>
      <td className="px-4 py-3"><Badge variant={policy.enabled ? 'green' : 'gray'}>{policy.enabled ? '已启用' : '待确认'}</Badge></td>
      <td className="px-4 py-3 text-sm tabular-nums">{policy.failureCount}</td>
      <td className="px-4 py-3"><FailureCodes values={policy.lastFailureCodes} /></td>
      <td className="px-4 py-3 text-right">
        <Button size="sm" variant={policy.enabled ? 'outline' : 'default'} disabled={busy} onClick={() => onToggle(policy)}>
          {policy.enabled ? '停用 Jina' : '启用 Jina'}
        </Button>
      </td>
    </tr>
  )
}

function BodyReviewQueue() {
  const query = useQuery({
    queryKey: ['articleFetchAdmin', 'bodyReviews'],
    queryFn: ({ signal }) => fetchArticleBodyReviews(signal),
    staleTime: 30_000, retry: false,
  })
  return <Card>
    <CardHeader>
      <CardTitle>无法比较版本的正文复核</CardTitle>
      <CardDescription>
        来源没有可靠版本证据且正文发生变化时，保留现有有效正文并记录待复核状态；
        不自动覆盖全文、不向未经授权的站点请求正文。
      </CardDescription>
    </CardHeader>
    <CardContent className="space-y-3">
      <Button type="button" size="sm" variant="outline" disabled={query.isFetching}
        onClick={() => void query.refetch()}>刷新复核记录</Button>
      {query.isPending && <p role="status">正在读取复核记录…</p>}
      {query.isError && <p role="alert" className="text-destructive">复核记录读取失败，请重试。</p>}
      {query.data?.truncated && <p role="status" className="text-sm text-amber-700">
        仅显示最近 100 项，请先处理较新的记录。
      </p>}
      {query.data && !query.data.results.length && <p className="text-sm text-muted-foreground">
        暂无有待核对的正文版本记录。
      </p>}
      {query.data?.results.length ? <div className="workspace-scroll max-h-96 overflow-auto rounded-lg border">
        <table className="w-full min-w-[700px] text-left text-sm">
          <thead className="sticky top-0 bg-muted"><tr>
            <th className="px-3 py-2">文章</th><th className="px-3 py-2">来源</th>
            <th className="px-3 py-2">状态</th><th className="px-3 py-2">发现时间</th>
          </tr></thead>
          <tbody>{query.data.results.map((item) => <tr key={item.sourceKey + ':' + item.newsId} className="border-t">
            <td className="px-3 py-2"><Link to={'/news/' + item.newsId}
              className="text-primary underline">{item.title}</Link></td>
            <td className="px-3 py-2">{item.sourceKey}</td>
            <td className="px-3 py-2">{item.status === 'reviewed' ? '新版本已确认' : '待人工核对'}
              <p className="text-xs text-muted-foreground">
                版本 {item.baseRevision} → {item.currentRevision} · {item.queueResult || '—'}
              </p></td>
            <td className="px-3 py-2 text-muted-foreground">{formatDate(item.detectedAt)}</td>
          </tr>)}</tbody>
        </table>
      </div> : null}
    </CardContent>
  </Card>
}

export default function ArticleFetchMonitorSection() {
  const queryClient = useQueryClient()
  const dashboard = useQuery(articleFetchDashboardOptions())
  const [domain, setDomain] = useState('')
  const [actionError, setActionError] = useState('')
  const refresh = async () => {
    setActionError('')
    await queryClient.invalidateQueries({ queryKey: articleFetchAdminKeys.all })
  }
  const policyMutation = useMutation({
    mutationFn: ({ policyDomain, enabled }: { policyDomain: string; enabled: boolean }) => updateJinaPolicy(policyDomain, enabled),
    onSuccess: refresh,
    onError: (error) => setActionError(error instanceof Error ? error.message : '更新 Jina 策略失败。'),
  })
  const createMutation = useMutation({
    mutationFn: createJinaPolicy,
    onSuccess: async () => {
      setDomain('')
      await refresh()
    },
    onError: (error) => setActionError(error instanceof Error ? error.message : '添加候选域名失败。'),
  })
  const busy = policyMutation.isPending || createMutation.isPending

  if (dashboard.isLoading) {
    return <section id="article-fetch" className="mt-10 h-64 animate-pulse scroll-mt-20 rounded-xl bg-muted" aria-label="正在加载全文抓取监控" />
  }
  if (dashboard.isError || !dashboard.data) {
    return (
      <section id="article-fetch" className="mt-10 scroll-mt-20">
        <Card><CardHeader><CardTitle>全文抓取监控不可用</CardTitle><CardDescription>{dashboard.error instanceof Error ? dashboard.error.message : '无法读取监控数据。'}</CardDescription></CardHeader><CardContent><Button onClick={() => void dashboard.refetch()}><RefreshCw aria-hidden="true" />重试</Button></CardContent></Card>
      </section>
    )
  }

  const data = dashboard.data
  const successRate = `${(data.summary.successRate * 100).toFixed(1)}%`
  const togglePolicy = (policy: JinaFallbackPolicy) => {
    if (!policy.enabled && !window.confirm(
      `确认允许 ${policy.domain} 使用 Jina 回退？\n\n该域名的公开文章路径和正文会由第三方 Jina Reader 处理；查询参数、登录信息和其他域名不会发送。`,
    )) return
    policyMutation.mutate({ policyDomain: policy.domain, enabled: !policy.enabled })
  }
  const submitDomain = () => {
    const value = domain.trim()
    if (!value) return
    setActionError('')
    createMutation.mutate(value)
  }

  return (
    <section id="article-fetch" className="mt-10 scroll-mt-20 space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="flex items-center gap-2 text-xl font-semibold"><ShieldCheck aria-hidden="true" />全文抓取监控</h2>
          <p className="mt-1 text-sm text-muted-foreground">每 10 秒刷新。仅记录脱敏错误码，不保存 URL 查询参数、正文、Cookie 或密钥。</p>
        </div>
        <Button variant="outline" disabled={dashboard.isFetching || busy} onClick={() => void dashboard.refetch()}>
          <RefreshCw aria-hidden="true" className={dashboard.isFetching ? 'animate-spin' : ''} />刷新
        </Button>
      </div>

      {actionError ? <div role="alert" className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800 dark:border-red-900/60 dark:bg-red-950/35 dark:text-red-200"><AlertCircle aria-hidden="true" className="mt-0.5 size-4 shrink-0" />{actionError}</div> : null}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Metric label="实际请求提交率" value={successRate} detail="仅统计已发出请求且可评估的尝试" />
        <Metric label="正文已提交" value={data.summary.success} detail="验证通过并经数据库 CAS 提交" />
        <Metric label="失败" value={data.summary.failed} detail="Provider 链全部失败" />
        <Metric label="待补全文" value={data.summary.unresolvedArticles} detail="当前数据库未解决记录" />
      </div>

      <BodyReviewQueue />

      <Card>
        <CardHeader>
          <CardTitle>Jina 精确域名策略</CardTitle>
          <CardDescription>未知失败域名只会自动加入“待确认”，不会自动向 Jina 发送文章。策略修改即时生效，无需重启。</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <form className="flex flex-col gap-2 sm:flex-row" onSubmit={(event) => { event.preventDefault(); submitDomain() }}>
            <label className="sr-only" htmlFor="jina-policy-domain">新增候选域名</label>
            <Input id="jina-policy-domain" placeholder="news.example.com（不含协议和路径）" value={domain} onChange={(event) => setDomain(event.target.value)} autoComplete="off" />
            <Button type="submit" variant="outline" disabled={busy || !domain.trim()}><Plus aria-hidden="true" />添加为待确认</Button>
          </form>
          <div className="workspace-scroll overflow-x-auto rounded-lg border">
            <table className="w-full min-w-[900px] text-left">
              <thead className="bg-muted/60 text-xs text-muted-foreground"><tr><th className="px-4 py-3">域名</th><th className="px-4 py-3">策略</th><th className="px-4 py-3">回退触发</th><th className="px-4 py-3">最近失败</th><th className="px-4 py-3 text-right">操作</th></tr></thead>
              <tbody>{data.policies.length ? data.policies.map((policy) => <PolicyRow key={policy.domain} policy={policy} busy={busy} onToggle={togglePolicy} />) : <tr><td className="px-4 py-8 text-center text-sm text-muted-foreground" colSpan={5}>暂无候选域名。</td></tr>}</tbody>
            </table>
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader><CardTitle>高频失败码</CardTitle><CardDescription>最近最多分析 5,000 条事件，监控数据保留 {data.retentionDays} 天。</CardDescription></CardHeader>
          <CardContent className="space-y-2">
            {data.topFailureCodes.length ? data.topFailureCodes.slice(0, 12).map((item) => <div key={item.code} className="flex items-center justify-between gap-3 rounded-md bg-muted/60 px-3 py-2 text-sm"><code>{item.code}</code><strong className="tabular-nums">{item.count}</strong></div>) : <p className="text-sm text-muted-foreground">当前时间窗口内没有失败事件。</p>}
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>失败域名</CardTitle><CardDescription>按失败次数排序，便于判断是否需要启用回退。</CardDescription></CardHeader>
          <CardContent className="space-y-2">
            {data.domains.filter((item) => item.failed > 0).slice(0, 12).map((item) => <div key={item.domain} className="grid grid-cols-[1fr_auto_auto] items-center gap-3 rounded-md bg-muted/60 px-3 py-2 text-sm"><span className="truncate font-medium">{item.domain}</span><span className="text-red-700">失败 {item.failed}</span><span className="text-emerald-700">成功 {item.succeeded}</span></div>)}
            {!data.domains.some((item) => item.failed > 0) ? <p className="text-sm text-muted-foreground">当前时间窗口内没有失败域名。</p> : null}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader><CardTitle>最近抓取事件</CardTitle><CardDescription>分别显示候选验证、正文提交与实际 HTTP 请求。历史成功不代表按新规则提交。</CardDescription></CardHeader>
        <CardContent>
          <div className="workspace-scroll overflow-x-auto rounded-lg border">
            <table className="w-full min-w-[920px] text-left">
              <thead className="bg-muted/60 text-xs text-muted-foreground"><tr><th className="px-4 py-3">时间 / 文章</th><th className="px-4 py-3">域名</th><th className="px-4 py-3">结果</th><th className="px-4 py-3">Provider / 错误码</th><th className="px-4 py-3 text-right">耗时</th></tr></thead>
              <tbody>{data.recentEvents.length ? data.recentEvents.map((event) => (
                <tr key={event.id} className="border-b last:border-0">
                  <td className="px-4 py-3 text-sm"><span className="block text-muted-foreground">{formatDate(event.createdAt)}</span>{event.newsId ? <Link className="inline-flex items-center gap-1 font-medium text-orange-700 hover:underline" to={`/news/${event.newsId}`}>新闻 #{event.newsId}<ExternalLink aria-hidden="true" className="size-3" /></Link> : '—'}</td>
                  <td className="px-4 py-3 text-sm font-medium">{event.domain}</td>
                  <td className="px-4 py-3"><Badge variant={event.persistenceOutcome === 'committed' ? 'green' : event.outcome === 'failed' ? 'red' : 'gray'}>{event.persistenceOutcome === 'committed' ? '正文已提交' : event.persistenceOutcome === 'noop' ? '正文未变' : event.persistenceOutcome === 'persistence_conflict' ? '提交冲突' : event.outcome === 'validated' ? '验证通过，未提交' : event.outcome === 'legacy_validated' ? '诊断验证通过' : event.outcome === 'success' ? '历史成功，提交未知' : event.logicalOutcome === 'budget_deferred' ? '预算延期' : '失败'}</Badge><span className="mt-1 block text-xs text-muted-foreground">HTTP {(event.httpStatuses || []).join(', ') || '—'} · {event.physicalRequests || 0} 次请求{event.retryAfterAt ? ` · 冷却至 ${formatDate(event.retryAfterAt)}` : ''}</span></td>
                  <td className="px-4 py-3 text-sm"><span className="mb-1 block font-medium">{event.provider || '—'}</span><FailureCodes values={event.failureCodes} /></td>
                  <td className="px-4 py-3 text-right text-sm tabular-nums">{event.elapsedMs.toLocaleString()} ms</td>
                </tr>
              )) : <tr><td className="px-4 py-8 text-center text-sm text-muted-foreground" colSpan={5}>部署后尚无全文抓取事件。</td></tr>}</tbody>
            </table>
          </div>
        </CardContent>
      </Card>
    </section>
  )
}
