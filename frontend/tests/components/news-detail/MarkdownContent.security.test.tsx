import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import MarkdownContent from '@/components/news-detail/MarkdownContent'

describe('MarkdownContent untrusted HTML and URLs', () => {
  it('does not create executable DOM from raw HTML, code, or javascript links', () => {
    const markdown = [
      '<script>window.compromised = true</script>',
      '<img src="x" onerror="window.compromised = true">',
      '<div onclick="window.compromised = true">raw HTML</div>',
      '[danger](javascript:window.compromised=true)',
      '',
      '```html',
      '<script>window.compromised = true</script>',
      '```',
      '',
      '[safe external](https://example.test/article)',
    ].join('\n')
    const { container } = render(<MarkdownContent content={markdown} />)

    expect(container.querySelector('script, img, iframe, object, embed')).toBeNull()
    expect(container.querySelector('[onclick], [onerror]')).toBeNull()
    expect([...container.querySelectorAll('a')].some((link) => /^javascript:/i.test(link.getAttribute('href') ?? ''))).toBe(false)
    expect(container.querySelector('pre')?.textContent).toContain('<script>window.compromised = true</script>')

    const safeLink = [...container.querySelectorAll('a')].find((link) => link.textContent === 'safe external')
    expect(safeLink?.getAttribute('href')).toBe('https://example.test/article')
    expect(safeLink?.getAttribute('target')).toBe('_blank')
    expect(safeLink?.getAttribute('rel')).toBe('noopener noreferrer')
  })
})
