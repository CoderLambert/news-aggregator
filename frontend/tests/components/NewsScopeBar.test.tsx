import '@tests/helpers/commandDom'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import NewsScopeBar from '@/components/NewsScopeBar'

afterEach(cleanup)
it('keeps direct long Chinese group names visible and preserves real parent paths in the searchable scope picker', () => {
  const label = '🌐 科技媒体与开源生态深度阅读'
  const onChange = vi.fn()
  render(<MemoryRouter><NewsScopeBar scope="group" groupId={1} personal accounts region="all" onRegionChange={vi.fn()} onChange={onChange}
    roots={[{ id: 4, name: '技术', version: 1, child_count: 1, created_at: 'now', updated_at: 'now' }]}
    groups={[
      { id: 1, root_id: null, name: label, source_ids: [3], version: 1, created_at: 'now', updated_at: 'now' },
      { id: 2, root_id: 4, name: '🎨 前端 & 设计', source_ids: [], version: 1, created_at: 'now', updated_at: 'now' },
    ]} /></MemoryRouter>)
  const picker = screen.getByRole('combobox', { name: '选择分组' })
  expect(picker).toHaveTextContent(label)
  expect(picker).not.toHaveTextContent('OPML 导入')
  fireEvent.click(picker)
  expect(screen.getByRole('option', { name: label })).toBeInTheDocument()
  expect(screen.getByRole('option', { name: '技术 / 🎨 前端 & 设计' })).toBeInTheDocument()
  fireEvent.change(screen.getByRole('combobox', { name: '搜索分组' }), { target: { value: '前端' } })
  fireEvent.click(screen.getByRole('option', { name: '技术 / 🎨 前端 & 设计' }))
  expect(onChange).toHaveBeenCalledWith('group:2')
})
