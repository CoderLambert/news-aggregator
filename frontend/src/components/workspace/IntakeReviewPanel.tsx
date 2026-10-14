import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { useAuth } from '@/context/AuthContext'
import { workspaceRequest, workspaceError } from '@/services/workspaceApi'

interface Intake {
  id: number
  url: string
  status: 'pending' | 'approved' | 'rejected'
  reason: string
  review_revision: number
  reviewed_at: string | null
  source_id: number | null
  requires_resubmission: boolean
}
interface IntakePage { count: number; next: string | null; previous: string | null; results: Intake[] }
const labels = { pending: '待审核', approved: '审核通过', rejected: '已驳回' }

export default function IntakeReviewPanel() {
  const { user } = useAuth()
  const [open, setOpen] = useState(false)
  if (!user) return null
  return <section className="workspace-soft-panel">
    <button type="button" className="workspace-link" aria-expanded={open} onClick={() => setOpen(!open)}>接入申请与审核记录</button>
    {open && <IntakeRecords key={user.id} viewer={user.id} admin={user.isSuperuser} />}
  </section>
}

function IntakeRecords({ viewer, admin }: { viewer: number; admin: boolean }) {
  const client = useQueryClient()
  const [reviewMode, setReviewMode] = useState(false)
  const [page, setPage] = useState(1)
  const [reason, setReason] = useState<Record<number, string>>({})
  const own = useQuery({ queryKey: ['channelIntake', viewer, 'own'], enabled: !reviewMode,
    queryFn: ({ signal }) => workspaceRequest<Intake[]>('/me/smart-channels/intake/', { signal }), retry: false })
  const queue = useQuery({ queryKey: ['channelIntake', viewer, 'review', page], enabled: admin && reviewMode,
    queryFn: ({ signal }) => workspaceRequest<IntakePage>('/admin/smart-channels/intake/?page=' + page, { signal }), retry: false })
  const decision = useMutation({
    mutationFn: ({ item, status }: { item: Intake; status: 'approved' | 'rejected' }) => workspaceRequest<Intake>(
      '/admin/smart-channels/intake/' + item.id + '/', { method: 'PATCH', body: {
        status, reason: reason[item.id]?.trim(), review_revision: item.review_revision,
      } }),
    onSuccess: () => client.invalidateQueries({ queryKey: ['channelIntake', viewer] }),
  })
  const current = reviewMode ? queue : own
  const rows = reviewMode ? queue.data?.results : own.data
  return <div>
    <p className="workspace-caption">通过审核只记录接入决定，不自动订阅、启动爬虫或调用模型。采集配置与内容许可仍需独立确认。</p>
    {admin && <button type="button" className="workspace-button secondary" onClick={() => { setReviewMode(!reviewMode); setPage(1) }}>{reviewMode ? '查看我的申请' : '管理员审核全部申请'}</button>}
    {current.isPending && <p role="status">正在读取申请…</p>}
    {current.isError && <p role="alert">{workspaceError(current.error)} <button type="button" onClick={() => void current.refetch()}>重试</button></p>}
    {decision.isError && <p role="alert" className="workspace-error">{workspaceError(decision.error)}</p>}
    {rows?.length === 0 && <p>暂无接入申请。</p>}
    {rows?.map(item => <article key={item.id} className="workspace-soft-panel">
      <p><strong>#{item.id} · {labels[item.status] ?? item.status}</strong></p>
      <p className="break-all">{item.requires_resubmission ? '旧地址可能含敏感参数，请重新提交公开入口。' : item.url}</p>
      {item.reason && <p>审核说明：{item.reason}</p>}
      {item.reviewed_at && <p className="workspace-caption">审核时间：{new Date(item.reviewed_at).toLocaleString()}</p>}
      {item.source_id && <Link to={'/channels/' + item.source_id}>查看已登记频道</Link>}
      {admin && reviewMode && item.status === 'pending' && <fieldset disabled={decision.isPending}>
        <label>审核说明<textarea aria-label={'申请 ' + item.id + ' 的审核说明'} maxLength={500} value={reason[item.id] ?? ''}
          onChange={event => setReason(values => ({ ...values, [item.id]: event.target.value }))} /></label>
        <div className="workspace-actions">
          <button type="button" className="workspace-button" disabled={!reason[item.id]?.trim() || item.requires_resubmission}
            onClick={() => decision.mutate({ item, status: 'approved' })}>通过审核，不开启采集</button>
          <button type="button" className="workspace-button secondary" disabled={!reason[item.id]?.trim()}
            onClick={() => decision.mutate({ item, status: 'rejected' })}>驳回并反馈</button>
        </div>
      </fieldset>}
    </article>)}
    {reviewMode && <nav aria-label="接入申请分页" className="workspace-actions">
      <button type="button" disabled={page <= 1 || queue.isFetching} onClick={() => setPage(page - 1)}>上一页</button>
      <span>第 {page} 页</span>
      <button type="button" disabled={!queue.data?.next || queue.isFetching} onClick={() => setPage(page + 1)}>下一页</button>
    </nav>}
  </div>
}
