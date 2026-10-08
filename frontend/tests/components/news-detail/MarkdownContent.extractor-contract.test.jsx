import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import process from 'node:process'
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import MarkdownContent from '@/components/news-detail/MarkdownContent'

const extractorFixture = JSON.parse(readFileSync(
  resolve(process.cwd(), '../backend/api/tests/full_article_renderer_contract.json'),
  'utf8',
))

describe('article extractor to Markdown renderer contract', () => {
  it('renders extractor paragraphs, hard breaks, lists, and code as semantic blocks', () => {
    const { container } = render(<MarkdownContent content={extractorFixture.markdown} />)

    expect(screen.getByRole('heading', { name: '正文结构' })).toBeInTheDocument()
    const paragraphs = container.querySelectorAll('p')
    expect(paragraphs).toHaveLength(2)
    expect(paragraphs[0].textContent).toBe('第一段第一行\n同段第二行')
    expect(paragraphs[0].querySelector('br')).toBeInTheDocument()
    expect(paragraphs[1].textContent).toBe('第二段。')
    expect(container.querySelectorAll('ul li')).toHaveLength(2)
    expect(container.querySelector('pre code').textContent).toBe('const value = "alpha\u3000\u3000beta";')
  })
})
