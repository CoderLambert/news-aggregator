import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import WorkspaceModal from '@/components/workspace/WorkspaceModal'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { NativeSelect } from '@/components/ui/native-select'
import { decideRecommendation, rssReviewKey, type Recommendation } from '@/services/rssReviewApi'
import { useSerialReviewActions } from './useSerialReviewActions'

export default function ReviewRecommendationsDialog({ viewer, rows, onClose }: {
  viewer: number; rows: Recommendation[]; onClose: () => void
}) {
  const client = useQueryClient()
  const batch = useSerialReviewActions()
  const [action, setAction] = useState('approve')
  const [reason, setReason] = useState('')
  const [consent, setConsent] = useState(false)
  const complete = batch.done.length === rows.length
  const valid = rows.length > 0 && rows.length <= 10 && consent && (action === 'approve' || reason.trim())
  async function submit() {
    if (!valid) return
    await batch.run(rows.map(row => row.candidate_id), (id, key) => {
      const row = rows.find(item => item.candidate_id === id)!
      return decideRecommendation(viewer, id, { action, expected_version: row.version, reason }, key)
    })
    void client.invalidateQueries({ queryKey: rssReviewKey(viewer) })
  }
  return <WorkspaceModal title="批量审核公开推荐" busy={batch.busy} onClose={onClose}>
    <p>请逐项核对名称、分类和 RSS 地址。通过审核后仍需完成连接核验，才会公开；个人订阅和记录不会公开。</p>
    <ul className="my-4 grid gap-3">{rows.map(row => <li key={row.candidate_id} className="rounded border p-3">
      <strong>{row.name}</strong> · {row.category_name} · {row.language}<p className="break-all">{row.feed_url}</p>
      <p>{row.scope_description}</p>{batch.done.includes(row.candidate_id) && <p role="status">审核已提交</p>}
    </li>)}</ul>
    <label>审核决定<NativeSelect value={action} disabled={batch.started} onChange={e => setAction(e.target.value)}><option value="approve">通过审核</option><option value="reject">驳回推荐</option></NativeSelect></label>
    <label>审核说明（驳回时必填）<Input value={reason} maxLength={1000} disabled={batch.started} onChange={e => setReason(e.target.value)} /></label>
    <label className="my-3 flex gap-2"><Checkbox checked={consent} disabled={batch.started} onChange={e => setConsent(e.target.checked)} />我已逐项核对所选推荐，确认执行上述决定</label>
    {batch.started && <p role="status">已完成 {batch.done.length} / {rows.length} 项审核</p>}
    {batch.error && <p role="alert">{batch.error}。已完成结果会保留。权限或版本改变时请关闭并刷新列表；结果待确认时可重试未完成项。</p>}
    <footer className="workspace-modal-actions"><Button variant="outline" disabled={batch.busy} onClick={onClose}>关闭</Button>
      {!complete && <Button disabled={!valid || batch.busy} onClick={() => void submit()}>{batch.busy ? '提交中…' : batch.started ? '重试未完成项' : '确认批量审核'}</Button>}
    </footer>
  </WorkspaceModal>
}
