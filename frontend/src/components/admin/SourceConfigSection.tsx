import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Copy, FileCheck2, FlaskConical, Pencil, Play, Plus, Power, RefreshCw, Trash2, X } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { fetchCategories } from '@/services/api'
import {
  approveSourceConfig,
  createSourceConfig,
  deleteSourceConfig,
  fetchSourceConfigs,
  probeSourceConfig,
  runSourceConfig,
  setSourceConfigEnabled,
  updateSourceConfig,
} from '@/services/crawlerAdminApi'
import { isRecord } from '@/types/news'
import type { SourceConfigInput, SourceConfigRecord, SourceEndpointKind } from '@/types/crawlerAdmin'

const sourceConfigKey = ['crawlerAdmin', 'sourceConfigs'] as const

type FormState = {
  sourceKey: string
  publisherName: string
  channelName: string
  category: string
  region: 'domestic' | 'international'
  language: string
  contentKind: string
  readingPolicy: string
  summaryAllowed: boolean
  feedFullContentAllowed: boolean
  officialHtmlFullContentAllowed: boolean
  endpointKind: SourceEndpointKind
  endpointUrl: string
  allowedDomains: string
  parserConfig: string
  requestIntervalSeconds: string
  maxResponseBytes: string
  maxPages: string
  maxItems: string
}

const emptyForm: FormState = {
  sourceKey: '', publisherName: '', channelName: '', category: '', region: 'domestic', language: 'zh',
  contentKind: 'article', readingPolicy: 'summary_only', summaryAllowed: true,
  feedFullContentAllowed: false, officialHtmlFullContentAllowed: false,
  endpointKind: 'rss', endpointUrl: '', allowedDomains: '', parserConfig: '{}',
  requestIntervalSeconds: '600', maxResponseBytes: '2097152', maxPages: '1', maxItems: '50',
}

function recordForm(source: SourceConfigRecord, copy: boolean): FormState {
  const endpoint = source.endpoints[0]
  return {
    sourceKey: copy ? `${source.sourceKey}_copy` : source.sourceKey,
    publisherName: source.publisherName,
    channelName: copy ? `${source.channelName} 副本` : source.channelName,
    category: source.category ? String(source.category) : '', region: source.region, language: source.language,
    contentKind: source.contentKind, readingPolicy: source.readingPolicy,
    summaryAllowed: source.summaryAllowed, feedFullContentAllowed: source.feedFullContentAllowed,
    officialHtmlFullContentAllowed: source.officialHtmlFullContentAllowed,
    endpointKind: endpoint?.kind ?? 'rss', endpointUrl: endpoint?.url ?? '',
    allowedDomains: endpoint?.allowedDomains.join(', ') ?? '',
    parserConfig: JSON.stringify(endpoint?.parserConfig ?? {}, null, 2),
    requestIntervalSeconds: String(endpoint?.requestIntervalSeconds ?? 600),
    maxResponseBytes: String(endpoint?.maxResponseBytes ?? 2097152),
    maxPages: String(endpoint?.maxPages ?? 1), maxItems: String(endpoint?.maxItems ?? 50),
  }
}

function toPayload(form: FormState): SourceConfigInput {
  const parserConfig = JSON.parse(form.parserConfig) as unknown
  if (!isRecord(parserConfig)) throw new Error('解析配置必须是 JSON 对象。')
  const category = Number(form.category)
  const requestIntervalSeconds = Number(form.requestIntervalSeconds)
  const maxResponseBytes = Number(form.maxResponseBytes)
  const maxPages = Number(form.maxPages)
  const maxItems = Number(form.maxItems)
  if (![category, requestIntervalSeconds, maxResponseBytes, maxPages, maxItems].every(Number.isInteger)) {
    throw new Error('分类与请求限制必须填写整数。')
  }
  return {
    source_key: form.sourceKey.trim(), publisher_name: form.publisherName.trim(), channel_name: form.channelName.trim(),
    category, region: form.region, language: form.language.trim(), content_kind: form.contentKind,
    reading_policy: form.readingPolicy, summary_allowed: form.summaryAllowed,
    feed_full_content_allowed: form.feedFullContentAllowed,
    official_html_full_content_allowed: form.officialHtmlFullContentAllowed,
    endpoints: [{
      kind: form.endpointKind, url: form.endpointUrl.trim(),
      allowed_domains: form.allowedDomains.split(',').map((value) => value.trim()).filter(Boolean),
      priority: 10, parser_config: parserConfig, conditional_requests: true,
      request_interval_seconds: requestIntervalSeconds, max_response_bytes: maxResponseBytes,
      max_pages: maxPages, max_items: maxItems, enabled: true,
    }],
  }
}

