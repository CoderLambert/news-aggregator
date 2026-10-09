import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import LazyModalState from '@/components/LazyModalState'

describe('LazyModalState', () => {
  it('takes focus, traps Tab, supports Escape, and restores body scrolling on unmount', () => {
    const onClose = vi.fn()
    const { unmount } = render(
      <LazyModalState label="测试加载框" message="正在加载…" onClose={onClose} variant="research" />,
    )
    const closeButton = screen.getByRole('button', { name: '关闭' })
    expect(document.activeElement).toBe(closeButton)
    expect(document.body.style.overflow).toBe('hidden')

    fireEvent.keyDown(closeButton, { key: 'Tab' })
    expect(document.activeElement).toBe(closeButton)
    fireEvent.keyDown(closeButton, { key: 'Escape' })
    expect(onClose).toHaveBeenCalledOnce()

    unmount()
    expect(document.body.style.overflow).toBe('')
  })

  it('offers separate retry and explicit page reload actions in the error state', () => {
    const onReload = vi.fn()
    const onRetry = vi.fn()
    render(
      <LazyModalState
        label="测试错误框"
        message="加载失败"
        onClose={vi.fn()}
        onReload={onReload}
        onRetry={onRetry}
        variant="chat"
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: '重试加载' }))
    fireEvent.click(screen.getByRole('button', { name: '刷新页面' }))

    expect(onRetry).toHaveBeenCalledOnce()
    expect(onReload).toHaveBeenCalledOnce()
  })
})
