import { useQuery } from '@tanstack/react-query'
import { listAIUsage } from '@/services/aiConnectionsApi'

const PURPOSES: Record<string, string> = {
  article_qa: '文章问答', full_translation: '全文翻译', deep_research: '深度研究',
  question_suggestions: '推荐问题', 'model_probe:text': '文本测试', 'model_probe:tools': '工具测试',
}
const STATUSES: Record<string, string> = {
  succeeded: '已完成', failed: '失败', unknown: '结果未知', unsupported: '不支持',
}
const tokens = (value: number | null) => value === null ? '未知' : value.toLocaleString()

export default function AIUsageSection({ viewer }: { viewer: number }) {
  const usage = useQuery({
    queryKey: ['ai-usage', viewer], queryFn: ({ signal }) => listAIUsage(signal),
    staleTime: 30_000, retry: false,
  })
  return <section className="workspace-card min-w-0" aria-labelledby="ai-usage-title">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h2 id="ai-usage-title" className="font-semibold">个人 AI 使用记录</h2>
      <button type="button" className="workspace-button" disabled={usage.isFetching}
        onClick={() => void usage.refetch()}>刷新记录</button>
    </div>
    <p className="mt-2 text-sm text-muted-foreground">记录本站个人模型调用尝试；进行中或中断的请求可能显示结果未知。研究工具轮次与翻译分段分别计数；读取缓存、历史和重连不新增调用。Token 缺失或结果未知时不估算，不代表服务商账户余额或费用。</p>
    {usage.isPending && <p role="status" className="mt-3 text-sm">正在读取使用记录…</p>}
    {usage.isError && <p role="alert" className="mt-3 text-sm text-destructive">暂时无法读取使用记录，请稍后刷新。</p>}
    {usage.data && <>
      <p className="mt-3 text-sm">共 {usage.data.summary.calls} 次尝试；已知输入 Token {tokens(usage.data.summary.input_tokens)}，已知输出 Token {tokens(usage.data.summary.output_tokens)}。</p>
      <p className="text-xs text-muted-foreground">输入未知 {usage.data.summary.input_tokens_unknown_calls} 次，输出未知 {usage.data.summary.output_tokens_unknown_calls} 次。成功状态表示模型响应完成，业务结果是否保存请查看相应任务。</p>
      {usage.data.attempts.length === 0 ? <p className="mt-3 text-sm">暂无调用记录。历史业务调用不会补造记录。</p> :
        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[540px] text-left text-xs">
            <thead><tr><th className="p-2">时间</th><th className="p-2">用途 / 模型</th><th className="p-2">状态</th><th className="p-2">输入 / 输出 Token</th></tr></thead>
            <tbody>{usage.data.attempts.map(row => <tr key={`${row.source}:${row.id}`} className="border-t border-border">
              <td className="p-2 whitespace-nowrap">{new Date(row.created_at).toLocaleString()}</td>
              <td className="p-2 break-all">{PURPOSES[row.task_kind] ?? row.task_kind}<br />{row.provider_id} · {row.model_id}</td>
              <td className="p-2 whitespace-nowrap">{STATUSES[row.status] ?? '结果未知'}</td>
              <td className="p-2">{tokens(row.input_tokens)} / {tokens(row.output_tokens)}</td>
            </tr>)}</tbody>
          </table>
        </div>}
      {usage.data.has_more && <p className="mt-2 text-xs text-muted-foreground">显示最近 50 条记录；汇总包含全部已有记录。</p>}
    </>}
  </section>
}
