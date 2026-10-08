import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AuthContext, AuthProvider, useAuth } from '@/context/AuthContext'

vi.mock('@/services/api', () => ({
  fetchProviderComparisons: vi.fn(),
  createProviderComparison: vi.fn(),
  retestProviderComparison: vi.fn(),
  fetchMe: vi.fn(),
  fetchCsrfToken: vi.fn(),
  loginUser: vi.fn(),
  logoutUser: vi.fn(),
  registerUser: vi.fn(),
}))

vi.mock('@/components/news-detail/MarkdownContent', () => ({
  default: ({ content }) => <div data-testid="markdown-preview">{content}</div>,
}))

import {
  fetchProviderComparisons,
  createProviderComparison,
  retestProviderComparison,
  fetchMe,
  logoutUser,
} from '@/services/api'
import { queryClient } from '@/services/queryClient'
import { providerComparisonKeys } from '@/services/providerComparisonsQueries'
import ProviderComparisons from '@/pages/ProviderComparisons'

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

function renderPage(options = {}) {
  const client = options.client ?? new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  let authState = {
    user: options.user === undefined ? { id: 1, username: 'tester' } : options.user,
    loading: options.loading ?? false,
  }
  const authValue = () => ({
    ...authState,
    login: vi.fn(),
    register: vi.fn(),
    logout: vi.fn(),
    refresh: vi.fn(),
  })
  const tree = () => (
    <QueryClientProvider client={client}>
      <AuthContext.Provider value={authValue()}>
        <MemoryRouter initialEntries={["/provider-comparisons"]}>
          <Routes>
            <Route path="/provider-comparisons" element={<ProviderComparisons />} />
          </Routes>
        </MemoryRouter>
      </AuthContext.Provider>
    </QueryClientProvider>
  )
  const view = render(tree())
  return {
    ...view,
    client,
    setAuth: (next) => {
      authState = { ...authState, ...next }
      view.rerender(tree())
    },
  }
}

beforeEach(() => {
  fetchProviderComparisons.mockResolvedValue(apiPayload)
  createProviderComparison.mockResolvedValue({ id: 102 })
  retestProviderComparison.mockResolvedValue({ id: 101 })
})

afterEach(() => {
  vi.clearAllMocks()
  queryClient.clear()
})

function AuthLifecycleControls() {
  const auth = useAuth()
  return (
    <div>
      <span>{auth.user?.username ?? 'logged-out'}</span>
      <button type="button" onClick={() => void auth.refresh()}>refresh identity</button>
      <button type="button" onClick={() => void auth.logout()}>logout</button>
    </div>
  )
}

