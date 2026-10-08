import { describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import MarkdownContent from '@/components/news-detail/MarkdownContent'

vi.mock('mermaid', () => ({
  default: {
    initialize: vi.fn(),
    render: vi.fn().mockRejectedValue(new Error('invalid diagram syntax')),
  },
}))

describe('MarkdownContent Mermaid fallback', () => {
  it('keeps the source visible and announces a failed diagram render', async () => {
    render(<MarkdownContent content={'```mermaid\ngraph TD\n  A --> B\n```'} />)

    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Mermaid 图表渲染失败'))
    expect(screen.getByRole('alert')).toHaveTextContent('A --> B')
  })
})
