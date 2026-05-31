import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import ChatMessageList from './ChatMessageList'

vi.mock('markstream-react', () => ({
  default: function NodeRenderer({ content }) {
    return <div data-testid="md">{content}</div>
  },
}))

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
    expect(screen.getByTestId('md')).toHaveTextContent('Hello there!')
  })
})