describe('ProviderComparisons page', () => {
  it('waits for auth hydration, hides data on logout, and never queries an anonymous key', async () => {
    const page = renderPage({ user: null, loading: true })

    expect(screen.getByText('正在确认登录状态...')).toBeInTheDocument()
    expect(fetchProviderComparisons).not.toHaveBeenCalled()

    page.setAuth({ user: { id: 1, username: 'tester' }, loading: false })
    expect(await screen.findByText('Example comparison')).toBeInTheDocument()
    expect(fetchProviderComparisons).toHaveBeenCalledTimes(1)

    page.setAuth({ user: null, loading: false })
    expect(screen.queryByText('Example comparison')).not.toBeInTheDocument()
    expect(screen.getByText('请先登录后查看 Provider 对比记录。')).toBeInTheDocument()
    expect(fetchProviderComparisons).toHaveBeenCalledTimes(1)
    expect(page.client.getQueryCache().findAll({ queryKey: ['providerComparisons'] }).some((query) =>
      query.queryKey[2]?.viewerId === 'anonymous')).toBe(false)
  })

  it('clears Provider cache on authenticated identity change and logout', async () => {
    queryClient.clear()
    fetchMe.mockResolvedValueOnce({ id: 1, username: 'viewer-a' })
    logoutUser.mockResolvedValue(undefined)
    const view = render(
      <QueryClientProvider client={queryClient}>
        <AuthProvider><AuthLifecycleControls /></AuthProvider>
      </QueryClientProvider>,
    )
    expect(await screen.findByText('viewer-a')).toBeInTheDocument()
    queryClient.setQueryData(providerComparisonKeys.list('zh', 1), apiPayload)
    queryClient.setQueryData(['chatgptSubscription', 'status', 1], { connections: [{ id: 'private-account-a' }] })

    fetchMe.mockResolvedValueOnce({ id: 2, username: 'viewer-b' })
    fireEvent.click(screen.getByRole('button', { name: 'refresh identity' }))
    expect(await screen.findByText('viewer-b')).toBeInTheDocument()
    expect(queryClient.getQueryCache().findAll({ queryKey: ['providerComparisons'] })).toHaveLength(0)
    expect(queryClient.getQueryCache().findAll({ queryKey: ['chatgptSubscription'] })).toHaveLength(0)

    queryClient.setQueryData(providerComparisonKeys.list('zh', 2), apiPayload)
    queryClient.setQueryData(['chatgptSubscription', 'status', 2], { connections: [{ id: 'private-account-b' }] })
    fireEvent.click(screen.getByRole('button', { name: 'logout' }))
    expect(await screen.findByText('logged-out')).toBeInTheDocument()
    expect(queryClient.getQueryCache().findAll({ queryKey: ['providerComparisons'] })).toHaveLength(0)
    expect(queryClient.getQueryCache().findAll({ queryKey: ['chatgptSubscription'] })).toHaveLength(0)
    view.unmount()
  })

  it('does not let a late create completion from viewer A clear viewer B form state', async () => {
    let resolveCreate
    createProviderComparison.mockImplementationOnce(() => new Promise((resolve) => { resolveCreate = resolve }))
    const page = renderPage()
    await screen.findByText('Example comparison')

    fireEvent.change(screen.getByLabelText('news_id'), { target: { value: '88' } })
    fireEvent.click(screen.getByRole('button', { name: '发起对比' }))
    await waitFor(() => expect(createProviderComparison).toHaveBeenCalledTimes(1))
    const signal = createProviderComparison.mock.calls[0][1]

    page.setAuth({ user: { id: 2, username: 'viewer-b' }, loading: false })
    await screen.findByText('Example comparison')
    expect(signal.aborted).toBe(true)
    fireEvent.change(screen.getByLabelText('news_id'), { target: { value: '99' } })
    resolveCreate({ id: 999 })

    await waitFor(() => expect(screen.getByLabelText('news_id')).toHaveValue('99'))
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('loads and renders adapted sites, metrics and provider comparison cards', async () => {
    renderPage()

    expect(screen.getByText('Provider 对比')).toBeInTheDocument()
    expect(fetchProviderComparisons).toHaveBeenCalledWith({}, expect.any(AbortSignal))

    expect(await screen.findByText('Example comparison')).toBeInTheDocument()
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
      expect(createProviderComparison).toHaveBeenCalledWith({ news_id: '88' }, expect.any(AbortSignal))
    })
    expect(fetchProviderComparisons).toHaveBeenCalledTimes(2)
  })

  it('submits a url comparison when url is provided', async () => {
    renderPage()

    const url = 'https://example.com/articles/1'
    fireEvent.change(screen.getByLabelText('url'), { target: { value: url } })
    fireEvent.click(screen.getByRole('button', { name: '发起对比' }))

    await waitFor(() => {
      expect(createProviderComparison).toHaveBeenCalledWith({ url }, expect.any(AbortSignal))
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
      expect(retestProviderComparison).toHaveBeenCalledWith(102, expect.any(AbortSignal))
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
      expect(retestProviderComparison).toHaveBeenCalledWith(202, expect.any(AbortSignal))
    })
  })

  it('lets provider retests run and stop independently, and locks duplicate create submissions', async () => {
    const requests = new Map()
    retestProviderComparison.mockImplementation((id, signal) => new Promise((resolve, reject) => {
      requests.set(id, { resolve, reject, signal })
      signal.addEventListener('abort', () => reject(new DOMException('Request aborted', 'AbortError')), { once: true })
    }))
    renderPage()

    await screen.findByText('Example comparison')
    fireEvent.change(screen.getByLabelText('news_id'), { target: { value: '88' } })
    const createButton = screen.getByRole('button', { name: '发起对比' })
    fireEvent.click(createButton)
    fireEvent.click(createButton)
    await waitFor(() => expect(createProviderComparison).toHaveBeenCalledTimes(1))

    fireEvent.click(screen.getByRole('button', { name: '重新测试 JINA' }))
    fireEvent.click(screen.getByRole('button', { name: '重新测试 SCRAPY' }))
    await waitFor(() => expect(requests.size).toBe(2))

    const jina = requests.get(101)
    const scrapy = requests.get(102)
    expect(jina.signal).not.toBe(scrapy.signal)
    fireEvent.click(screen.getByRole('button', { name: '停止等待 JINA 重测' }))
    expect(jina.signal.aborted).toBe(true)
    expect(scrapy.signal.aborted).toBe(false)

    scrapy.resolve({ run_id: 'run-retest', count: 1, results: [] })
    await waitFor(() => expect(screen.queryByRole('button', { name: '停止等待 SCRAPY 重测' })).not.toBeInTheDocument())
    await screen.findByRole('button', { name: '重新测试 JINA' })
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('aborts create and retest waits on unmount', async () => {
    let createSignal
    let retestSignal
    createProviderComparison.mockImplementationOnce((_payload, signal) => {
      createSignal = signal
      return new Promise(() => {})
    })
    retestProviderComparison.mockImplementationOnce((_id, signal) => {
      retestSignal = signal
      return new Promise(() => {})
    })
    const page = renderPage()
    await screen.findByText('Example comparison')
    fireEvent.change(screen.getByLabelText('news_id'), { target: { value: '88' } })
    fireEvent.click(screen.getByRole('button', { name: '发起对比' }))
    fireEvent.click(screen.getByRole('button', { name: '重新测试 JINA' }))
    await waitFor(() => {
      expect(createSignal).toBeInstanceOf(AbortSignal)
      expect(retestSignal).toBeInstanceOf(AbortSignal)
    })

    page.unmount()
    expect(createSignal.aborted).toBe(true)
    expect(retestSignal.aborted).toBe(true)
  })

  it('ignores a late retest error after switching from viewer A to viewer B', async () => {
    let rejectRetest
    retestProviderComparison.mockImplementationOnce(() => new Promise((_resolve, reject) => { rejectRetest = reject }))
    const page = renderPage()
    await screen.findByText('Example comparison')
    fireEvent.click(screen.getByRole('button', { name: '重新测试 JINA' }))
    await waitFor(() => expect(retestProviderComparison).toHaveBeenCalledTimes(1))
    const signal = retestProviderComparison.mock.calls[0][1]

    page.setAuth({ user: { id: 2, username: 'viewer-b' }, loading: false })
    await screen.findByText('Example comparison')
    expect(signal.aborted).toBe(true)
    rejectRetest(new Error('Viewer A retest failed late'))

    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument())
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
