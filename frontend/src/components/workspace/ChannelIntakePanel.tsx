import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { workspaceRequest, workspaceError } from '@/services/workspaceApi'

interface Intake {
  id: number; url: string; url_safe: boolean; status: string
  review_reason: string; created_at: string; reviewed_at: string | null
  activation_status: 'not_enabled'
}
interface IntakePage { count: number; results: Intake[]; next: string | null; previous: string | null }
const labels: Record<string, string> = { pending: '待审核', approved: '已批准受理，尚未启用采集', rejected: '已驳回' }

export default function ChannelIntakePanel({ viewer, admin = false }: { viewer: number; admin?: boolean }) {
  const [open, setOpen] = useState(false)
  const [page, setPage] = useState(1)
  const client = useQueryClient()
  const prefix = ['workspace', viewer, 'intake-history', admin ? 'admin' : 'owner'] as const
  const endpoint = admin ? '/admin/smart-channels/intake/' : '/me/smart-channels/intake/history/'
  const history = useQuery({ queryKey: [...prefix, page], enabled: open,
    queryFn: ({ signal }) => workspaceRequest<IntakePage>(endpoint + '?page=' + page, { signal }),
    retry: false })
  const review = useMutation({
    mutationFn: ({ id, decision, reason }: { id: number; decision: 'approved' | 'rejected'; reason: string }) =>
      workspaceRequest<Intake>('/admin/smart-channels/intake/' + id + '/', { method: 'POST', body: { decision, reason } }),
    onSuccess: async () => { await client.invalidateQueries({ queryKey: ['workspace', viewer, 'intake-history'] }) },
  })
  return <section className="workspace-panel" aria-label={admin ? '频道接入审批' : '个人频道接入记录'}>
    <button type="button" className="workspace-link" aria-expanded={open} onClick={() => setOpen(value => !value)}>
      {admin ? '审核频道接入申请' : '我的接入申请'}
    </button>
    {open && <>
      <p className="workspace-caption">批准表示同意受理，不会自动注册来源、启用抓取或替用户订阅；发布者许可与采集策略仍须另行核验。</p>
      {history.isPending && <p role="status">正在读取申请…</p>}
      {history.isError && <p role="alert">{workspaceError(history.error)}</p>}
      {review.isError && <p role="alert">{workspaceError(review.error)}</p>}
      {review.isSuccess && <p role="status">审核结果已保存。</p>}
      {history.data?.results.length === 0 && <p>暂无接入申请。</p>}
      <ul className="workspace-intake-list">{history.data?.results.map(item => <li key={item.id}>
        <div><code>{item.url_safe ? item.url : '历史地址含敏感或不支持参数，已隐藏'}</code>
          <p>{labels[item.status] ?? '未知状态'}</p>
          {item.review_reason && <p>审核说明：{item.review_reason}</p>}
          {item.reviewed_at && <time dateTime={item.reviewed_at}>{new Date(item.reviewed_at).toLocaleString()}</time>}
        </div>
        {admin && item.status === 'pending' && <ReviewForm id={item.id} safe={item.url_safe} busy={review.isPending}
          onReview={(decision, reason) => review.mutate({ id: item.id, decision, reason })} />}
      </li>)}</ul>
      <div className="workspace-actions">
        <button type="button" disabled={page <= 1 || history.isFetching} onClick={() => setPage(value => value - 1)}>上一页</button>
        <span>第 {page} 页{history.data ? ` · 共 ${history.data.count} 项` : ''}</span>
        <button type="button" disabled={!history.data?.next || history.isFetching} onClick={() => setPage(value => value + 1)}>下一页</button>
        <button type="button" disabled={history.isFetching} onClick={() => void history.refetch()}>刷新申请状态</button>
      </div>
    </>}
  </section>
}

function ReviewForm({ id, safe, busy, onReview }: { id: number; safe: boolean; busy: boolean;
  onReview: (decision: 'approved' | 'rejected', reason: string) => void }) {
  const [reason, setReason] = useState('')
  return <div className="workspace-soft-panel">
    <label htmlFor={'intake-reason-' + id}>审核说明</label>
    <textarea id={'intake-reason-' + id} maxLength={500} value={reason} disabled={busy}
      onChange={event => setReason(event.target.value)} placeholder="说明受理范围或驳回原因，不要填写凭据" />
    <div className="workspace-actions">
      <button type="button" className="workspace-button" disabled={busy || !safe || !reason.trim()}
        onClick={() => onReview('approved', reason.trim())}>批准受理</button>
      <button type="button" className="workspace-button secondary" disabled={busy || !reason.trim()}
        onClick={() => onReview('rejected', reason.trim())}>驳回申请</button>
    </div>
  </div>
}
