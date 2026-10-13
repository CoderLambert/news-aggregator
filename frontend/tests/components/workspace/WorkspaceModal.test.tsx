import { useState } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import WorkspaceModal from '@/components/workspace/WorkspaceModal'

beforeEach(() => {
  vi.spyOn(HTMLDialogElement.prototype, 'showModal').mockImplementation(function (this: HTMLDialogElement) { this.setAttribute('open', '') })
  vi.spyOn(HTMLDialogElement.prototype, 'close').mockImplementation(function (this: HTMLDialogElement) { this.removeAttribute('open') })
})
afterEach(() => vi.restoreAllMocks())
function Example({ busy = false }: { busy?: boolean }) {
  const [open, setOpen] = useState(false)
  return <><button type="button" onClick={() => setOpen(true)}>打开整理确认</button>{open && <WorkspaceModal title="整理确认" busy={busy} onClose={() => setOpen(false)}><p>确认内容</p></WorkspaceModal>}</>
}
describe('workspace modal accessibility', () => {
  it('has an accessible title and restores focus after closing', () => {
    render(<Example />)
    const trigger = screen.getByRole('button', { name: '打开整理确认' })
    trigger.focus(); fireEvent.click(trigger)
    expect(screen.getByRole('dialog', { name: '整理确认' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '关闭整理确认' }))
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(trigger).toHaveFocus()
  })
  it('does not dismiss a mutation in progress via Escape', () => {
    render(<Example busy />)
    fireEvent.click(screen.getByRole('button', { name: '打开整理确认' }))
    const dialog = screen.getByRole('dialog', { name: '整理确认' })
    fireEvent(dialog, new Event('cancel', { cancelable: true }))
    expect(dialog).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '关闭整理确认' })).toBeDisabled()
  })
})
