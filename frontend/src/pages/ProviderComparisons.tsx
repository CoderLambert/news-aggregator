import { useRef, useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Activity, AlertCircle, CheckCircle2, Clock, FileText, Gauge, Globe2, Loader2, RefreshCw, Send, Square } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { useAuth } from '@/context/AuthContext'
import { useLanguage } from '@/context/useLanguage'
import MarkdownContent from '@/components/news-detail/MarkdownContent'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  createProviderComparison,
  providerComparisonsOptions,
  providerComparisonKeys,
  retestProviderComparison,
} from '@/services/providerComparisonsQueries'
import type { ProviderComparisonInput } from '@/services/providerComparisonsQueries'
import { isRecord } from '@/types/news'

type JsonRecord = Record<string, unknown>

interface ProviderResult {
  id: number | null
  provider: string
  status: string
  ok: boolean | null
  durationMs: unknown
  qualityScore: unknown
  contentLength: unknown
  markdown: string
  error: string
}

interface ComparisonRecord {
  id: string | number
  runId: string
  newsId: string | number | null
  title: string
  url: string
  siteName: string
  createdAt: string
  providers: ProviderResult[]
}

interface AdaptedSite {
  name: string
  domain: string
  domains: string[]
  provider: string
  status: string
}

const metricCards: Array<{ label: string; icon: LucideIcon; keys: string[]; formatter: (value: unknown) => string }> = [
  { label: '总对比数', icon: Activity, keys: ['total', 'total_comparisons'], formatter: formatNumber },
  { label: '成功率', icon: CheckCircle2, keys: ['success_rate', 'successRate'], formatter: formatPercent },
  { label: '平均质量分', icon: Gauge, keys: ['avg_quality_score', 'average_quality_score', 'quality_score'], formatter: formatNumber },
  { label: '平均耗时', icon: Clock, keys: ['avg_duration_ms', 'average_duration_ms', 'duration_ms'], formatter: formatDuration },
]

