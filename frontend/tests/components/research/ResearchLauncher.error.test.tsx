import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

function RecoveredPanel({ onClose }: { onClose: () => void }) {
  return <button type="button" onClick={onClose}>关闭恢复后的研究面板</button>
}

const loader = vi.hoisted(() => ({
  load: vi.fn(),
}))

vi.mock('@/components/research/researchPanelLoader', () => ({
  loadResearchPanel: loader.load,
  prefetchResearchPanel: vi.fn(),
}))
vi.mock('@/context/SpeechPlayerContext', () => ({ useSpeechPlayerActivity: () => false }))

import ResearchLauncher from '@/components/research/ResearchLauncher'
import { CapabilitiesTestProvider } from '../../helpers/capabilities'

describe('ResearchLauncher chunk recovery', () => {
  it('contains a failed chunk and retries with a fresh lazy component', async () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {})
    loader.load
      .mockRejectedValueOnce(new Error('chunk unavailable'))
      .mockResolvedValueOnce({ default: RecoveredPanel })
    render(<MemoryRouter><CapabilitiesTestProvider><ResearchLauncher /></CapabilitiesTestProvider></MemoryRouter>)
    fireEvent.click(screen.getByRole('button', { name: '打开新闻研究助手' }))

    expect(await screen.findByRole('alert')).not.toBeNull()
    fireEvent.click(screen.getByRole('button', { name: '重试加载' }))

    expect(await screen.findByRole('button', { name: '关闭恢复后的研究面板' })).not.toBeNull()
    expect(loader.load).toHaveBeenCalledTimes(2)
    consoleError.mockRestore()
  })
})
