import { describe, expect, it } from 'vitest'
import {
  chatHistoryTurnOverlay,
  copyChatHistoryBoundary,
  reconcileChatHistory,
} from '@/services/chatHistoryReconciliation'

describe('chat history reconciliation', () => {
  it.each([
    ['missing boundary', null, []],
    ['changed boundary', [{ role: 'user', content: 'before' }], [{ role: 'assistant', content: 'changed' }]],
    ['history shorter than boundary', [{ role: 'user', content: 'before' }], []],
  ])('keeps an unknown result for a %s', (_label, boundary, historyMessages) => {
    expect(reconcileChatHistory({ messages: historyMessages }, boundary, 'current')).toBe('unconfirmed')
  })

  it('does not match an identical old question before the saved history boundary', () => {
    const history = [
      { role: 'user', content: 'same question' },
      { role: 'assistant', content: 'older answer' },
      { role: 'user', content: 'unrelated' },
    ]
    const boundary = history.slice(0, 2)

    expect(reconcileChatHistory({ messages: history }, boundary, 'same question')).toBe('unconfirmed')
  })

  it('recognizes the next turn when the same question is sent again after its boundary', () => {
    const firstTurn = [
      { role: 'user', content: 'same question' },
      { role: 'assistant', content: 'first answer' },
    ]
    const history = [
      ...firstTurn,
      { role: 'user', content: 'same question' },
      { role: 'assistant', content: 'second answer' },
    ]

    expect(reconcileChatHistory({ messages: history }, firstTurn, 'same question')).toBe('answered')
  })

  it('distinguishes a saved question from a fully saved answer at the exact turn boundary', () => {
    const boundary = [{ role: 'user', content: 'earlier' }, { role: 'assistant', content: 'reply' }]
    expect(reconcileChatHistory({ messages: [...boundary, { role: 'user', content: 'current' }] }, boundary, 'current'))
      .toBe('question-saved')
    expect(reconcileChatHistory({ messages: [
      ...boundary,
      { role: 'user', content: 'current' },
      { role: 'assistant', content: 'complete answer' },
    ] }, boundary, 'current')).toBe('answered')
  })

  it('copies the history boundary without sharing mutable message objects', () => {
    const source = [{ role: 'user', content: 'before' }]
    const boundary = copyChatHistoryBoundary(source)
    source[0].content = 'changed'

    expect(boundary).toEqual([{ role: 'user', content: 'before' }])
  })

  it('shows only the assistant overlay once the question is already in server history', () => {
    const user = { role: 'user', content: 'already saved' }
    const assistant = { role: 'assistant', content: 'saved answer' }
    expect(chatHistoryTurnOverlay({ user, assistant, serverQuestionSaved: true })).toEqual([assistant])
    expect(chatHistoryTurnOverlay({ user, assistant, serverQuestionSaved: false })).toEqual([user, assistant])
  })
})
