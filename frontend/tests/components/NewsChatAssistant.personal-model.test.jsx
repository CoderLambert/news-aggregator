import { MemoryRouter } from 'react-router-dom'
import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import NewsChatAssistant from '@/components/NewsChatAssistant'
import { useChat } from '@/hooks/useChat'

const calls = vi.hoisted(() => ({
  send: vi.fn(() => Promise.resolve(true)),
  stop: vi.fn(),
  quickSend: vi.fn(() => Promise.resolve(true)),
  refresh: vi.fn(),
  preferenceError: false, reload: vi.fn(),
}))
vi.mock('@/context/AuthContext', () => ({
  useAuth: () => ({ user: { id: 7 }, loading: false }),
}))
vi.mock('@/hooks/useChat', () => ({
  useChat: vi.fn(() => ({
    messages: [], input: 'Personal question', setInput: vi.fn(), isLoading: false, phase: 'idle',
    historyError: null, retryHistory: vi.fn(), handleSend: calls.send, doSend: calls.quickSend,
    stopWaiting: calls.stop, confirmingClear: false, isClearing: false,
    clearError: null, requestClearChat: vi.fn(), cancelClear: vi.fn(), confirmClear: vi.fn(),
    uncertainTurn: null, checkPendingTurn: vi.fn(), resendUncertainTurn: vi.fn(),
    webSearch: false, toggleWebSearch: vi.fn(),
  })),
}))
vi.mock('@/hooks/useSuggestedQuestions', () => ({
  useSuggestedQuestions: () => ({ questions: ['测试推荐问题'], contextScope: 'summary', generated: false,
    modelConfigId: 'saved-suggestions-model', modelLabel: 'Personal suggestions model',
    loading: false, refresh: calls.refresh }),
}))
vi.mock('@/hooks/useChatScroll', () => ({
  useChatScroll: () => ({ scrollRef: { current: null }, onScroll: vi.fn(), onWheel: vi.fn() }),
}))
vi.mock('@/components/chat/ChatHeader', () => ({ default: () => null }))
vi.mock('@/components/chat/ChatInput', () => ({
  default: ({ onSend, sendDisabled }) => (
    <button type="button" disabled={sendDisabled} onClick={onSend}>发送聊天问题</button>
  ),
}))
vi.mock('@/hooks/useDefaultAIModel', () => ({
  useDefaultAIModel: () => ({ isPending: false, isError: calls.preferenceError, refetch: calls.reload,
    selection: calls.preferenceError ? null : { model_config_id: '22222222-2222-4222-8222-222222222222', model: { display_name: 'Default' } } }),
}))
vi.mock('@/components/chat/ClearChatDialog', () => ({ default: () => null }))
vi.mock('@/components/chat/Confetti', () => ({ default: () => null }))

beforeEach(() => { vi.clearAllMocks(); calls.preferenceError = false })

describe('T04 article assistant explicit billing intent', () => {
  it('reports a preference read failure without falsely asking the user to configure a model', () => {
    calls.preferenceError = true
    render(<MemoryRouter><NewsChatAssistant newsId={42} open /></MemoryRouter>)
    expect(screen.getByText('暂时无法读取默认模型，请重试。')).toBeInTheDocument()
    expect(screen.queryByText('默认问答模型不可用，请先在设置中配置。')).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: '模型设置' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '重新读取' }))
    expect(calls.reload).toHaveBeenCalledOnce()
    expect(calls.send).not.toHaveBeenCalled()
  })
  it('sends each explicit question with the saved model without a configuration or consent form', () => {
    render(<MemoryRouter><NewsChatAssistant newsId={42} open /></MemoryRouter>)
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument()
    expect(screen.queryAllByRole('checkbox')).toHaveLength(0)
    expect(screen.queryByRole('link', { name: '模型设置' })).not.toBeInTheDocument()
    expect(screen.queryByText(/使用已配置的问答模型|推荐问题模型|需要配置个人模型额度/)).not.toBeInTheDocument()
    expect(calls.send).not.toHaveBeenCalled()
    expect(calls.refresh).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: '发送聊天问题' })).toBeEnabled()
    fireEvent.click(screen.getByRole('button', { name: '发送聊天问题' }))
    fireEvent.click(screen.getByRole('button', { name: '发送聊天问题' }))
    expect(calls.send).toHaveBeenCalledTimes(2)
    expect(vi.mocked(useChat)).toHaveBeenLastCalledWith(42, true,
      '22222222-2222-4222-8222-222222222222', true, undefined, 'current')
  })

  it('a recommended question sends directly, while refresh explicitly authorizes only recommendation generation', () => {
    render(<MemoryRouter><NewsChatAssistant newsId={42} open /></MemoryRouter>)
    fireEvent.click(screen.getByRole('button', { name: '测试推荐问题' }))
    expect(calls.quickSend).toHaveBeenCalledExactlyOnceWith('测试推荐问题')
    expect(calls.refresh).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: '换一批推荐问题' }))
    expect(calls.refresh).toHaveBeenCalledExactlyOnceWith(true)
    expect(calls.send).not.toHaveBeenCalled()
  })
})
