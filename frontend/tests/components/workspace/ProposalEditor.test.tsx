import '@tests/helpers/commandDom'
import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { ProposalEditor } from '@/pages/SmartGroupingWorkspace'
import type { Proposal } from '@/services/workspaceApi'

const proposal: Proposal = {
  id: 'test-preview', engine: 'rules', status: 'ready', source_ids: [1, 2], topic_keys: ['frontend'],
  result: [{ source_id: 1, name: 'React Blog', topic_keys: ['frontend'], reason: '框架资料', origin: 'catalog', needs_review: false },
    { source_id: 2, name: 'Unknown channel', topic_keys: [], reason: '信息不足', origin: 'unknown', needs_review: true }],
  error_code: '', created_at: '2026-10-13T00:00:00Z', expires_at: '2026-10-14T00:00:00Z', applied_count: 0, model_id: '', attempts: 0,
}
const topics = [{ key: 'frontend', name: '前端开发', description: 'Web 平台' }]

function setup(groups: Array<{ id: number; name: string; source_ids: number[] }> = []) {
  const onApply = vi.fn(), onCancel = vi.fn()
  render(<ProposalEditor proposal={proposal} topics={topics} groups={groups} mode="suggest" busy={false} onApply={onApply} onCancel={onCancel} />)
  return { onApply, onCancel }
}
describe('editable grouping preview', () => {
  it('does not apply until the user explicitly confirms', () => {
    const { onApply } = setup()
    expect(onApply).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: '确认应用分组' }))
    expect(onApply).toHaveBeenCalledWith({ mode: 'suggest', groups: [{ topic_key: 'frontend', name: '前端开发', source_ids: [1] }] })
  })
  it('requires explicit selection before reusing an existing same-name group', async () => {
    const { onApply } = setup([{ id: 7, name: '前端开发', source_ids: [] }])
    expect(screen.getByRole('button', { name: '确认应用分组' })).toBeDisabled()
    fireEvent.click(screen.getByRole('combobox', { name: '目标分组 frontend' }))
    fireEvent.change(screen.getByRole('combobox', { name: '搜索目标分组 frontend' }), { target: { value: '7' } })
    fireEvent.click(await screen.findByRole('option', { name: /前端开发.*ID 7/ }))
    fireEvent.click(screen.getByRole('button', { name: '确认应用分组' }))
    expect(onApply).toHaveBeenCalledWith({ mode: 'suggest', groups: [{ topic_key: 'frontend', group_id: 7, source_ids: [1] }] })
  })
  it('allows a user to correct uncertain source membership', () => {
    const { onApply } = setup()
    fireEvent.click(screen.getByRole('button', { name: '调整频道归属' }))
    fireEvent.click(screen.getByRole('checkbox', { name: /Unknown channel/ }))
    fireEvent.click(screen.getByRole('button', { name: '确认应用分组' }))
    expect(onApply.mock.calls[0][0].groups[0].source_ids).toEqual([1, 2])
  })
  it('labels title-evidence matches as unverified and never applies them automatically', () => {
    const inferred: Proposal = {
      ...proposal,
      result: [{ source_id: 1, name: 'Unlisted source', topic_keys: ['frontend'],
        origin: 'title_evidence', needs_review: true,
        reason: '最近 4 篇不同文章标题：前端开发 3 篇；仅供人工确认。' }],
    }
    const onApply = vi.fn()
    render(<ProposalEditor proposal={inferred} topics={topics} groups={[]}
      mode="suggest" busy={false} onApply={onApply} onCancel={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: '调整频道归属' }))
    expect(screen.getByText(/标题证据推测·待确认/)).toBeInTheDocument()
    expect(screen.getByText(/仅供人工确认/)).toBeInTheDocument()
    expect(onApply).not.toHaveBeenCalled()
  })
  it('cancels without invoking apply and never shows a fabricated confidence percentage', () => {
    const { onApply, onCancel } = setup()
    fireEvent.click(screen.getByRole('button', { name: '取消预览' }))
    expect(onCancel).toHaveBeenCalledOnce()
    expect(onApply).not.toHaveBeenCalled()
    expect(screen.queryByText(/\d+%/)).toBeNull()
  })
})
