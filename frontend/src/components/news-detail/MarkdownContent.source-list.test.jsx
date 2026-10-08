import { describe, expect, it } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import MarkdownContent from './MarkdownContent'

describe('MarkdownContent ordered lists', () => {
  it.each([
    ['fragment anchors', '#methods'],
    ['relative links', '../references/paper'],
    ['mailto links', 'mailto:editor@example.test'],
  ])('preserves an ordered list containing only %s as a standard list', (_kind, href) => {
    render(<MarkdownContent content={`1. [Reference](${href})`} />)

    const list = screen.getByRole('list')
    expect(list.tagName).toBe('OL')
    expect(within(list).getByRole('link', { name: 'Reference' })).toHaveAttribute('href', href)
  })

  it('keeps plain ordered items when no citation URL is present', () => {
    render(<MarkdownContent content={'1. First step\n2. Second step'} />)

    const list = screen.getByRole('list')
    expect(list.tagName).toBe('OL')
    expect(within(list).getAllByRole('listitem')).toHaveLength(2)
  })

  it('renders a list of supported source citations as source cards', () => {
    render(<MarkdownContent content={'1. Paper: [Open paper](https://example.test/paper)\n2. Article: [Open article](/news/42)'} />)

    expect(screen.queryByRole('list')).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: '原文' })).toHaveAttribute('href', 'https://example.test/paper')
    expect(screen.getByRole('link', { name: '详情' })).toHaveAttribute('href', '/news/42')
  })
})
