import { describe, expect, it } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import MarkdownContent from '@/components/news-detail/MarkdownContent'

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

  it.each([
    ['fragment anchor', '#methods', 'Methods'],
    ['relative link', '../references/paper', 'Relative reference'],
    ['mailto link', 'mailto:editor@example.test', 'Contact editor'],
  ])('preserves a supported citation and a %s in the same list item', (_kind, unsupportedHref, otherLabel) => {
    render(<MarkdownContent content={`1. [Paper](https://example.test/paper) and [${otherLabel}](${unsupportedHref})`} />)

    const list = screen.getByRole('list')
    expect(list.tagName).toBe('OL')
    const items = within(list).getAllByRole('listitem')
    expect(items.map((item) => item.textContent)).toEqual([`Paper and ${otherLabel}`])
    const links = Array.from(list.querySelectorAll('a'))
    expect(links.map((link) => link.getAttribute('href'))).toEqual([
      'https://example.test/paper',
      unsupportedHref,
    ])
    expect(links.map((link) => link.textContent)).toEqual(['Paper', otherLabel])
  })

  it('preserves list order and all links when only one item contains an unsupported link', () => {
    render(<MarkdownContent content={'1. [Paper](https://example.test/paper)\n2. Contact [editor](mailto:editor@example.test)'} />)

    const list = screen.getByRole('list')
    expect(list.tagName).toBe('OL')
    const items = within(list).getAllByRole('listitem')
    expect(items.map((item) => item.textContent)).toEqual(['Paper', 'Contact editor'])
    const links = Array.from(list.querySelectorAll('a'))
    expect(links.map((link) => link.getAttribute('href'))).toEqual([
      'https://example.test/paper',
      'mailto:editor@example.test',
    ])
    expect(links.map((link) => link.textContent)).toEqual(['Paper', 'editor'])
  })

  it('renders a list of supported source citations as source cards', () => {
    render(<MarkdownContent content={'1. Paper: [Open paper](https://example.test/paper)\n2. Article: [Open article](/news/42)'} />)

    expect(screen.queryByRole('list')).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: '原文' })).toHaveAttribute('href', 'https://example.test/paper')
    expect(screen.getByRole('link', { name: '详情' })).toHaveAttribute('href', '/news/42')
  })
})
