import { useState } from 'react'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

function RecoveredAssistant({ onOpenChange }: { onOpenChange: (open: boolean) => void }) {
  return <button type="button" onClick={() => onOpenChange(false)}>关闭恢复后的小闻</button>
}

const loader = vi.hoisted(() => ({ load: vi.fn(), reloadPage: vi.fn() }))

vi.mock('@/components/chat/newsChatAssistantLoader', () => ({
  loadNewsChatAssistant: loader.load,
  reloadNewsChatPage: loader.reloadPage,
}))

import LazyNewsChatAssistant from '@/components/chat/LazyNewsChatAssistant'

function ReopenHarness() {
  const [open, setOpen] = useState(true)
  return (
    <>
      {!open && <button type="button" onClick={() => setOpen(true)}>重新打开小闻</button>}
      <LazyNewsChatAssistant newsId="3369" open={open} onOpenChange={setOpen} />
    </>
  )
}

describe('LazyNewsChatAssistant chunk recovery', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    loader.load.mockReset()
    loader.reloadPage.mockReset()
  })

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
    expect(consoleError).toHaveBeenCalled()
  })

  it('keeps the local error state after a repeated failure and lets the user refresh the page', async () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {})
    loader.load.mockRejectedValue(new Error('cached chunk failure'))

    render(<LazyNewsChatAssistant newsId="3369" open onOpenChange={vi.fn()} />)

    const firstError = await screen.findByRole('alert')
    expect(firstError.textContent).toContain('若仍失败，请刷新页面')
    fireEvent.click(screen.getByRole('button', { name: '重试加载' }))

    await waitFor(() => expect(loader.load).toHaveBeenCalledTimes(2))
    await waitFor(() => expect(screen.getByRole('alert')).not.toBe(firstError))
    expect(screen.getByRole('alert').textContent).toContain('若仍失败，请刷新页面')
    fireEvent.click(screen.getByRole('button', { name: '刷新页面' }))

    expect(loader.reloadPage).toHaveBeenCalledOnce()
    expect(consoleError).toHaveBeenCalled()
  })

  it('keeps a closed failure contained and retries only after the reopened user asks', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    loader.load
      .mockRejectedValueOnce(new Error('first chunk failure'))
      .mockResolvedValueOnce({ default: RecoveredAssistant })
    render(<ReopenHarness />)

    await screen.findByRole('alert')
    fireEvent.click(screen.getByRole('button', { name: '关闭' }))
    fireEvent.click(await screen.findByRole('button', { name: '重新打开小闻' }))

    expect(await screen.findByRole('alert')).not.toBeNull()
    expect(loader.load).toHaveBeenCalledTimes(1)
    fireEvent.click(screen.getByRole('button', { name: '重试加载' }))

    expect(await screen.findByRole('button', { name: '关闭恢复后的小闻' })).not.toBeNull()
    expect(loader.load).toHaveBeenCalledTimes(2)
  })
})
