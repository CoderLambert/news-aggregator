import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'

vi.mock('../services/api', () => ({
  fetchProviderComparisons: vi.fn(),
  createProviderComparison: vi.fn(),
  retestProviderComparison: vi.fn(),
}))

vi.mock('../components/news-detail/MarkdownContent', () => ({
  default: ({ content }) => <div data-testid="markdown-preview">{content}</div>,
}))

import {
  fetchProviderComparisons,
  createProviderComparison,
  retestProviderComparison,
} from '../services/api'
import ProviderComparisons from './ProviderComparisons'

const apiPayload = {
  count: 1,
  next: null,
  previous: null,
  adapted_sites: [
    { name: 'TechCrunch', domain: 'techcrunch.com', provider: 'scrapy', status: 'active' },
    { name: 'The Verge', domain: 'theverge.com', provider: 'scrapy', status: 'active' },
  ],
  metrics: {
    total: 11,
    success_rate: 0.82,
    avg_quality_score: 87.6,
    avg_duration_ms: 1432,
  },
  results: [
    {
      id: 101,
      news_id: 42,
      url: 'https://example.com/very/long/path/that/should/break/on/mobile',
      title: 'Example comparison',
      site_name: 'TechCrunch',
      created_at: '2026-06-02T00:00:00Z',
      providers: [
        {
          provider: 'jina',
          id: 101,
          status: 'success',
          quality_score: 91,
          content_length: 12345,
          duration_ms: 1200,
          error: '',
          markdown: '# Jina Preview\n正文',
        },
        {
          provider: 'scrapy',
          id: 102,
          status: 'failed',
          quality_score: 31,
          content_length: 500,
          duration_ms: 2500,
          error: 'timeout',
          markdown: 'Scrapy partial',
        },
      ],
    },
  ],
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/provider-comparisons"]}>
      <Routes>
        <Route path="/provider-comparisons" element={<ProviderComparisons />} />
      </Routes>
    </MemoryRouter>
  )
}

beforeEach(() => {
  fetchProviderComparisons.mockResolvedValue(apiPayload)
  createProviderComparison.mockResolvedValue({ id: 102 })
  retestProviderComparison.mockResolvedValue({ id: 101 })
})

afterEach(() => {
  vi.clearAllMocks()
})

