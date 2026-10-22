import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import FullContentSection from '@/components/news-detail/FullContentSection'
import type { NewsDetail } from '@/types/news'

vi.mock('@/components/news-detail/MarkdownContent', () => ({
  default: ({ content }: { content: string }) => <div data-testid="article-body">{content}</div>,
}))

const history = [
  { result_id: 41, task_id: '11111111-1111-4111-8111-111111111111', content: '当前个人中文', model: 'Flash',
    source_hash: 'current-hash', current_match: true, source_title: '当前标题', source_revision: 2, completed_at: '' },
  { result_id: 42, task_id: '22222222-2222-4222-8222-222222222222', content: '旧版本个人中文', model: 'Flash',
    source_hash: 'old-hash', current_match: false, source_title: '旧版标题', source_revision: 1, completed_at: '' },
]

function props(selectedPrivateResultId: number | null, onSelectPrivateResult: (id: number | null) => void) {
  return {
    news: {
      id: 7, title: '当前文章标题', source_language: 'en', full_content: '# 原文',
      full_content_state: 'complete', full_content_zh: '当前推荐中文',
      full_content_zh_private_history: history,
    } as unknown as NewsDetail,
    translating: false, translationPaused: false, translateError: '', translationProgress: '',
    showOriginal: false, onToggleOriginal: vi.fn(), onTranslate: vi.fn(), onRetryTranslate: vi.fn(),
    onResumeTranslation: vi.fn(), onStopTranslation: vi.fn(), onRefetch: vi.fn(), refetching: false,
    onCancelRefetch: vi.fn(), selectedPrivateResultId, onSelectPrivateResult,
  }
}

describe('saved private translation reader selection', () => {
  it('round-trips an exact saved result and labels stale source version', () => {
    const onSelect = vi.fn()
    const initial = props(null, onSelect)
    const rendered = render(<FullContentSection {...initial} />)
    expect(screen.getByTestId('article-body')).toHaveTextContent('当前推荐中文')

    fireEvent.click(screen.getByText('历史译文', { exact: true }))
    fireEvent.change(screen.getByRole('combobox', { name: '选择历史译文' }), { target: { value: '42' } })
    expect(onSelect).toHaveBeenCalledWith(42)

    rendered.rerender(<FullContentSection {...props(42, onSelect)} />)
    expect(screen.getByTestId('article-body')).toHaveTextContent('旧版本个人中文')
    expect(screen.getByRole('status')).toHaveTextContent('旧版标题')
    expect(screen.getByRole('combobox', { name: '选择历史译文' })).toHaveValue('42')
  })
})


it('copies the selected saved translation instead of the current recommendation', async () => {
  const previous = Object.getOwnPropertyDescriptor(navigator, 'clipboard')
  const writeText = vi.fn().mockResolvedValue(undefined)
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } })
  try {
    render(<FullContentSection {...props(42, vi.fn())} />)
    await act(async () => fireEvent.click(screen.getByRole('button', { name: '复制全文' })))
    expect(writeText).toHaveBeenCalledWith('旧版本个人中文')
  } finally {
    if (previous) Object.defineProperty(navigator, 'clipboard', previous)
    else Reflect.deleteProperty(navigator, 'clipboard')
  }
})

it('labels an incomplete translation and keeps its draft until the reader explicitly selects original', async () => {
  const base = props(null, vi.fn())
  const task = {
    task_id: 'task-failed', request_id: 'request-failed', news_id: 7, generation: 1,
    status: 'failed' as const, progress: '尚未完成的中文草稿', error_code: 'incomplete_response',
    result: null, previous_result: null, retry_of: null, model_config_id: 'model', target_language: 'zh' as const,
  }
  const rendered = render(<FullContentSection {...base} privateTask={task} />)
  expect(screen.getByRole('status')).toHaveTextContent('翻译未完成')
  expect(screen.queryByTestId('article-body')).toBeNull()
  await waitFor(() => expect(screen.getByLabelText('未完成的译文')).toHaveTextContent('尚未完成的中文草稿'))
  rendered.rerender(<FullContentSection {...base} privateTask={task} showOriginal />)
  expect(screen.getByTestId('article-body')).toHaveTextContent('# 原文')
})

it('does not silently substitute original content when no failed draft remains', () => {
  const task = {
    task_id: 'task-failed', request_id: 'request-failed', news_id: 7, generation: 1,
    status: 'failed' as const, progress: '', error_code: 'translation_failed',
    result: null, previous_result: null, retry_of: null, model_config_id: 'model', target_language: 'zh' as const,
  }
  render(<FullContentSection {...props(null, vi.fn())} privateTask={task} />)
  expect(screen.getByRole('status')).toHaveTextContent('翻译未完成')
  expect(screen.queryByTestId('article-body')).toBeNull()
})
