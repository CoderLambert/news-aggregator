import { describe, it, expect, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import ChatMessageList from './ChatMessageList'

describe('ChatMessageList', () => {
  it('shows mascot loader while loading-history', () => {
    const { container } = render(
      <ChatMessageList messages={[]} phase="loading-history" onSuggestionClick={() => {}} />,
    )
    // mascot SVG should be the only thing
    expect(container.querySelector('svg[aria-label="小闻 AI 助手"]')).toBeInTheDocument()
    // No suggestions when loading
    expect(screen.queryByText(/帮我用一句话总结/)).not.toBeInTheDocument()
  })

  it('renders empty state with mascot + greeting + 3 suggested questions', () => {
    render(<ChatMessageList messages={[]} phase="idle" onSuggestionClick={() => {}} />)
    expect(screen.getByText(/嗨，我是小闻/)).toBeInTheDocument()
    expect(screen.getByText(/帮我用一句话总结这篇文章/)).toBeInTheDocument()
    expect(screen.getByText(/最重要的三个观点/)).toBeInTheDocument()
    expect(screen.getByText(/背景知识/)).toBeInTheDocument()
  })

  it('clicking a suggestion calls onSuggestionClick with the question text', async () => {
    const user = userEvent.setup()
    const onSuggestionClick = vi.fn()
    render(<ChatMessageList messages={[]} phase="idle" onSuggestionClick={onSuggestionClick} />)

    const btn = screen.getByText(/帮我用一句话总结这篇文章/)
    await user.click(btn)

    expect(onSuggestionClick).toHaveBeenCalledTimes(1)
    expect(onSuggestionClick).toHaveBeenCalledWith('帮我用一句话总结这篇文章')
  })

  it('renders thinking dots when assistant message is empty', () => {
    const messages = [
      { role: 'user', content: 'hi' },
      { role: 'assistant', content: '' },
    ]
    const { container } = render(
      <ChatMessageList messages={messages} phase="thinking" onSuggestionClick={() => {}} />,
    )
    expect(container.querySelectorAll('.thinking-dot')).toHaveLength(3)
  })

  it('renders assistant content via markdown renderer when content present', () => {
    const messages = [
      { role: 'user', content: 'hi' },
      { role: 'assistant', content: 'Hello there!' },
    ]
    render(<ChatMessageList messages={messages} phase="streaming" onSuggestionClick={() => {}} />)
    expect(screen.getByText('Hello there!')).toBeInTheDocument()
  })

  it('copies code from a streamed assistant Markdown message without changing its text', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText }, writable: true })
    const streamedMarkdown = '```ts\nconst answer: string = "OK"\n```'
    render(<ChatMessageList messages={[{ role: 'assistant', content: streamedMarkdown }]} phase="idle" />)

    fireEvent.click(screen.getByRole('button', { name: /复制代码/ }))
    await waitFor(() => expect(writeText).toHaveBeenCalledOnce())
    expect(writeText.mock.calls[0][0]).toContain('const answer: string = "OK"')
  })

  describe('refresh suggestions ("换一批")', () => {
    it('renders a refresh button when onRefreshSuggestions is provided', () => {
      render(
        <ChatMessageList
          messages={[]}
          phase="idle"
          onSuggestionClick={() => {}}
          onRefreshSuggestions={() => {}}
        />,
      )
      expect(screen.getByRole('button', { name: /换一批/ })).toBeInTheDocument()
    })

    it('does NOT render the refresh button when onRefreshSuggestions is missing', () => {
      // Backward compat — old callers without refresh capability see no button
      render(<ChatMessageList messages={[]} phase="idle" onSuggestionClick={() => {}} />)
      expect(screen.queryByRole('button', { name: /换一批/ })).not.toBeInTheDocument()
    })

    it('clicking refresh calls onRefreshSuggestions', async () => {
      const user = userEvent.setup()
      const onRefreshSuggestions = vi.fn()
      render(
        <ChatMessageList
          messages={[]}
          phase="idle"
          onSuggestionClick={() => {}}
          onRefreshSuggestions={onRefreshSuggestions}
        />,
      )
      await user.click(screen.getByRole('button', { name: /换一批/ }))
      expect(onRefreshSuggestions).toHaveBeenCalledTimes(1)
    })

    it('refresh button is disabled and shows spinner state when refreshing=true', () => {
      render(
        <ChatMessageList
          messages={[]}
          phase="idle"
          onSuggestionClick={() => {}}
          onRefreshSuggestions={() => {}}
          refreshingSuggestions
        />,
      )
      const btn = screen.getByRole('button', { name: /换一批/ })
      expect(btn).toBeDisabled()
    })

    it('does NOT render refresh button when there are messages (only in empty state)', () => {
      render(
        <ChatMessageList
          messages={[{ role: 'user', content: 'hi' }]}
          phase="idle"
          onSuggestionClick={() => {}}
          onRefreshSuggestions={() => {}}
        />,
      )
      expect(screen.queryByRole('button', { name: /换一批/ })).not.toBeInTheDocument()
    })
  })
})
