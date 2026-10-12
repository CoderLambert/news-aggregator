import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

function TestPanel({ onClose }: { onClose: () => void }) {
  return <button type="button" onClick={onClose}>关闭研究测试面板</button>
}

const loader = vi.hoisted(() => ({
  load: vi.fn(),
  prefetch: vi.fn(),
}))

vi.mock('@/components/research/researchPanelLoader', () => ({
  loadResearchPanel: loader.load,
  prefetchResearchPanel: loader.prefetch,
}))
vi.mock('@/context/SpeechPlayerContext', () => ({ useSpeechPlayerActivity: () => false }))

import ResearchLauncher from '@/components/research/ResearchLauncher'
import { CapabilitiesTestProvider } from '../../helpers/capabilities'

beforeEach(() => {
  loader.load.mockReset().mockResolvedValue({ default: TestPanel })
  loader.prefetch.mockReset()
})

describe('ResearchLauncher loading boundary', () => {
  it('prefetches on intent and mounts heavy UI only after activation', async () => {
    render(<MemoryRouter><CapabilitiesTestProvider><ResearchLauncher /></CapabilitiesTestProvider></MemoryRouter>)
    const launcher = screen.getByRole('button', { name: '打开新闻研究助手' })

    expect(loader.load).not.toHaveBeenCalled()
    fireEvent.mouseEnter(launcher)
    expect(loader.prefetch).toHaveBeenCalledOnce()
    expect(loader.load).not.toHaveBeenCalled()

    fireEvent.click(launcher)
    expect(await screen.findByRole('button', { name: '关闭研究测试面板' })).not.toBeNull()
    expect(loader.load).toHaveBeenCalledOnce()
  })

})
