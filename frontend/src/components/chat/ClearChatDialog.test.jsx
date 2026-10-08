import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import ClearChatDialog from './ClearChatDialog'

describe('ClearChatDialog', () => {
  it('does not render when open=false', () => {
    render(<ClearChatDialog open={false} onConfirm={() => {}} onCancel={() => {}} />)
    expect(screen.queryByRole('alertdialog')).toBeNull()
  })

  it('renders Xiaowen + friendly text when open', () => {
    render(<ClearChatDialog open onConfirm={() => {}} onCancel={() => {}} />)
    const dialog = screen.getByRole('alertdialog')
    expect(dialog).toBeInTheDocument()
    // Friendly tone — not the cold "确定要清空..."
    expect(screen.getByText(/真的要忘掉/)).toBeInTheDocument()
    // Mascot present
    expect(dialog.querySelector('svg[aria-label="小闻 AI 助手"]')).not.toBeNull()
  })

  it('calls onConfirm when confirm button clicked', () => {
    const onConfirm = vi.fn()
    render(<ClearChatDialog open onConfirm={onConfirm} onCancel={() => {}} />)
    fireEvent.click(screen.getByRole('button', { name: '清空' }))
    expect(onConfirm).toHaveBeenCalledOnce()
  })

  it('calls onCancel when cancel button clicked', () => {
    const onCancel = vi.fn()
    render(<ClearChatDialog open onConfirm={() => {}} onCancel={onCancel} />)
    fireEvent.click(screen.getByRole('button', { name: '再聊聊' }))
    expect(onCancel).toHaveBeenCalledOnce()
  })

  it('calls onCancel when Escape pressed', () => {
    const onCancel = vi.fn()
    render(<ClearChatDialog open onConfirm={() => {}} onCancel={onCancel} />)
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(onCancel).toHaveBeenCalledOnce()
  })

  it('calls onCancel when backdrop clicked', () => {
    const onCancel = vi.fn()
    render(<ClearChatDialog open onConfirm={() => {}} onCancel={onCancel} />)
    fireEvent.click(screen.getByTestId('clear-dialog-backdrop'))
    expect(onCancel).toHaveBeenCalledOnce()
  })
})


describe('ClearChatDialog busy state', () => {
  it('displays the recoverable delete error in the still-open dialog', () => {
    render(<ClearChatDialog open error="清空失败，原有聊天记录仍保留。" onConfirm={() => {}} onCancel={() => {}} />)
    expect(screen.getByRole('alert')).toHaveTextContent('清空失败')
    expect(screen.getByRole('button', { name: '再聊聊' })).toBeEnabled()
    expect(screen.getByRole('button', { name: '清空' })).toBeEnabled()
  })

  it('prevents closing or confirming while the delete request is pending', () => {
    const onConfirm = vi.fn()
    const onCancel = vi.fn()
    render(<ClearChatDialog open isClearing onConfirm={onConfirm} onCancel={onCancel} />)
    expect(screen.getByRole('alertdialog')).toHaveAttribute('aria-busy', 'true')
    expect(screen.getByRole('button', { name: '再聊聊' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '清空中…' })).toBeDisabled()
    fireEvent.keyDown(window, { key: 'Escape' })
    fireEvent.click(screen.getByTestId('clear-dialog-backdrop'))
    expect(onCancel).not.toHaveBeenCalled()
    expect(onConfirm).not.toHaveBeenCalled()
  })
})
