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
