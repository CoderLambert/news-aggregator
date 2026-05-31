/**
 * Behaviour tests for the news-detail subcomponents extracted from
 * NewsDetail.jsx during the P2 refactor. Pure presentational — we verify
 * accessible roles, key labels, and click handlers.
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

import FetchArticleCard from './FetchArticleCard'
import FetchArticleSpinner from './FetchArticleSpinner'
import ErrorBanner from './ErrorBanner'
import FullContentSection from './FullContentSection'

describe('FetchArticleCard', () => {
  it('renders the CTA copy and triggers onFetch when clicked', () => {
    const onFetch = vi.fn()
    render(<FetchArticleCard onFetch={onFetch} />)

    expect(screen.getByText('获取完整原文')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '加载原文' }))
    expect(onFetch).toHaveBeenCalledTimes(1)
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
    expect(onRetry).toHaveBeenCalledTimes(1)
  })
})

describe('FullContentSection', () => {
  const baseNews = {
    full_content: 'English source body',
  }

  function renderSection(overrides = {}) {
    const props = {
      news: baseNews,
      translating: false,
      translateError: '',
      translationProgress: '',
      showOriginal: false,
      onToggleOriginal: vi.fn(),
      onTranslate: vi.fn(),
      onRetryTranslate: vi.fn(),
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

  it('shows "重新翻译" + lang toggle when translation present', () => {
    const news = { ...baseNews, full_content_zh: '中文译文' }
    renderSection({ news })
    expect(screen.getByRole('button', { name: '重新翻译' })).toBeInTheDocument()
    expect(screen.getByRole('group', { name: '切换语言' })).toBeInTheDocument()
    expect(screen.getByText('已翻译')).toBeInTheDocument()
  })

  it('clicking 翻译为中文 calls onTranslate', () => {
    const { props } = renderSection()
    fireEvent.click(screen.getByRole('button', { name: '翻译为中文' }))
    expect(props.onTranslate).toHaveBeenCalledTimes(1)
  })

  it('renders the spinner card while translating with no progress yet', () => {
    renderSection({ translating: true, translationProgress: '' })
    expect(screen.getByText('正在使用 AI 翻译...')).toBeInTheDocument()
  })

  it('renders streaming progress when translating with partial content', () => {
    renderSection({ translating: true, translationProgress: '部分译文...' })
    expect(screen.getByText('AI 正在翻译...')).toBeInTheDocument()
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
