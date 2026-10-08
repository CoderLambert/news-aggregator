import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import ResearchHeader from '@/components/research/ResearchHeader'

const sessions = [
  { id: 'session-one', title: '第一场研究' },
  { id: 'session-two', title: '第二场研究' },
  { id: 'session-three', title: '第三场研究' },
]

function renderHeader() {
  const onSelectSession = vi.fn()
  render(
    <ResearchHeader
      phase="idle"
      isFullscreen={false}
      onToggleFullscreen={vi.fn()}
      onNewSession={vi.fn()}
      onClose={vi.fn()}
      sessions={sessions}
      activeSessionId="session-two"
      onSelectSession={onSelectSession}
    />,
  )
  return { onSelectSession }
}

describe('ResearchHeader history menu keyboard behavior', () => {
  it('does not reopen when the open trigger receives an outside-click sequence', async () => {
    renderHeader()
    const trigger = screen.getByRole('button', { name: '历史会话' })
    fireEvent.click(trigger)
    expect(await screen.findByRole('menu', { name: '历史会话' })).toBeInTheDocument()

    fireEvent.mouseDown(trigger)
    fireEvent.click(trigger)

    expect(screen.queryByRole('menu', { name: '历史会话' })).not.toBeInTheDocument()
    expect(trigger).toHaveAttribute('aria-expanded', 'false')
  })

  it('focuses the current item and supports arrow, Home, End and Escape', async () => {
    renderHeader()
    const trigger = screen.getByRole('button', { name: '历史会话' })
    fireEvent.click(trigger)

    const menu = await screen.findByRole('menu', { name: '历史会话' })
    const items = within(menu).getAllByRole('menuitem')
    await waitFor(() => expect(items[1]).toHaveFocus())
    expect(items[0]).toHaveAttribute('tabindex', '-1')
    expect(items[1]).toHaveAttribute('tabindex', '0')

    fireEvent.keyDown(items[1], { key: 'ArrowDown' })
    expect(items[2]).toHaveFocus()
    fireEvent.keyDown(items[2], { key: 'ArrowDown' })
    expect(items[0]).toHaveFocus()
    fireEvent.keyDown(items[0], { key: 'End' })
    expect(items[2]).toHaveFocus()
    fireEvent.keyDown(items[2], { key: 'Home' })
    expect(items[0]).toHaveFocus()

    fireEvent.keyDown(items[0], { key: 'Escape' })
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
    expect(trigger).toHaveFocus()
  })

  it('opens from the trigger ArrowUp key and returns focus after selecting a session', async () => {
    const { onSelectSession } = renderHeader()
    const trigger = screen.getByRole('button', { name: '历史会话' })
    fireEvent.keyDown(trigger, { key: 'ArrowUp' })

    const menu = await screen.findByRole('menu', { name: '历史会话' })
    const items = within(menu).getAllByRole('menuitem')
    await waitFor(() => expect(items[2]).toHaveFocus())
    fireEvent.click(items[0])

    expect(onSelectSession).toHaveBeenCalledWith('session-one')
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
    expect(trigger).toHaveFocus()
  })
})
