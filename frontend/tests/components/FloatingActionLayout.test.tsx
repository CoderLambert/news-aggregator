import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import ChatBubbleButton from '@/components/chat/ChatBubbleButton'
import ResearchBubbleButton from '@/components/research/ResearchBubbleButton'
import { SpeechPlayerActivityContext } from '@/context/SpeechPlayerContext'

function renderLaunchers(speechActive = false) {
  return render(
    <MemoryRouter initialEntries={['/news/21']}>
      <SpeechPlayerActivityContext.Provider value={speechActive}>
        <ResearchBubbleButton onOpen={vi.fn()} />
        <ChatBubbleButton onOpen={vi.fn()} buttonRef={undefined} />
      </SpeechPlayerActivityContext.Provider>
    </MemoryRouter>,
  )
}

describe('mobile floating action layout', () => {
  it('places research and Xiaowen side by side on a news detail route', () => {
    renderLaunchers()
    expect(screen.getByRole('button', { name: '打开新闻研究助手' }).className).toContain('bottom-6')
    expect(screen.getByRole('button', { name: '打开新闻研究助手' }).className).toContain('right-24')
    expect(screen.getByRole('button', { name: '打开 AI 助手小闻' }).className).toContain('bottom-6')
    expect(screen.getByRole('button', { name: '打开 AI 助手小闻' }).className).toContain('right-6')
  })

  it('moves both launchers above the global speech player', () => {
    renderLaunchers(true)
    expect(screen.getByRole('button', { name: '打开新闻研究助手' }).className).toContain('bottom-24')
    expect(screen.getByRole('button', { name: '打开新闻研究助手' }).className).toContain('right-24')
    expect(screen.getByRole('button', { name: '打开 AI 助手小闻' }).className).toContain('bottom-24')
    expect(screen.getByRole('button', { name: '打开 AI 助手小闻' }).className).toContain('right-6')
  })
})
