import { useState } from 'react'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import NewsChatAssistant from '@/components/NewsChatAssistant'

const chatState = vi.hoisted(() => ({ stopWaiting: vi.fn() }))

vi.mock('@/hooks/useChat', () => ({
  useChat: vi.fn(() => ({
    messages: [], input: '', setInput: vi.fn(), isLoading: false, phase: 'idle',
    historyError: '', retryHistory: vi.fn(), handleSend: vi.fn(), doSend: vi.fn(),
    stopWaiting: chatState.stopWaiting, confirmingClear: false, isClearing: false,
    clearError: '', requestClearChat: vi.fn(), cancelClear: vi.fn(), confirmClear: vi.fn(),
    uncertainTurn: null, checkPendingTurn: vi.fn(), resendUncertainTurn: vi.fn(),
    webSearch: false, toggleWebSearch: vi.fn(),
  })),
}))

vi.mock('@/hooks/useSuggestedQuestions', () => ({
  useSuggestedQuestions: () => ({ questions: [], loading: false, refresh: vi.fn() }),
}))

vi.mock('@/components/chat/ChatBubbleButton', () => ({
  default: ({ onOpen, buttonRef }) => <button ref={buttonRef} type="button" onClick={onOpen}>打开浮动助手</button>,
}))
vi.mock('@/components/chat/ChatHeader', () => ({
  default: ({ onClose }) => <button type="button" onClick={onClose}>关闭助手</button>,
}))
vi.mock('@/components/chat/ChatMessageList', () => ({ default: () => null }))
vi.mock('@/components/chat/ChatInput', () => ({ default: () => null }))
vi.mock('@/components/chat/ClearChatDialog', () => ({ default: () => null }))
vi.mock('@/components/chat/Confetti', () => ({ default: () => null }))

function ControlledHarness() {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>外部打开助手</button>
      <NewsChatAssistant newsId={21} open={open} onOpenChange={setOpen} />
    </>
  )
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('NewsChatAssistant open state', () => {
  it('keeps the floating entry working in uncontrolled mode', async () => {
    render(<NewsChatAssistant newsId={21} />)

    fireEvent.click(screen.getByRole('button', { name: '打开浮动助手' }))
    expect(screen.getByRole('dialog', { name: 'AI 助手小闻' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '关闭助手' }))
    expect(screen.queryByRole('dialog', { name: 'AI 助手小闻' })).not.toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole('button', { name: '打开浮动助手' })).toHaveFocus())
    expect(chatState.stopWaiting).toHaveBeenCalledOnce()
  })

  it('opens and closes through the controlled page state', () => {
    render(<ControlledHarness />)

    fireEvent.click(screen.getByRole('button', { name: '外部打开助手' }))
    expect(screen.getByRole('dialog', { name: 'AI 助手小闻' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '关闭助手' }))
    expect(screen.queryByRole('dialog', { name: 'AI 助手小闻' })).not.toBeInTheDocument()
  })

  it('restores the controlled floating entry after the dialog closes', async () => {
    render(<ControlledHarness />)

    fireEvent.click(screen.getByRole('button', { name: '打开浮动助手' }))
    expect(screen.getByRole('dialog', { name: 'AI 助手小闻' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '关闭助手' }))
    await waitFor(() => expect(screen.getByRole('button', { name: '打开浮动助手' })).toHaveFocus())
  })

  it('does not mutate internal state when a controlled parent keeps it closed', () => {
    const onOpenChange = vi.fn()
    render(<NewsChatAssistant newsId={21} open={false} onOpenChange={onOpenChange} />)

    fireEvent.click(screen.getByRole('button', { name: '打开浮动助手' }))
    expect(onOpenChange).toHaveBeenCalledWith(true)
    expect(screen.queryByRole('dialog', { name: 'AI 助手小闻' })).not.toBeInTheDocument()
  })
})