function formatDate(value: string | null): string {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString('zh-CN')
}

function statusVariant(status: SourceConfigRecord['status']): 'green' | 'red' | 'amber' | 'gray' {
  if (status === 'enabled') return 'green'
  if (status === 'blocked' || status === 'unsupported') return 'red'
  if (status === 'probed' || status === 'approved') return 'amber'
  return 'gray'
}

function sampleArticles(source: SourceConfigRecord) {
  const samples = source.probeSummary.sample_articles
  if (!Array.isArray(samples)) return []
  return samples.flatMap((sample) => isRecord(sample) && typeof sample.title === 'string' && typeof sample.url === 'string'
    ? [{ title: sample.title, url: sample.url, publishedAt: typeof sample.published_at === 'string' ? sample.published_at : '' }]
    : [])
}

export default function SourceConfigSection() {
  const queryClient = useQueryClient()
  const sources = useQuery({ queryKey: sourceConfigKey, queryFn: ({ signal }) => fetchSourceConfigs(signal), staleTime: 15_000 })
  const categories = useQuery({
    queryKey: ['crawlerAdmin', 'sourceCategories'],
    queryFn: async ({ signal }) => {
      const data = await fetchCategories(signal)
      const rows = Array.isArray(data) ? data : isRecord(data) && Array.isArray(data.results) ? data.results : []
      return rows.flatMap((item) => isRecord(item) && typeof item.id === 'number' && typeof item.name === 'string'
        ? [{ id: item.id, name: item.name }] : [])
    },
    staleTime: 60_000,
  })
  const [form, setForm] = useState<FormState | null>(null)
  const [editingKey, setEditingKey] = useState<string | null>(null)
  const [error, setError] = useState('')

  const refresh = async () => {
    setError('')
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: sourceConfigKey }),
      queryClient.invalidateQueries({ queryKey: ['crawlerAdmin', 'dashboard'] }),
      queryClient.invalidateQueries({ queryKey: ['crawlerAdmin', 'readiness'] }),
    ])
  }
  const mutation = useMutation({
    mutationFn: async (operation: () => Promise<unknown>) => operation(),
    onSuccess: refresh,
    onError: (reason) => setError(reason instanceof Error ? reason.message : '来源操作失败。'),
  })

  const submit = () => {
    if (!form) return
    try {
      const payload = toPayload(form)
      mutation.mutate(async () => {
        if (editingKey) {
          const changes: Partial<SourceConfigInput> = { ...payload }
          delete changes.source_key
          await updateSourceConfig(editingKey, changes)
        } else {
          await createSourceConfig(payload)
        }
        setForm(null); setEditingKey(null)
      })
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '表单内容无效。')
    }
  }

  const busy = mutation.isPending
  const configurableSources = sources.data?.filter((source) => !source.readOnly) ?? []
  const codeSources = sources.data?.filter((source) => source.readOnly) ?? []
  return (
    <section id="source-configs" className="mt-10 scroll-mt-20 space-y-4" aria-labelledby="source-config-title">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <h2 id="source-config-title" className="text-xl font-semibold">动态来源配置</h2>
          <p className="mt-1 max-w-3xl text-sm text-muted-foreground">这里仅展开可编辑的来源。新增来源默认不调度，必须先探测、审批，再由超级管理员启用。</p>
        </div>
        <div className="flex w-full flex-wrap gap-2 sm:w-auto">
          <Button variant="outline" disabled={sources.isFetching} onClick={() => void sources.refetch()}><RefreshCw aria-hidden="true" className={sources.isFetching ? 'animate-spin' : ''} />刷新</Button>
          <Button disabled={busy} onClick={() => { setEditingKey(null); setForm({ ...emptyForm, category: categories.data?.[0] ? String(categories.data[0].id) : '' }) }}><Plus aria-hidden="true" />新建来源</Button>
        </div>
      </div>

      {error ? <p role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800 dark:border-red-900 dark:bg-red-950/30 dark:text-red-200">{error}</p> : null}

      {form ? <Card>
        <CardHeader>
          <div className="flex items-start justify-between gap-3">
            <div><CardTitle>{editingKey ? '编辑来源配置' : '新建来源配置'}</CardTitle><CardDescription>修改入口、域名、解析规则或许可后，旧探测和审批会自动失效。</CardDescription></div>
            <Button size="icon" variant="ghost" aria-label="关闭来源配置表单" onClick={() => { setForm(null); setEditingKey(null) }}><X aria-hidden="true" /></Button>
          </div>
        </CardHeader>
        <CardContent className="grid min-w-0 gap-4 md:grid-cols-2">
          <label className="grid min-w-0 gap-1 text-sm">来源标识<Input value={form.sourceKey} disabled={Boolean(editingKey)} onChange={(event) => setForm({ ...form, sourceKey: event.target.value })} placeholder="official_health_news" /></label>
          <label className="grid min-w-0 gap-1 text-sm">出版者<Input value={form.publisherName} onChange={(event) => setForm({ ...form, publisherName: event.target.value })} /></label>
          <label className="grid min-w-0 gap-1 text-sm">频道名称<Input value={form.channelName} onChange={(event) => setForm({ ...form, channelName: event.target.value })} /></label>
          <label className="grid min-w-0 gap-1 text-sm">分类<select className="h-9 min-w-0 rounded-md border bg-background px-3" value={form.category} onChange={(event) => setForm({ ...form, category: event.target.value })}>{categories.data?.map((category) => <option key={category.id} value={category.id}>{category.name}</option>)}</select></label>
          <label className="grid min-w-0 gap-1 text-sm">入口类型<select className="h-9 min-w-0 rounded-md border bg-background px-3" value={form.endpointKind} onChange={(event) => setForm({ ...form, endpointKind: event.target.value as SourceEndpointKind })}><option value="rss">RSS</option><option value="atom">Atom</option><option value="json">JSON API</option><option value="html">官方 HTML</option></select></label>
          <label className="grid min-w-0 gap-1 text-sm">入口 URL<Input value={form.endpointUrl} onChange={(event) => setForm({ ...form, endpointUrl: event.target.value })} placeholder="https://example.cn/feed.xml" /></label>
          <label className="grid min-w-0 gap-1 text-sm md:col-span-2">许可域名（逗号分隔）<Input value={form.allowedDomains} onChange={(event) => setForm({ ...form, allowedDomains: event.target.value })} placeholder="example.cn, www.example.cn" /></label>
          <label className="grid gap-1 text-sm">内容类型<select className="h-9 rounded-md border bg-background px-3" value={form.contentKind} onChange={(event) => setForm({ ...form, contentKind: event.target.value })}><option value="article">资讯</option><option value="abstract">科研摘要</option><option value="regulatory_data">监管数据</option></select></label>
          <label className="grid gap-1 text-sm">读取政策<select className="h-9 rounded-md border bg-background px-3" value={form.readingPolicy} onChange={(event) => setForm({ ...form, readingPolicy: event.target.value })}><option value="summary_only">仅摘要</option><option value="public_feed">公开 Feed</option><option value="official_html">官方网页</option><option value="regulatory_data">监管数据</option></select></label>
          <label className="grid gap-1 text-sm">请求间隔（秒）<Input type="number" min={3} value={form.requestIntervalSeconds} onChange={(event) => setForm({ ...form, requestIntervalSeconds: event.target.value })} /></label>
          <label className="grid gap-1 text-sm">响应上限（字节）<Input type="number" min={1024} value={form.maxResponseBytes} onChange={(event) => setForm({ ...form, maxResponseBytes: event.target.value })} /></label>
          <label className="grid gap-1 text-sm">最大页数<Input type="number" min={1} max={5} value={form.maxPages} onChange={(event) => setForm({ ...form, maxPages: event.target.value })} /></label>
          <label className="grid gap-1 text-sm">最大条目<Input type="number" min={1} max={200} value={form.maxItems} onChange={(event) => setForm({ ...form, maxItems: event.target.value })} /></label>
          <label className="grid min-w-0 gap-1 text-sm md:col-span-2">受控解析配置（JSON）<textarea className="min-h-36 min-w-0 rounded-md border bg-background p-3 font-mono text-xs" value={form.parserConfig} onChange={(event) => setForm({ ...form, parserConfig: event.target.value })} /></label>
          <div className="flex flex-wrap gap-4 text-sm md:col-span-2">
            <label className="flex items-center gap-2"><input type="checkbox" checked={form.summaryAllowed} onChange={(event) => setForm({ ...form, summaryAllowed: event.target.checked })} />允许摘要</label>
            <label className="flex items-center gap-2"><input type="checkbox" checked={form.feedFullContentAllowed} onChange={(event) => setForm({ ...form, feedFullContentAllowed: event.target.checked })} />允许已验证 Feed 正文</label>
            <label className="flex items-center gap-2"><input type="checkbox" checked={form.officialHtmlFullContentAllowed} onChange={(event) => setForm({ ...form, officialHtmlFullContentAllowed: event.target.checked })} />允许官方网页正文</label>
          </div>
          <div className="flex justify-end gap-2 md:col-span-2"><Button variant="outline" onClick={() => { setForm(null); setEditingKey(null) }}>取消</Button><Button disabled={busy} onClick={submit}>保存为草稿</Button></div>
        </CardContent>
      </Card> : null}

      {sources.isLoading ? <div className="h-40 animate-pulse rounded-xl bg-muted" /> : sources.isError ? <Card><CardContent className="py-6 text-sm text-destructive">来源配置读取失败。</CardContent></Card> : (
        <div className="grid min-w-0 grid-cols-1 gap-4">
          {configurableSources.map((source) => {
            const endpoint = source.endpoints[0]
            const samples = sampleArticles(source)
            return <Card key={source.sourceKey} className="min-w-0 overflow-hidden">
              <CardHeader>
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="min-w-0 flex-1"><CardTitle className="break-words text-base">{source.channelName}</CardTitle><CardDescription className="break-words">{source.publisherName} · <code className="break-all">{source.sourceKey}</code></CardDescription></div>
                  <div className="flex shrink-0 flex-wrap gap-2"><Badge variant={statusVariant(source.status)}>{source.status}</Badge><Badge variant="gray">{source.maintenance === 'code' ? '代码维护' : '后台维护'}</Badge></div>
                </div>
              </CardHeader>
              <CardContent className="min-w-0 space-y-4 text-sm">
                <div className="grid min-w-0 grid-cols-1 gap-2 text-muted-foreground sm:grid-cols-2">
                  <span className="min-w-0 break-words">入口：{endpoint?.kind?.toUpperCase() ?? '自定义'}</span><span className="min-w-0 break-words">分类：{source.categoryName || '—'}</span>
                  <span className="min-w-0 break-words">读取：{source.readingPolicy}</span><span className="min-w-0 break-words">正文：{source.feedFullContentAllowed || source.officialHtmlFullContentAllowed ? '已批准' : '仅摘要/链接'}</span>
                  <span className="min-w-0 break-words">版本：v{source.configVersion}</span><span className="min-w-0 break-words">审批：{formatDate(source.approvedAt)}</span>
                </div>
                {endpoint?.url ? <p className="min-w-0 break-all font-mono text-xs" title={endpoint.url}>{endpoint.url}</p> : null}
                <div className="grid min-w-0 grid-cols-1 gap-2 rounded-lg bg-muted/50 p-3 text-xs sm:grid-cols-2">
                  <span className="min-w-0 break-words">最近探测：{formatDate(source.probedAt)}</span><span className="min-w-0 break-words">Feed 成功：{formatDate(source.monitoring.lastFeedSuccessAt)}</span>
                  <span className="min-w-0 break-words">运行成功：{formatDate(source.monitoring.lastSuccessAt)}</span><span className="min-w-0 break-words">下次轮询：{formatDate(source.monitoring.nextPollAt)}</span>
                  <span className="min-w-0 break-words">Worker 心跳：{formatDate(source.monitoring.workerHeartbeatAt)}</span><span className="min-w-0 break-words">冷却截止：{formatDate(source.monitoring.cooldownUntil)}</span>
                </div>
                {source.monitoring.latestArticle ? <p className="min-w-0 break-words text-xs text-muted-foreground">最新入库：<a className="break-words hover:underline" href={source.monitoring.latestArticle.url} target="_blank" rel="noreferrer">{source.monitoring.latestArticle.title}</a> · {formatDate(source.monitoring.latestArticle.publishTime)}</p> : null}
                {Object.keys(source.monitoring.lastHttpStatuses).length ? <p className="break-words text-xs text-muted-foreground">HTTP 状态：{Object.entries(source.monitoring.lastHttpStatuses).map(([code, count]) => `${code}:${count}`).join(' · ')}</p> : null}
                {source.unavailableReason ? <p className="break-words text-red-700 dark:text-red-300">不可用原因：{source.unavailableReason}</p> : null}
                {source.monitoring.lastFailure ? <p className="break-words text-red-700 dark:text-red-300">最近失败：{source.monitoring.lastFailure}</p> : null}
                {samples.length ? <div className="min-w-0"><p className="mb-1 font-medium">探测样本</p><ul className="min-w-0 space-y-1 text-xs text-muted-foreground">{samples.map((sample) => <li key={sample.url} className="min-w-0 break-words"><a className="break-words hover:underline" href={sample.url} target="_blank" rel="noreferrer">{sample.title}</a>{sample.publishedAt ? ` · ${sample.publishedAt}` : ''}</li>)}</ul></div> : null}
                <div className="grid grid-cols-2 gap-2 sm:flex sm:flex-wrap sm:justify-end">
                  {!source.readOnly ? <Button className="w-full sm:w-auto" size="sm" variant="outline" disabled={busy} onClick={() => { setEditingKey(source.sourceKey); setForm(recordForm(source, false)) }}><Pencil aria-hidden="true" />编辑</Button> : null}
                  <Button className="w-full sm:w-auto" size="sm" variant="outline" disabled={busy || !source.category} onClick={() => { setEditingKey(null); setForm(recordForm(source, true)) }}><Copy aria-hidden="true" />复制</Button>
                  {!source.readOnly ? <Button className="w-full sm:w-auto" size="sm" variant="outline" disabled={busy} onClick={() => mutation.mutate(() => probeSourceConfig(source.sourceKey))}><FlaskConical aria-hidden="true" />探测</Button> : null}
                  {!source.readOnly ? <Button className="w-full sm:w-auto" size="sm" variant="outline" disabled={busy || source.status !== 'probed' || !source.probeIsCurrent} onClick={() => mutation.mutate(() => approveSourceConfig(source.sourceKey))}><FileCheck2 aria-hidden="true" />审批</Button> : null}
                  {!source.readOnly ? <Button className="w-full sm:w-auto" size="sm" variant="outline" disabled={busy || !source.approvalIsCurrent} onClick={() => mutation.mutate(() => runSourceConfig(source.sourceKey))}><Play aria-hidden="true" />试运行</Button> : null}
                  {!source.readOnly ? <Button className="w-full sm:w-auto" size="sm" disabled={busy || (source.status !== 'enabled' && !source.canEnable)} variant={source.status === 'enabled' ? 'outline' : 'default'} onClick={() => mutation.mutate(() => setSourceConfigEnabled(source.sourceKey, source.status !== 'enabled'))}><Power aria-hidden="true" />{source.status === 'enabled' ? '停用' : '启用'}</Button> : null}
                  {!source.readOnly && source.status === 'draft' ? <Button className="w-full sm:w-auto" size="sm" variant="destructive" disabled={busy} onClick={() => { if (window.confirm('只允许删除没有文章、运行和订阅关系的草稿。确认删除？')) mutation.mutate(() => deleteSourceConfig(source.sourceKey)) }}><Trash2 aria-hidden="true" />删除</Button> : null}
                </div>
              </CardContent>
            </Card>
          })}
          {!configurableSources.length ? <Card><CardContent className="py-8 text-center text-sm text-muted-foreground">暂无可编辑的来源配置。</CardContent></Card> : null}
        </div>
      )}

      {!sources.isLoading && !sources.isError && codeSources.length ? (
        <details className="group overflow-hidden rounded-xl border bg-card">
          <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-5 py-4 font-medium marker:content-none">
            <span>代码维护来源 <span className="ml-1 text-sm font-normal text-muted-foreground">{codeSources.length} 个，只读</span></span>
            <span aria-hidden="true" className="text-muted-foreground transition-transform group-open:rotate-180">⌄</span>
          </summary>
          <div className="workspace-scroll overflow-x-auto border-t">
            <table className="w-full min-w-[680px] text-left text-sm">
              <thead className="bg-muted/60 text-xs text-muted-foreground"><tr><th className="px-4 py-3">来源</th><th className="px-4 py-3">标识</th><th className="px-4 py-3">分类</th><th className="px-4 py-3">区域</th><th className="px-4 py-3 text-right">操作</th></tr></thead>
              <tbody>{codeSources.map((source) => <tr key={source.sourceKey} className="border-t">
                <td className="max-w-72 break-words px-4 py-3 font-medium">{source.channelName}</td>
                <td className="max-w-64 break-all px-4 py-3 font-mono text-xs text-muted-foreground">{source.sourceKey}</td>
                <td className="px-4 py-3 text-muted-foreground">{source.categoryName || '—'}</td>
                <td className="px-4 py-3 text-muted-foreground">{source.region === 'domestic' ? '国内' : '国际'}</td>
                <td className="px-4 py-3 text-right"><Button size="sm" variant="outline" disabled={busy || !source.category} onClick={() => { setEditingKey(null); setForm(recordForm(source, true)) }}><Copy aria-hidden="true" />复制为配置</Button></td>
              </tr>)}</tbody>
            </table>
          </div>
        </details>
      ) : null}
    </section>
  )
}
