import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

function RecoveredAssistant({ onOpenChange }: { onOpenChange: (open: boolean) => void }) {
  return <button type="button" onClick={() => onOpenChange(false)}>关闭恢复后的小闻</button>
}

const loader = vi.hoisted(() => ({ load: vi.fn() }))

vi.mock('@/components/chat/newsChatAssistantLoader', () => ({
  loadNewsChatAssistant: loader.load,
}))

import LazyNewsChatAssistant from '@/components/chat/LazyNewsChatAssistant'

describe('LazyNewsChatAssistant chunk recovery', () => {
  it('contains a failed chunk and retries with a fresh lazy component', async () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {})
    const onOpenChange = vi.fn()
    loader.load
      .mockRejectedValueOnce(new Error('chunk unavailable'))
      .mockResolvedValueOnce({ default: RecoveredAssistant })

    render(<LazyNewsChatAssistant newsId="3369" open onOpenChange={onOpenChange} />)

    expect((await screen.findByRole('alert')).textContent).toContain('小闻加载失败')
    fireEvent.click(screen.getByRole('button', { name: '重试加载' }))

    expect(await screen.findByRole('button', { name: '关闭恢复后的小闻' })).not.toBeNull()
    expect(loader.load).toHaveBeenCalledTimes(2)
    fireEvent.click(screen.getByRole('button', { name: '关闭恢复后的小闻' }))
    expect(onOpenChange).toHaveBeenCalledWith(false)
    consoleError.mockRestore()
  })
})
