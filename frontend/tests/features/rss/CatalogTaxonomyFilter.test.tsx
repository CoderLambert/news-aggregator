import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import CatalogTaxonomyFilter from '@/features/rss/CatalogTaxonomyFilter'
import { parseCatalogSections } from '@/features/rss/catalogTaxonomy'

afterEach(cleanup)
const sections = [
  { key: 'tech', label: '技术', count: 42, groups: [
    { key: 'ai-llm', label: 'AI / 大模型', count: 21 },
    { key: 'frontend', label: '前端开发', count: 21 },
  ] },
  { key: 'industry', label: '行业', count: 20, groups: [{ key: 'automotive', label: '汽车', count: 20 }] },
]
const empty = { section: '', group: '', language: '', region: '' }

describe('public default catalog taxonomy', () => {
  it('preserves slash-containing names and accepts old API without taxonomy', () => {
    expect(parseCatalogSections(undefined)).toEqual([])
    expect(parseCatalogSections(sections)[0].groups[0].label).toBe('AI / 大模型')
  })
  it('rejects malformed counts, duplicate keys and unknown shapes', () => {
    for (const value of [null, {}, [sections[0], sections[0]],
      [{ ...sections[0], count: -1 }], [{ ...sections[0], groups: 'wrong' }]]) {
      expect(() => parseCatalogSections(value)).toThrow(TypeError)
    }
  })
  it('changes a section without retaining an incompatible child selection', () => {
    const onChange = vi.fn()
    render(<CatalogTaxonomyFilter sections={sections} value={{ ...empty, section: 'tech', group: 'frontend' }} onChange={onChange} />)
    fireEvent.click(screen.getByRole('button', { name: '行业 20' }))
    expect(onChange).toHaveBeenCalledWith({ ...empty, section: 'industry', group: '' })
  })
  it('shows the selected section children and combines language without side effects', () => {
    const onChange = vi.fn()
    render(<CatalogTaxonomyFilter sections={sections} value={{ ...empty, section: 'tech' }} onChange={onChange} />)
    expect(screen.getByRole('option', { name: 'AI / 大模型 (21)' })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: '汽车 (20)' })).not.toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('订阅源语言'), { target: { value: 'zh' } })
    expect(onChange).toHaveBeenCalledWith({ ...empty, section: 'tech', language: 'zh' })
    expect(screen.getByText(/不是新增订阅数/)).toBeInTheDocument()
  })
  it('disables mutations while subscription submission is pending', () => {
    render(<CatalogTaxonomyFilter sections={sections} value={empty} onChange={vi.fn()} disabled />)
    expect(screen.getByRole('button', { name: '技术 42' })).toBeDisabled()
    expect(screen.getByLabelText('订阅源语言')).toBeDisabled()
  })
})
