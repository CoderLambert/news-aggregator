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

describe('MarkdownContent article readability', () => {
  it('turns legacy full-width paragraph separators into paragraphs and keeps Markdown structure', () => {
    const { container } = render(
      <MarkdownContent
        content={'## 制度边界\n\n第一段正文。\u3000\u3000第二段正文。\n\n- 第一项\n- 第二项\n\n段内第一行  \n段内第二行'}
        legacySummarySpacing
      />,
    )

    expect(screen.getByRole('heading', { name: '制度边界' })).toBeInTheDocument()
    expect(screen.getByText('第一段正文。')).toBeInTheDocument()
    expect(screen.getByText('第二段正文。')).toBeInTheDocument()
    expect(within(screen.getByRole('list')).getAllByRole('listitem')).toHaveLength(2)
    expect(container.querySelectorAll('br')).toHaveLength(1)
    expect(container.querySelector('p')).toHaveClass('text-neutral-700')
  })

  it('leaves full-width spaces untouched by default', () => {
    const { container } = render(<MarkdownContent content={'第一段正文。\u3000\u3000第二段正文。'} />)

    expect(container.querySelectorAll('p')).toHaveLength(1)
    expect(container.querySelector('p').textContent).toBe('第一段正文。\u3000\u3000第二段正文。')
  })

  it('preserves full-width spaces in inline code', () => {
    const { container } = render(<MarkdownContent content={'前缀 `alpha\u3000\u3000beta` 后缀'} legacySummarySpacing />)

    expect(container.querySelector('p code').textContent).toBe('alpha\u3000\u3000beta')
    expect(container.querySelectorAll('p')).toHaveLength(1)
  })

  it('preserves indented code blocks', () => {
    const { container } = render(<MarkdownContent content={'    alpha\u3000\u3000beta\n    next'} legacySummarySpacing />)

    expect(container.querySelector('pre code').textContent).toBe('alpha\u3000\u3000beta\nnext')
    expect(container.querySelectorAll('p')).toHaveLength(0)
  })

  it('preserves fenced code inside a blockquote', () => {
    const { container } = render(
      <MarkdownContent content={'> 引用\n>\n> ```js\n> const value = "alpha\u3000\u3000beta"\n> ```'} legacySummarySpacing />,
    )

    expect(container.querySelector('blockquote')).toBeInTheDocument()
    expect(container.querySelector('blockquote pre code').textContent).toBe('const value = "alpha\u3000\u3000beta"')
  })

  it('preserves fenced code inside a list item', () => {
    const { container } = render(
      <MarkdownContent content={'- sample:\n  ```txt\n  alpha\u3000\u3000beta\n  ```'} legacySummarySpacing />,
    )

    expect(container.querySelector('ul li')).toBeInTheDocument()
    expect(container.querySelector('li pre code').textContent).toBe('alpha\u3000\u3000beta')
  })
})