function stringValue(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

function displayValue(value: unknown): string {
  return typeof value === 'string' || typeof value === 'number' ? String(value) : ''
}

function numberValue(value: unknown): number | null {
  const numeric = Number(value)
  return Number.isFinite(numeric) ? numeric : null
}

function formatPercent(value: unknown): string {
  if (value == null || value === '') return '—'
  const numeric = numberValue(value)
  if (numeric === null) return String(value)
  return `${Math.round(numeric > 1 ? numeric : numeric * 100)}%`
}

function formatNumber(value: unknown): string {
  if (value == null || value === '') return '—'
  const numeric = numberValue(value)
  return numeric === null ? '—' : numeric.toLocaleString()
}

function formatDuration(value: unknown): string {
  if (value == null || value === '') return '—'
  const numeric = numberValue(value)
  if (numeric === null) return '—'
  if (numeric >= 1000) return `${(numeric / 1000).toFixed(numeric % 1000 === 0 ? 0 : 1)}s`
  return `${Math.round(numeric)}ms`
}

function metricValue(metrics: JsonRecord, keys: string[]): unknown {
  for (const key of keys) {
    if (metrics[key] != null) return metrics[key]
  }
  return null
}

function toProvider(row: JsonRecord): ProviderResult {
  const ok = typeof row.ok === 'boolean' ? row.ok : null
  const provider = stringValue(row.provider) || stringValue(row.name) || stringValue(row.type) || 'provider'
  return {
    id: typeof row.id === 'number' ? row.id : null,
    provider,
    status: stringValue(row.status) || (ok === true ? 'success' : ok === false ? 'failed' : stringValue(row.error) ? 'failed' : 'unknown'),
    ok,
    durationMs: row.duration_ms ?? row.elapsed_ms,
    qualityScore: row.quality_score ?? row.score,
    contentLength: row.content_length ?? row.length,
    markdown: stringValue(row.markdown) || stringValue(row.markdown_preview),
    error: stringValue(row.error),
  }
}

function comparisonId(value: unknown, fallback: string | number): string | number {
  return typeof value === 'number' || typeof value === 'string' ? value : fallback
}

function normalizeProviders(record: JsonRecord): ProviderResult[] {
  const grouped = Array.isArray(record.providers)
    ? record.providers
    : Array.isArray(record.provider_results)
      ? record.provider_results
      : null
  if (grouped) return grouped.filter(isRecord).map(toProvider)
  return ['jina', 'scrapy', 'other']
    .map((key) => record[key] ?? record[`${key}_result`])
    .filter(isRecord)
    .map(toProvider)
}

function groupedRecord(row: JsonRecord, providers: ProviderResult[], fallback: string | number): ComparisonRecord {
  const id = comparisonId(row.id, fallback)
  const runId = stringValue(row.run_id)
  const url = stringValue(row.url)
  return {
    id,
    runId,
    newsId: typeof row.news_id === 'number' || typeof row.news_id === 'string'
      ? row.news_id
      : typeof row.news === 'number' || typeof row.news === 'string' ? row.news : null,
    title: stringValue(row.title) || stringValue(row.news_title) || stringValue(row.expected_title) || url,
    url,
    siteName: stringValue(row.site_name) || stringValue(row.source_name),
    createdAt: stringValue(row.created_at),
    providers,
  }
}

function groupComparisonRows(rows: JsonRecord[]): ComparisonRecord[] {
  const groups = new Map<string, ComparisonRecord>()
  rows.forEach((row, index) => {
    const providers = normalizeProviders(row)
    if (Array.isArray(row.providers) || Array.isArray(row.provider_results)) {
      const grouped = groupedRecord(row, providers, `record-${index}`)
      groups.set(grouped.runId || String(grouped.id), grouped)
      return
    }

    const provider = toProvider(row)
    const id = comparisonId(row.id, `row-${index}`)
    const key = stringValue(row.run_id) || String(row.id ?? `${stringValue(row.url)}-${stringValue(row.created_at)}-${provider.provider}`)
    const existing = groups.get(key)
    if (existing) {
      existing.providers.push(provider)
      if (!existing.title) existing.title = stringValue(row.news_title) || stringValue(row.title) || existing.url
      return
    }
    groups.set(key, groupedRecord(row, [provider], id))
  })
  return Array.from(groups.values())
}

function adaptedSite(value: JsonRecord): AdaptedSite {
  return {
    name: stringValue(value.name) || stringValue(value.site_name) || stringValue(value.domain),
    domain: stringValue(value.domain) || stringValue(value.url),
    domains: Array.isArray(value.domains) ? value.domains.filter((domain): domain is string => typeof domain === 'string') : [],
    provider: stringValue(value.provider) || 'scrapy',
    status: stringValue(value.status),
  }
}

function errorMessage(error: unknown, fallback: string): string {
  if (!isRecord(error)) return error instanceof Error ? error.message || fallback : fallback
  const response = isRecord(error.response) ? error.response : null
  const data = response && isRecord(response.data) ? response.data : null
  if (typeof response?.data === 'string') return response.data
  if (typeof data?.detail === 'string') return data.detail
  if (typeof data?.error === 'string') return data.error
  if (data) {
    return Object.entries(data)
      .map(([key, value]) => `${key}: ${Array.isArray(value) ? value.map(displayValue).join(', ') : displayValue(value) || JSON.stringify(value)}`)
      .join('; ')
  }
  return typeof error.message === 'string' ? error.message : fallback
}

function statusClass(status: string): string {
  const normalized = status.toLowerCase()
  if (['success', 'ok', 'completed'].includes(normalized)) return 'bg-emerald-50 text-emerald-700 border-emerald-200'
  if (['failed', 'error'].includes(normalized)) return 'bg-red-50 text-red-700 border-red-200'
  if (['running', 'queued', 'pending'].includes(normalized)) return 'bg-amber-50 text-amber-700 border-amber-200'
  return 'bg-gray-50 text-gray-600 border-gray-200'
}

export default function ProviderComparisons() {
  const queryClient = useQueryClient()
  const { lang } = useLanguage()
  const { user } = useAuth()
  const viewerId = user?.id ?? 'anonymous'
  const comparisonsQuery = useQuery(providerComparisonsOptions(lang, viewerId))
  const [newsId, setNewsId] = useState('')
  const [url, setUrl] = useState('')
  const [actionError, setActionError] = useState('')
  const [pendingRetests, setPendingRetests] = useState<Set<number>>(() => new Set())
  const [stoppingRetests, setStoppingRetests] = useState<Set<number>>(() => new Set())
  const pendingRetestsRef = useRef(new Map<number, AbortController>())
  const submitLockRef = useRef(false)

  const refreshComparisons = async () => {
    setActionError('')
    return comparisonsQuery.refetch()
  }

  const createMutation = useMutation({
    mutationFn: ({ payload, signal }: { payload: ProviderComparisonInput; signal: AbortSignal }) =>
      createProviderComparison(payload, signal),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: providerComparisonKeys.lists() }),
  })
  const retestMutation = useMutation({
    mutationFn: ({ id, signal }: { id: number; signal: AbortSignal }) => retestProviderComparison(id, signal),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: providerComparisonKeys.lists() }),
  })

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (submitLockRef.current) return
    const trimmedNewsId = newsId.trim()
    const trimmedUrl = url.trim()
    if (!trimmedNewsId && !trimmedUrl) {
      setActionError('请输入 news_id 或 url')
      return
    }
    if (trimmedNewsId && trimmedUrl) {
      setActionError('请仅填写 news_id 或 url 之一')
      return
    }

    const payload: ProviderComparisonInput = trimmedNewsId ? { news_id: trimmedNewsId } : { url: trimmedUrl }
    submitLockRef.current = true
    setActionError('')
    try {
      await createMutation.mutateAsync({ payload, signal: new AbortController().signal })
      setNewsId('')
      setUrl('')
    } catch (error) {
      setActionError(errorMessage(error, '发起对比失败'))
    } finally {
      submitLockRef.current = false
    }
  }

  async function handleRetest(id: number) {
    if (pendingRetestsRef.current.has(id)) return
    const controller = new AbortController()
    pendingRetestsRef.current.set(id, controller)
    setPendingRetests((current) => new Set(current).add(id))
    setStoppingRetests((current) => {
      const next = new Set(current)
      next.delete(id)
      return next
    })
    setActionError('')
    try {
      await retestMutation.mutateAsync({ id, signal: controller.signal })
    } catch (error) {
      if (!controller.signal.aborted) setActionError(errorMessage(error, '重新测试失败'))
    } finally {
      if (pendingRetestsRef.current.get(id) === controller) pendingRetestsRef.current.delete(id)
      setPendingRetests((current) => {
        const next = new Set(current)
        next.delete(id)
        return next
      })
      setStoppingRetests((current) => {
        const next = new Set(current)
        next.delete(id)
        return next
      })
    }
  }

  function cancelRetest(id: number) {
    const controller = pendingRetestsRef.current.get(id)
    if (!controller || controller.signal.aborted) return
    setStoppingRetests((current) => new Set(current).add(id))
    controller.abort()
  }

  const payload = comparisonsQuery.data
  const records = payload ? groupComparisonRows(payload.results) : []
  const sites = payload?.adapted_sites.map(adaptedSite) ?? []
  const metrics = metricCards.map((card) => ({
    ...card,
    value: card.formatter(metricValue(payload?.metrics ?? {}, card.keys) ?? (card.label === '总对比数' ? payload?.count ?? 0 : null)),
  }))
  const loading = comparisonsQuery.isPending
  const isRefreshing = comparisonsQuery.isFetching
  const visibleError = actionError || (comparisonsQuery.error ? errorMessage(comparisonsQuery.error, '加载 Provider 对比失败') : '')

  return (
    <div className="max-w-6xl mx-auto px-4 py-6 sm:py-8 space-y-6 overflow-x-hidden">
      <section className="rounded-3xl bg-gradient-to-br from-gray-950 via-slate-900 to-indigo-950 text-white p-5 sm:p-8 shadow-xl overflow-hidden">
        <div className="flex flex-col md:flex-row md:items-end md:justify-between gap-5">
          <div className="min-w-0">
            <p className="text-sm text-indigo-200 font-medium mb-2">Scrapy / Jina / Other Providers</p>
            <h1 className="text-2xl sm:text-4xl font-bold tracking-tight">Provider 对比</h1>
            <p className="mt-3 text-sm sm:text-base text-gray-300 max-w-2xl">
              查看已适配站点的爬取质量、耗时、错误和 Markdown 预览，快速对比 Scrapy 与其他 provider 的表现。
            </p>
          </div>
          <Button
            type="button"
            variant="outline"
            onClick={() => void refreshComparisons()}
            className="bg-white/10 border-white/20 text-white hover:bg-white/20 w-full md:w-auto"
            disabled={isRefreshing}
          >
            {isRefreshing ? <Loader2 className="size-4 animate-spin" /> : <RefreshCw className="size-4" />}
            刷新
          </Button>
        </div>
      </section>

      <form onSubmit={(event) => void handleSubmit(event)} className="bg-white rounded-2xl border border-gray-200 shadow-sm p-4 sm:p-5">
        <div className="grid grid-cols-1 md:grid-cols-[1fr_2fr_auto] gap-3 items-end">
          <label className="space-y-1.5 min-w-0">
            <span className="text-sm font-medium text-gray-700">news_id</span>
            <Input value={newsId} onChange={(event) => setNewsId(event.target.value)} placeholder="例如 42" aria-label="news_id" />
          </label>
          <label className="space-y-1.5 min-w-0">
            <span className="text-sm font-medium text-gray-700">url</span>
            <Input value={url} onChange={(event) => setUrl(event.target.value)} placeholder="https://..." aria-label="url" className="break-all" />
          </label>
          <Button type="submit" className="w-full md:w-auto bg-gray-900 text-white hover:bg-gray-800" disabled={createMutation.isPending}>
            {createMutation.isPending ? <Loader2 className="size-4 animate-spin" /> : <Send className="size-4" />}
            发起对比
          </Button>
        </div>
        <p className="mt-2 text-xs text-gray-500">请仅填写 news_id 或 url 之一；URL 模式仅允许已适配站点。</p>
        <p className="mt-1 text-xs text-gray-400">新建操作由后端一次运行并保存所有 provider 结果；单列重测可分别停止浏览器等待，服务器可能继续处理。</p>
      </form>

      {visibleError && (
        <div role="alert" className="flex items-start gap-2 rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          <AlertCircle className="size-4 mt-0.5 shrink-0" />
          <span className="break-words">{visibleError}</span>
        </div>
      )}

      <section className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        {metrics.map((item) => (
          <Card key={item.label} className="py-4 gap-2">
            <CardContent className="px-4 flex items-center gap-3">
              <div className="size-10 rounded-2xl bg-indigo-50 text-indigo-600 flex items-center justify-center shrink-0">
                <item.icon className="size-5" />
              </div>
              <div>
                <p className="text-xs text-gray-500">{item.label}</p>
                <p className="text-xl font-semibold text-gray-900">{item.value}</p>
              </div>
            </CardContent>
          </Card>
        ))}
      </section>

      <section className="bg-white rounded-2xl border border-gray-200 shadow-sm p-4 sm:p-5">
        <div className="flex items-center gap-2 mb-4">
          <Globe2 className="size-5 text-indigo-500" />
          <h2 className="text-lg font-semibold text-gray-900">已适配站点</h2>
        </div>
        {sites.length ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {sites.map((site, index) => (
              <div key={`${site.domain || site.name || index}`} className="rounded-xl border border-gray-100 bg-gray-50 p-3 min-w-0">
                <div className="font-medium text-gray-900 break-words">{site.name}</div>
                <div className="text-sm text-gray-500 break-all">{site.domains.length ? site.domains.join(', ') : (site.domain || '—')}</div>
                <div className="mt-2 flex flex-wrap gap-2 text-xs">
                  <span className="rounded-full bg-white px-2 py-1 text-gray-600 border border-gray-200">{site.provider}</span>
                  {site.status && <span className="rounded-full bg-emerald-50 px-2 py-1 text-emerald-700 border border-emerald-100">{site.status}</span>}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-sm text-gray-500">暂无已适配站点数据。</p>
        )}
      </section>

      <section className="space-y-4">
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-lg font-semibold text-gray-900">Provider 对比记录</h2>
          <span className="text-sm text-gray-500">共 {formatNumber(payload?.count ?? records.length)} 条</span>
        </div>

        {loading ? (
          <div className="rounded-2xl border border-gray-200 bg-white p-8 text-center text-gray-500">
            <Loader2 className="size-6 animate-spin mx-auto mb-2" />
            加载中...
          </div>
        ) : records.length ? (
          records.map((record) => (
            <ComparisonRecord
              key={record.runId || record.id}
              record={record}
              pendingRetests={pendingRetests}
              stoppingRetests={stoppingRetests}
              onRetest={(id) => void handleRetest(id)}
              onCancel={cancelRetest}
            />
          ))
        ) : (
          <div className="rounded-2xl border border-dashed border-gray-300 bg-white p-8 text-center text-gray-500">
            暂无 Provider 对比记录，请输入 news_id 或 url 发起一次对比。
          </div>
        )}
      </section>
    </div>
  )
}

interface ComparisonRecordProps {
  record: ComparisonRecord
  pendingRetests: ReadonlySet<number>
  stoppingRetests: ReadonlySet<number>
  onRetest: (id: number) => void
  onCancel: (id: number) => void
}

function ComparisonRecord({ record, pendingRetests, stoppingRetests, onRetest, onCancel }: ComparisonRecordProps) {
  const title = record.title || record.url || `对比记录 #${record.id}`

  return (
    <Card className="overflow-hidden py-0 gap-0">
      <CardHeader className="p-4 sm:p-5 border-b border-gray-100 gap-3">
        <div className="min-w-0">
          <CardTitle className="text-base sm:text-lg text-gray-900 break-words">{title}</CardTitle>
          <div className="mt-2 flex flex-col sm:flex-row sm:flex-wrap gap-1.5 sm:gap-3 text-xs sm:text-sm text-gray-500">
            {record.newsId != null && <span>news_id: {record.newsId}</span>}
            {record.siteName && <span>{record.siteName}</span>}
            {record.createdAt && <time dateTime={record.createdAt}>{new Date(record.createdAt).toLocaleString()}</time>}
          </div>
          {record.url && <p className="mt-2 text-xs text-blue-600 break-all">{record.url}</p>}
        </div>
      </CardHeader>

      <CardContent className="p-4 sm:p-5">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {record.providers.map((provider, index) => (
            <ProviderResult
              key={`${provider.provider}-${provider.id ?? index}`}
              provider={provider}
              pending={provider.id != null && pendingRetests.has(provider.id)}
              stopping={provider.id != null && stoppingRetests.has(provider.id)}
              onRetest={onRetest}
              onCancel={onCancel}
            />
          ))}
        </div>
      </CardContent>
    </Card>
  )
}

interface ProviderResultProps {
  provider: ProviderResult
  pending: boolean
  stopping: boolean
  onRetest: (id: number) => void
  onCancel: (id: number) => void
}

function ProviderResult({ provider, pending, stopping, onRetest, onCancel }: ProviderResultProps) {
  const status = provider.status
  const name = provider.provider.toUpperCase()

  return (
    <article className="rounded-2xl border border-gray-200 bg-gray-50/70 p-4 min-w-0 overflow-hidden">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 mb-3">
        <div className="flex items-center gap-2 min-w-0">
          <FileText className="size-4 text-gray-500 shrink-0" />
          <h3 className="font-semibold text-gray-900 break-words">{name}</h3>
        </div>
        <span className={`inline-flex w-fit rounded-full border px-2.5 py-1 text-xs font-medium ${statusClass(status)}`}>
          {status}
        </span>
        {provider.id != null && (
          <div className="flex w-full sm:w-auto shrink-0 gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => onRetest(provider.id as number)}
              className="w-full sm:w-auto bg-white/80 backdrop-blur-sm border border-gray-200"
              disabled={pending}
              aria-label={`重新测试 ${name}`}
            >
              {pending ? <Loader2 className="size-4 animate-spin" /> : <RefreshCw className="size-4" />}
              重新测试
            </Button>
            {pending && (
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => onCancel(provider.id as number)}
                disabled={stopping}
                aria-label={`停止等待 ${name} 重测`}
                title="关闭此浏览器请求；服务端可能继续处理"
              >
                {stopping ? <Loader2 className="size-4 animate-spin" /> : <Square className="size-4" />}
                停止等待
              </Button>
            )}
          </div>
        )}
      </div>

      <dl className="grid grid-cols-1 sm:grid-cols-3 gap-2 text-sm">
        <div className="rounded-xl bg-white p-2 border border-gray-100">
          <dt className="text-xs text-gray-500">质量分</dt>
          <dd className="font-medium text-gray-900">质量分 {formatNumber(provider.qualityScore)}</dd>
        </div>
        <div className="rounded-xl bg-white p-2 border border-gray-100">
          <dt className="text-xs text-gray-500">内容长度</dt>
          <dd className="font-medium text-gray-900">内容 {formatNumber(provider.contentLength)} 字</dd>
        </div>
        <div className="rounded-xl bg-white p-2 border border-gray-100">
          <dt className="text-xs text-gray-500">耗时</dt>
          <dd className="font-medium text-gray-900">耗时 {formatDuration(provider.durationMs)}</dd>
        </div>
      </dl>

      {provider.error && (
        <div className="mt-3 rounded-xl border border-red-100 bg-red-50 p-3 text-sm text-red-700 break-words overflow-hidden">
          {provider.error}
        </div>
      )}

      <div className="mt-3 rounded-xl bg-white border border-gray-100 p-3 max-h-80 overflow-auto">
        <p className="text-xs font-medium text-gray-500 mb-2">Markdown 预览</p>
        {provider.markdown ? <MarkdownContent content={provider.markdown} /> : <p className="text-sm text-gray-400">暂无 Markdown 内容</p>}
      </div>
    </article>
  )
}
