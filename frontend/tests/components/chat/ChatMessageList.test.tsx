import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import ChatMessageList from '@/components/chat/ChatMessageList'

describe('ChatMessageList model source', () => {
  it('shows the saved provider and model below a BYOK answer', () => {
    render(<ChatMessageList
      phase="idle"
      messages={[{
        role: 'assistant',
        content: 'The article says this is the main point.',
        model_source: { provider: 'DeepSeek', model: 'DeepSeek V4.1 Flash' },
      }]}
    />)

    expect(screen.getByLabelText('回答模型来源')).toHaveTextContent('模型来源：DeepSeek · DeepSeek V4.1 Flash')
  })
})
