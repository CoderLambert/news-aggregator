import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import ChatHeader from './ChatHeader'

describe('ChatHeader', () => {
  function setup(props = {}) {
    const handlers = {
      onToggleFullscreen: vi.fn(),
      onClear: vi.fn(),
      onClose: vi.fn(),
    }
    render(<ChatHeader isFullscreen={false} {...handlers} {...props} />)
    return handlers
  }

  it('renders mascot avatar + name "小闻" + default subtitle', () => {
    const { container } = render(
      <ChatHeader
        isFullscreen={false}
        onToggleFullscreen={() => {}}
        onClear={() => {}}
        onClose={() => {}}
      />,
    )
    expect(screen.getByText('小闻')).toBeInTheDocument()
    expect(screen.getByText('读完文章再来聊')).toBeInTheDocument()
    expect(container.querySelector('svg[aria-label="小闻 AI 助手"]')).toBeInTheDocument()
  })

  it('subtitle reflects mood', () => {
    const { rerender } = render(
      <ChatHeader
        mood="think"
        isFullscreen={false}
        onToggleFullscreen={() => {}}
        onClear={() => {}}
        onClose={() => {}}
      />,
    )
    expect(screen.getByText('让我想想…')).toBeInTheDocument()

    rerender(
      <ChatHeader
        mood="talk"
        isFullscreen={false}
        onToggleFullscreen={() => {}}
        onClear={() => {}}
        onClose={() => {}}
      />,
    )
    expect(screen.getByText('正在回答你～')).toBeInTheDocument()

    rerender(
      <ChatHeader
        mood="confused"
        isFullscreen={false}
        onToggleFullscreen={() => {}}
        onClear={() => {}}
        onClose={() => {}}
      />,
    )
    expect(screen.getByText('咦，好像出了点问题')).toBeInTheDocument()
  })

  it('mascot data-mood prop is forwarded', () => {
    const { container } = render(
      <ChatHeader
        mood="happy"
        isFullscreen={false}
        onToggleFullscreen={() => {}}
        onClear={() => {}}
        onClose={() => {}}
      />,
    )
    expect(container.querySelector('svg')).toHaveAttribute('data-mood', 'happy')
  })

  it('action buttons fire their callbacks', async () => {
    const user = userEvent.setup()
    const handlers = setup()
    await user.click(screen.getByLabelText('全屏观看'))
    await user.click(screen.getByLabelText('清空对话'))
    await user.click(screen.getByLabelText('关闭对话窗口'))
    expect(handlers.onToggleFullscreen).toHaveBeenCalled()
    expect(handlers.onClear).toHaveBeenCalled()
    expect(handlers.onClose).toHaveBeenCalled()
  })
})