describe('ProviderComparisons page', () => {
  it('loads and renders adapted sites, metrics and provider comparison cards', async () => {
    renderPage()

    expect(screen.getByText('Provider 对比')).toBeInTheDocument()
    expect(fetchProviderComparisons).toHaveBeenCalledWith({})

    expect(await screen.findByText('已适配站点')).toBeInTheDocument()
    expect(screen.getAllByText('TechCrunch').length).toBeGreaterThan(0)
    expect(screen.getByText('techcrunch.com')).toBeInTheDocument()
    expect(screen.getByText('总对比数')).toBeInTheDocument()
    expect(screen.getByText('11')).toBeInTheDocument()
    expect(screen.getByText('82%')).toBeInTheDocument()
    expect(screen.getByText('Example comparison')).toBeInTheDocument()
    expect(screen.getByText('news_id: 42')).toBeInTheDocument()

    expect(screen.getByText('JINA')).toBeInTheDocument()
    expect(screen.getByText('SCRAPY')).toBeInTheDocument()
    expect(screen.getByText('质量分 91')).toBeInTheDocument()
    expect(screen.getByText('内容 12,345 字')).toBeInTheDocument()
    expect(screen.getByText('耗时 1.2s')).toBeInTheDocument()
    expect(screen.getByText('timeout')).toBeInTheDocument()
    expect(screen.getAllByTestId('markdown-preview')[0]).toHaveTextContent('Jina Preview')
  })

  it('submits a news_id comparison and refreshes the list', async () => {
    renderPage()

    fireEvent.change(screen.getByLabelText('news_id'), { target: { value: '88' } })
    fireEvent.click(screen.getByRole('button', { name: '发起对比' }))

    await waitFor(() => {
      expect(createProviderComparison).toHaveBeenCalledWith({ news_id: '88' })
    })
    expect(fetchProviderComparisons).toHaveBeenCalledTimes(2)
  })

  it('submits a url comparison when url is provided', async () => {
    renderPage()

    const url = 'https://example.com/articles/1'
    fireEvent.change(screen.getByLabelText('url'), { target: { value: url } })
    fireEvent.click(screen.getByRole('button', { name: '发起对比' }))

    await waitFor(() => {
      expect(createProviderComparison).toHaveBeenCalledWith({ url })
    })
  })

  it('supports retesting a single provider row without hover-only controls', async () => {
    renderPage()

    const retestButtons = await screen.findAllByRole('button', { name: /重新测试/ })
    expect(retestButtons).toHaveLength(2)
    for (const button of retestButtons) {
      expect(button).toBeVisible()
      expect(button.className).not.toMatch(/opacity-0/)
    }

    fireEvent.click(screen.getByRole('button', { name: '重新测试 SCRAPY' }))

    await waitFor(() => {
      expect(retestProviderComparison).toHaveBeenCalledWith(102)
    })
    expect(fetchProviderComparisons).toHaveBeenCalledTimes(2)
  })

  it('renders the real backend flat row shape as one grouped comparison run', async () => {
    fetchProviderComparisons.mockResolvedValueOnce({
      count: 2,
      adapted_sites: [
        { name: 'Product Hunt', domains: ['producthunt.com'], provider: 'scrapy' },
      ],
      metrics: { total: 2, success: 1, failure: 1, success_rate: 0.5 },
      results: [
        {
          id: 201,
          run_id: 'run-1',
          news: 77,
          news_title: 'Real Backend Article',
          url: 'https://producthunt.com/products/demo',
          provider: 'jina',
          ok: true,
          markdown: '# Jina real markdown',
          quality_score: 0.92,
          content_length: 900,
          elapsed_ms: 1100,
          created_at: '2026-06-02T01:00:00Z',
        },
        {
          id: 202,
          run_id: 'run-1',
          news: 77,
          news_title: 'Real Backend Article',
          url: 'https://producthunt.com/products/demo',
          provider: 'scrapy_http',
          ok: false,
          error: 'validation_failed:too_short',
          markdown: '',
          quality_score: 0.2,
          content_length: 90,
          elapsed_ms: 2000,
          created_at: '2026-06-02T01:00:01Z',
        },
      ],
    })

    renderPage()

    expect(await screen.findByText('Product Hunt')).toBeInTheDocument()
    expect(screen.getByText('producthunt.com')).toBeInTheDocument()
    expect(screen.getByText('Real Backend Article')).toBeInTheDocument()
    expect(screen.getByText('news_id: 77')).toBeInTheDocument()
    expect(screen.getByText('JINA')).toBeInTheDocument()
    expect(screen.getByText('SCRAPY_HTTP')).toBeInTheDocument()
    expect(screen.getByText('success')).toBeInTheDocument()
    expect(screen.getByText('failed')).toBeInTheDocument()
    expect(screen.getByText('validation_failed:too_short')).toBeInTheDocument()
    expect(screen.getByText('质量分 0.92')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '重新测试 SCRAPY_HTTP' }))
    await waitFor(() => {
      expect(retestProviderComparison).toHaveBeenCalledWith(202)
    })
  })

  it('shows backend error messages from data.error and blocks ambiguous form input', async () => {
    createProviderComparison.mockRejectedValueOnce({
      response: { data: { error: 'URL must match an adapted Scrapy provider site' } },
    })
    renderPage()

    fireEvent.change(screen.getByLabelText('news_id'), { target: { value: '88' } })
    fireEvent.change(screen.getByLabelText('url'), { target: { value: 'https://github.com/example/demo' } })
    fireEvent.click(screen.getByRole('button', { name: '发起对比' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('请仅填写 news_id 或 url 之一')
    expect(createProviderComparison).not.toHaveBeenCalled()

    fireEvent.change(screen.getByLabelText('news_id'), { target: { value: '' } })
    fireEvent.click(screen.getByRole('button', { name: '发起对比' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('URL must match an adapted Scrapy provider site')
  })

  it('does not use news full_content or summary fields as provider markdown preview', async () => {
    fetchProviderComparisons.mockResolvedValueOnce({
      count: 1,
      adapted_sites: [],
      metrics: { total: 1 },
      results: [
        {
          id: 301,
          run_id: 'run-no-markdown',
          news: 90,
          news_title: 'No Provider Markdown',
          url: 'https://github.com/example/no-markdown',
          provider: 'scrapy_http',
          ok: false,
          content: 'NEWS SUMMARY MUST NOT BE PREVIEWED',
          full_content: 'NEWS FULL CONTENT MUST NOT BE PREVIEWED',
          markdown: '',
          error: 'validation_failed',
        },
      ],
    })

    renderPage()

    expect(await screen.findByText('No Provider Markdown')).toBeInTheDocument()
    expect(screen.getByText('暂无 Markdown 内容')).toBeInTheDocument()
    expect(screen.queryByText('NEWS SUMMARY MUST NOT BE PREVIEWED')).not.toBeInTheDocument()
    expect(screen.queryByText('NEWS FULL CONTENT MUST NOT BE PREVIEWED')).not.toBeInTheDocument()
  })
})
