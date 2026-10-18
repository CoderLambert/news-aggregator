import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import NewsChatAssistant from '@/components/NewsChatAssistant'

const calls = vi.hoisted(() => ({
  send: vi.fn(() => Promise.resolve(true)),
  stop: vi.fn(),
}))
vi.mock('@/context/AuthContext', () => ({
  useAuth: () => ({ user: { id: 7 }, loading: false }),
}))
vi.mock('@/hooks/useChat', () => ({
  useChat: vi.fn(() => ({
    messages: [], input: 'Personal question', setInput: vi.fn(), isLoading: false, phase: 'idle',
    historyError: null, retryHistory: vi.fn(), handleSend: calls.send, doSend: vi.fn(),
    stopWaiting: calls.stop, confirmingClear: false, isClearing: false,
    clearError: null, requestClearChat: vi.fn(), cancelClear: vi.fn(), confirmClear: vi.fn(),
    uncertainTurn: null, checkPendingTurn: vi.fn(), resendUncertainTurn: vi.fn(),
    webSearch: false, toggleWebSearch: vi.fn(),
  })),
}))
vi.mock('@/hooks/useSuggestedQuestions', () => ({
  useSuggestedQuestions: () => ({ questions: [], contextScope: 'summary', generated: false,
    loading: false, refresh: vi.fn() }),
}))
vi.mock('@/hooks/useChatScroll', () => ({
  useChatScroll: () => ({ scrollRef: { current: null }, onScroll: vi.fn(), onWheel: vi.fn() }),
}))
vi.mock('@/components/chat/ChatHeader', () => ({ default: () => null }))
vi.mock('@/components/chat/ChatMessageList', () => ({ default: () => null }))
vi.mock('@/components/chat/ChatInput', () => ({
  default: ({ onSend, sendDisabled }) => (
    <button type="button" disabled={sendDisabled} onClick={onSend}>发送聊天问题</button>
  ),
}))
vi.mock('@/components/chat/ChatModelPicker', () => ({
  default: ({ selected, consent, onSelect, onConsent }) => (
    <div>
      <button type="button" onClick={() => onSelect('22222222-2222-4222-8222-222222222222')}>选择个人模型</button>
      <button type="button" onClick={() => onConsent(true)} disabled={!selected}>确认可能收费</button>
      <span>{selected ? (consent ? '收费已确认' : '收费未确认') : '尚未选择模型'}</span>
    </div>
  ),
}))
vi.mock('@/components/chat/ClearChatDialog', () => ({ default: () => null }))
vi.mock('@/components/chat/Confetti', () => ({ default: () => null }))

beforeEach(() => vi.clearAllMocks())

describe('T04 article assistant explicit billing intent', () => {
  it('consumes billing consent on each send; a second billable turn needs fresh confirmation', () => {
    render(<NewsChatAssistant newsId={42} open />)
    fireEvent.click(screen.getByRole('button', { name: '选择个人模型' }))
    expect(screen.getByRole('button', { name: '发送聊天问题' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: '确认可能收费' }))
    expect(screen.getByText('收费已确认')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '发送聊天问题' }))
    expect(calls.send).toHaveBeenCalledOnce()
    expect(screen.getByText('收费未确认')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '发送聊天问题' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: '确认可能收费' }))
    expect(screen.getByRole('button', { name: '发送聊天问题' })).toBeEnabled()
  })
})
