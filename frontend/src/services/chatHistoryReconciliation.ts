import type { ChatHistory, ChatMessage } from '@/services/newsWorkflowApi'

export type ChatHistoryReconciliation = 'answered' | 'question-saved' | 'unconfirmed'

export interface ChatHistoryTurnOverlay {
  user: ChatMessage
  assistant: ChatMessage
  serverQuestionSaved: boolean
}

export function copyChatHistoryBoundary(messages: ChatMessage[] | undefined): ChatMessage[] | null {
  return messages ? messages.map((message) => ({ ...message })) : null
}

function matchesBoundary(history: ChatMessage[], boundary: ChatMessage[]): boolean {
  if (history.length < boundary.length) return false
  return boundary.every((message, index) => {
    const candidate = history[index]
    return candidate?.role === message.role && candidate.content === message.content
  })
}

export function reconcileChatHistory(
  history: ChatHistory,
  boundary: ChatMessage[] | null,
  question: string,
): ChatHistoryReconciliation {
  if (!boundary || !matchesBoundary(history.messages, boundary)) return 'unconfirmed'
  const userMessage = history.messages[boundary.length]
  if (userMessage?.role !== 'user' || userMessage.content !== question) return 'unconfirmed'
  return history.messages[boundary.length + 1]?.role === 'assistant' ? 'answered' : 'question-saved'
}

export function chatHistoryTurnOverlay(turn: ChatHistoryTurnOverlay): ChatMessage[] {
  return turn.serverQuestionSaved ? [turn.assistant] : [turn.user, turn.assistant]
}
