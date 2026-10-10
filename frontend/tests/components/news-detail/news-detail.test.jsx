/**
 * Behaviour tests for the news-detail subcomponents extracted from
 * NewsDetail.jsx during the P2 refactor. Pure presentational — we verify
 * accessible roles, key labels, and click handlers.
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

import FetchArticleCard from '@/components/news-detail/FetchArticleCard'
import FetchArticleSpinner from '@/components/news-detail/FetchArticleSpinner'
import ErrorBanner from '@/components/news-detail/ErrorBanner'
import FullContentSection from '@/components/news-detail/FullContentSection'

describe('FetchArticleCard', () => {
  it('renders the CTA copy and triggers onFetch when clicked', () => {
    const onFetch = vi.fn()
    render(<FetchArticleCard onFetch={onFetch} />)

    expect(screen.getByText('获取完整原文')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '获取完整原文' }))
    expect(onFetch).toHaveBeenCalledWith()
  })
})

describe('FetchArticleSpinner', () => {
  it('renders the loading copy', () => {
    render(<FetchArticleSpinner />)
    expect(screen.getByText(/正在获取原文内容/)).toBeInTheDocument()
  })
})

describe('ErrorBanner', () => {
  it('renders the message and fires onRetry', () => {
    const onRetry = vi.fn()
    render(<ErrorBanner message="抓取失败：超时" onRetry={onRetry} />)

    expect(screen.getByRole('alert')).toHaveTextContent('抓取失败：超时')
    fireEvent.click(screen.getByRole('button', { name: '重试' }))
    expect(onRetry).toHaveBeenCalledWith()
  })
})

describe('FullContentSection', () => {
  const baseNews = {
    full_content: 'English source body',
    full_content_zh: '',
  }

  function renderSection(overrides = {}) {
    const props = {
      news: baseNews,
      translating: false,
      translationPaused: false,
      translateError: '',
      translationProgress: '',
      showOriginal: false,
      onToggleOriginal: vi.fn(),
      onTranslate: vi.fn(),
      onRetryTranslate: vi.fn(),
      onResumeTranslation: vi.fn(),
      onStopTranslation: vi.fn(),
      onRefetch: vi.fn(),
      refetching: false,
      onCancelRefetch: vi.fn(),
      ...overrides,
    }
    return { props, ...render(<FullContentSection {...props} />) }
  }

  it('shows "翻译为中文" button when no translation exists', () => {
    renderSection()
    expect(screen.getByRole('button', { name: '翻译为中文' })).toBeInTheDocument()
    // No LangToggle when there's no Chinese translation yet
    expect(screen.queryByRole('group', { name: '切换语言' })).not.toBeInTheDocument()
  })

  it('labels a public copy and hides paid personal regeneration without an account', () => {
    renderSection({ news: { ...baseNews, full_content_zh: '共享文本', full_content_zh_scope: 'shared', full_translation_personal_available: false } })
    expect(screen.getByText('共享译文')).toBeInTheDocument()
    expect(screen.getByText(/不消耗你的模型额度/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '生成个人译文' })).not.toBeInTheDocument()
  })

  it('offers an explicit personal version when a subscription is available', () => {
    const { props } = renderSection({ news: { ...baseNews, full_content_zh: '共享文本', full_content_zh_scope: 'shared', full_translation_personal_available: true } })
    fireEvent.click(screen.getByRole('button', { name: '生成个人译文' }))
    expect(props.onTranslate).toHaveBeenCalledOnce()
  })

  it('shows a shared wait message rather than another users private progress', () => {
    renderSection({ translating: true, translationWaitingShared: true })
    expect(screen.getByText('共享译文正在生成，完成后自动显示…')).toBeInTheDocument()
    expect(screen.getByText(/正在复用其他读者发起的翻译/)).toBeInTheDocument()
    expect(screen.queryByText(/其他用户的私有进度：/)).not.toBeInTheDocument()
  })

  it('shows "重新翻译" + lang toggle when translation present', () => {
    const news = { ...baseNews, full_content_zh: '中文译文' }
    renderSection({ news })
    expect(screen.getByRole('button', { name: '重新翻译' })).toBeInTheDocument()
    expect(screen.getByRole('group', { name: '切换语言' })).toBeInTheDocument()
    expect(screen.getByText('已有中文译文')).toBeInTheDocument()
  })

  it('clicking 翻译为中文 calls onTranslate', () => {
    const { props } = renderSection()
    fireEvent.click(screen.getByRole('button', { name: '翻译为中文' }))
    expect(props.onTranslate).toHaveBeenCalledTimes(1)
  })

  it('renders the spinner card while translating with no progress yet', () => {
    renderSection({ translating: true, translationProgress: '' })
    expect(screen.getByText('正在翻译全文…')).toBeInTheDocument()
    expect(screen.getByText(/取消会阻止后续请求与保存/)).toBeInTheDocument()
  })

  it('sends explicit translation cancellation rather than claiming server work was stopped by disconnect', () => {
    const { props } = renderSection({ translating: true, translationProgress: 'partial' })
    fireEvent.click(screen.getByRole('button', { name: '取消全文翻译' }))
    expect(props.onStopTranslation).toHaveBeenCalledOnce()
  })

  it('exposes an explicit resume action after translation updates are paused', () => {
    const { props } = renderSection({ translationPaused: true })
    expect(screen.getByText(/本页已停止接收更新/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '翻译为中文' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '继续接收翻译进度' }))
    expect(props.onResumeTranslation).toHaveBeenCalledOnce()
  })

  it('renders streaming progress when translating with partial content', () => {
    renderSection({ translating: true, translationProgress: '部分译文...' })
    expect(screen.getByText('AI 正在翻译…')).toBeInTheDocument()
  })

  it('shows ErrorBanner when translateError is non-empty', () => {
    renderSection({ translateError: '翻译失败：429' })
    expect(screen.getByRole('alert')).toHaveTextContent('翻译失败：429')
  })

  it('lang toggle items reflect showOriginal via aria-checked', () => {
    // shadcn ToggleGroup is built on Radix → exposes role="radio" /
    // aria-checked instead of role="button" / aria-pressed. This is a
    // semantically richer pattern and the migration intentionally adopts it.
    const news = { ...baseNews, full_content_zh: '中文译文' }
    renderSection({ news, showOriginal: false })
    expect(screen.getByRole('radio', { name: '切换中文' })).toHaveAttribute('aria-checked', 'true')
    expect(screen.getByRole('radio', { name: '切换英文' })).toHaveAttribute('aria-checked', 'false')
  })

  it('shows English content when showOriginal=true', () => {
    const news = { full_content: 'EN body', full_content_zh: '中文译文' }
    renderSection({ news, showOriginal: true })
    expect(screen.getByText('EN body')).toBeInTheDocument()
  })

  it('shows Chinese content when showOriginal=false and translation exists', () => {
    const news = { full_content: 'EN body', full_content_zh: '中文译文' }
    renderSection({ news, showOriginal: false })
    expect(screen.getByText('中文译文')).toBeInTheDocument()
  })
})
