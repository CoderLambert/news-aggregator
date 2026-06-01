import { useEffect, useMemo, useState } from 'react'
import { Activity, AlertCircle, CheckCircle2, Clock, FileText, Gauge, Globe2, Loader2, RefreshCw, Send } from 'lucide-react'

import {
  createProviderComparison,
  fetchProviderComparisons,
  retestProviderComparison,
} from '../services/api'
import MarkdownContent from '../components/news-detail/MarkdownContent'
import { Button } from '../components/ui/button'
import { Input } from '../components/ui/input'
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card'

function formatPercent(value) {
  if (value == null || value === '') return '—'
  const n = Number(value)
  if (!Number.isFinite(n)) return String(value)
  return `${Math.round(n > 1 ? n : n * 100)}%`
}

function formatNumber(value) {
  const n = Number(value)
  return Number.isFinite(n) ? n.toLocaleString() : '—'
}

function formatDuration(ms) {
  const n = Number(ms)
  if (!Number.isFinite(n)) return '—'
  if (n >= 1000) return `${(n / 1000).toFixed(n % 1000 === 0 ? 0 : 1)}s`
  return `${Math.round(n)}ms`
}

function normalizeProviders(record) {
  if (Array.isArray(record.providers)) return record.providers
  if (Array.isArray(record.provider_results)) return record.provider_results
  return ['jina', 'scrapy', 'other']
    .map((key) => record[key] || record[`${key}_result`])
    .filter(Boolean)
}

function rowToProvider(row) {
  return {
    ...row,
    status: row.status || (row.ok === true ? 'success' : row.ok === false ? 'failed' : undefined),
    duration_ms: row.duration_ms ?? row.elapsed_ms,
  }
}

function groupComparisonRows(rows) {
  const groups = new Map()

  for (const row of rows || []) {
    if (Array.isArray(row.providers) || Array.isArray(row.provider_results)) {
      const key = row.run_id || row.id || `record-${groups.size}`
      groups.set(key, row)
      continue
    }

    const key = row.run_id || row.id || `${row.url}-${row.created_at || row.provider}`
    const existing = groups.get(key)
    if (existing) {
      existing.providers.push(rowToProvider(row))
      if (!existing.title && (row.news_title || row.title)) existing.title = row.news_title || row.title
      continue
    }

    groups.set(key, {
      id: row.id,
      retest_id: row.id,
      run_id: row.run_id,
      news_id: row.news ?? row.news_id,
      title: row.news_title || row.expected_title || row.title || row.url,
      url: row.url,
      site_name: row.source_name || row.site_name,
      created_at: row.created_at,
      providers: [rowToProvider(row)],
    })
  }

  return Array.from(groups.values())
}

function providerName(provider) {
  return String(provider.provider || provider.name || provider.type || 'provider').toUpperCase()
}

function providerStatus(provider) {
  return provider.status || (provider.error ? 'failed' : 'unknown')
}

function errorMessage(err, fallback) {
  const data = err?.response?.data
  if (typeof data === 'string') return data
  if (data?.detail) return data.detail
  if (data?.error) return data.error
  if (data && typeof data === 'object') {
    return Object.entries(data)
      .map(([key, value]) => `${key}: ${Array.isArray(value) ? value.join(', ') : value}`)
      .join('; ')
  }
  return err?.message || fallback
}

function metricValue(metrics, keys) {
  for (const key of keys) {
    if (metrics?.[key] != null) return metrics[key]
  }
  return null
}

function statusClass(status) {
  const normalized = String(status).toLowerCase()
  if (['success', 'ok', 'completed'].includes(normalized)) return 'bg-emerald-50 text-emerald-700 border-emerald-200'
  if (['failed', 'error'].includes(normalized)) return 'bg-red-50 text-red-700 border-red-200'
  if (['running', 'queued', 'pending'].includes(normalized)) return 'bg-amber-50 text-amber-700 border-amber-200'
  return 'bg-gray-50 text-gray-600 border-gray-200'
}

export default function ProviderComparisons() {
  const [data, setData] = useState({ results: [], adapted_sites: [], metrics: {} })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [newsId, setNewsId] = useState('')
  const [url, setUrl] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [retestingId, setRetestingId] = useState(null)

  const loadComparisons = async () => {
    setLoading(true)
    setError('')
    try {
      const payload = await fetchProviderComparisons({})
      setData({
        results: groupComparisonRows(payload.results || []),
        adapted_sites: payload.adapted_sites || [],
        metrics: payload.metrics || {},
        count: payload.count,
        next: payload.next,
        previous: payload.previous,
      })
    } catch (err) {
      setError(errorMessage(err, '加载 Provider 对比失败'))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadComparisons()
  }, [])

  const metrics = useMemo(() => {
    const m = data.metrics || {}
    return [
      { label: '总对比数', value: formatNumber(metricValue(m, ['total', 'total_comparisons']) ?? data.count ?? 0), icon: Activity },
      { label: '成功率', value: formatPercent(metricValue(m, ['success_rate', 'successRate'])), icon: CheckCircle2 },
      { label: '平均质量分', value: formatNumber(metricValue(m, ['avg_quality_score', 'average_quality_score', 'quality_score'])), icon: Gauge },
      { label: '平均耗时', value: formatDuration(metricValue(m, ['avg_duration_ms', 'average_duration_ms', 'duration_ms'])), icon: Clock },
    ]
  }, [data])

  const handleSubmit = async (event) => {
    event.preventDefault()
    const trimmedNewsId = newsId.trim()
    const trimmedUrl = url.trim()
    if (!trimmedNewsId && !trimmedUrl) {
      setError('请输入 news_id 或 url')
      return
    }
    if (trimmedNewsId && trimmedUrl) {
      setError('请仅填写 news_id 或 url 之一')
      return
    }

    const payload = trimmedNewsId ? { news_id: trimmedNewsId } : { url: trimmedUrl }
    setSubmitting(true)
    setError('')
    try {
      await createProviderComparison(payload)
      setNewsId('')
      setUrl('')
      await loadComparisons()
    } catch (err) {
      setError(errorMessage(err, '发起对比失败'))
    } finally {
      setSubmitting(false)
    }
  }

  const handleRetest = async (comparisonId) => {
    setRetestingId(comparisonId)
    setError('')
    try {
      await retestProviderComparison(comparisonId)
      await loadComparisons()
    } catch (err) {
      setError(errorMessage(err, '重新测试失败'))
    } finally {
      setRetestingId(null)
    }
  }

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
            onClick={loadComparisons}
            className="bg-white/10 border-white/20 text-white hover:bg-white/20 w-full md:w-auto"
            disabled={loading}
          >
            {loading ? <Loader2 className="size-4 animate-spin" /> : <RefreshCw className="size-4" />}
            刷新
          </Button>
        </div>
      </section>

      <form onSubmit={handleSubmit} className="bg-white rounded-2xl border border-gray-200 shadow-sm p-4 sm:p-5">
        <div className="grid grid-cols-1 md:grid-cols-[1fr_2fr_auto] gap-3 items-end">
          <label className="space-y-1.5 min-w-0">
            <span className="text-sm font-medium text-gray-700">news_id</span>
            <Input value={newsId} onChange={(e) => setNewsId(e.target.value)} placeholder="例如 42" aria-label="news_id" />
          </label>
          <label className="space-y-1.5 min-w-0">
            <span className="text-sm font-medium text-gray-700">url</span>
            <Input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://..." aria-label="url" className="break-all" />
          </label>
          <Button type="submit" className="w-full md:w-auto bg-gray-900 text-white hover:bg-gray-800" disabled={submitting}>
            {submitting ? <Loader2 className="size-4 animate-spin" /> : <Send className="size-4" />}
            发起对比
          </Button>
        </div>
        <p className="mt-2 text-xs text-gray-500">请仅填写 news_id 或 url 之一；URL 模式仅允许已适配站点。</p>
      </form>

      {error && (
        <div role="alert" className="flex items-start gap-2 rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          <AlertCircle className="size-4 mt-0.5 shrink-0" />
          <span className="break-words">{error}</span>
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
        {data.adapted_sites.length ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {data.adapted_sites.map((site, index) => (
              <div key={`${site.domain || site.name || index}`} className="rounded-xl border border-gray-100 bg-gray-50 p-3 min-w-0">
                <div className="font-medium text-gray-900 break-words">{site.name || site.site_name || site.domain}</div>
                <div className="text-sm text-gray-500 break-all">{Array.isArray(site.domains) ? site.domains.join(', ') : (site.domain || site.url || '—')}</div>
                <div className="mt-2 flex flex-wrap gap-2 text-xs">
                  <span className="rounded-full bg-white px-2 py-1 text-gray-600 border border-gray-200">{site.provider || 'scrapy'}</span>
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
          <span className="text-sm text-gray-500">共 {formatNumber(data.count ?? data.results.length)} 条</span>
        </div>

        {loading ? (
          <div className="rounded-2xl border border-gray-200 bg-white p-8 text-center text-gray-500">
            <Loader2 className="size-6 animate-spin mx-auto mb-2" />
            加载中...
          </div>
        ) : data.results.length ? (
          data.results.map((record) => (
            <ComparisonRecord key={record.run_id || record.id} record={record} retestingId={retestingId} onRetest={handleRetest} />
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

function ComparisonRecord({ record, retestingId, onRetest }) {
  const providers = normalizeProviders(record)
  const title = record.title || record.url || `对比记录 #${record.id}`

  return (
    <Card className="overflow-hidden py-0 gap-0">
      <CardHeader className="p-4 sm:p-5 border-b border-gray-100 gap-3">
        <div className="min-w-0">
          <CardTitle className="text-base sm:text-lg text-gray-900 break-words">{title}</CardTitle>
          <div className="mt-2 flex flex-col sm:flex-row sm:flex-wrap gap-1.5 sm:gap-3 text-xs sm:text-sm text-gray-500">
            {record.news_id != null && <span>news_id: {record.news_id}</span>}
            {record.site_name && <span>{record.site_name}</span>}
            {record.created_at && <span>{new Date(record.created_at).toLocaleString()}</span>}
          </div>
          {record.url && <p className="mt-2 text-xs text-blue-600 break-all">{record.url}</p>}
        </div>
      </CardHeader>

      <CardContent className="p-4 sm:p-5">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {providers.map((provider, index) => (
            <ProviderResult
              key={`${provider.provider || provider.name || index}`}
              provider={provider}
              retesting={retestingId === provider.id}
              onRetest={onRetest}
            />
          ))}
        </div>
      </CardContent>
    </Card>
  )
}

function ProviderResult({ provider, retesting, onRetest }) {
  const markdown = provider.markdown || provider.markdown_preview || ''
  const status = providerStatus(provider)
  const name = providerName(provider)

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
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => onRetest(provider.id)}
            className="w-full sm:w-auto shrink-0 bg-white/80 backdrop-blur-sm border border-gray-200"
            disabled={retesting}
            aria-label={`重新测试 ${name}`}
          >
            {retesting ? <Loader2 className="size-4 animate-spin" /> : <RefreshCw className="size-4" />}
            重新测试
          </Button>
        )}
      </div>

      <dl className="grid grid-cols-1 sm:grid-cols-3 gap-2 text-sm">
        <div className="rounded-xl bg-white p-2 border border-gray-100">
          <dt className="text-xs text-gray-500">质量分</dt>
          <dd className="font-medium text-gray-900">质量分 {formatNumber(provider.quality_score ?? provider.score)}</dd>
        </div>
        <div className="rounded-xl bg-white p-2 border border-gray-100">
          <dt className="text-xs text-gray-500">内容长度</dt>
          <dd className="font-medium text-gray-900">内容 {formatNumber(provider.content_length ?? provider.length)} 字</dd>
        </div>
        <div className="rounded-xl bg-white p-2 border border-gray-100">
          <dt className="text-xs text-gray-500">耗时</dt>
          <dd className="font-medium text-gray-900">耗时 {formatDuration(provider.duration_ms ?? provider.elapsed_ms)}</dd>
        </div>
      </dl>

      {provider.error && (
        <div className="mt-3 rounded-xl border border-red-100 bg-red-50 p-3 text-sm text-red-700 break-words overflow-hidden">
          {provider.error}
        </div>
      )}

      <div className="mt-3 rounded-xl bg-white border border-gray-100 p-3 max-h-80 overflow-auto">
        <p className="text-xs font-medium text-gray-500 mb-2">Markdown 预览</p>
        {markdown ? <MarkdownContent content={markdown} /> : <p className="text-sm text-gray-400">暂无 Markdown 内容</p>}
      </div>
    </article>
  )
}
