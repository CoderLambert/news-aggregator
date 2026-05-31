import { describe, it, expect } from 'vitest'
import { render } from '@testing-library/react'
import XiaowenMascot from './XiaowenMascot'

describe('XiaowenMascot', () => {
  it('renders with default idle mood', () => {
    const { container } = render(<XiaowenMascot />)
    const svg = container.querySelector('svg')
    expect(svg).toBeInTheDocument()
    expect(svg).toHaveAttribute('data-mood', 'idle')
    expect(svg).toHaveAttribute('aria-label', '小闻 AI 助手')
  })

  it('switches data-mood when prop changes', () => {
    const { container, rerender } = render(<XiaowenMascot mood="think" />)
    expect(container.querySelector('svg')).toHaveAttribute('data-mood', 'think')
    rerender(<XiaowenMascot mood="happy" />)
    expect(container.querySelector('svg')).toHaveAttribute('data-mood', 'happy')
    rerender(<XiaowenMascot mood="confused" />)
    expect(container.querySelector('svg')).toHaveAttribute('data-mood', 'confused')
  })

  it('respects size prop', () => {
    const { container } = render(<XiaowenMascot size={120} />)
    const svg = container.querySelector('svg')
    expect(svg).toHaveAttribute('width', '120')
    expect(svg).toHaveAttribute('height', '120')
  })

  it('shows sleep z text when mood=sleep', () => {
    const { container } = render(<XiaowenMascot mood="sleep" autoBlink={false} />)
    expect(container.querySelector('text')).toBeInTheDocument()
    expect(container.querySelector('text').textContent).toBe('z')
  })

  it('does not show sleep z text in other moods', () => {
    const { container } = render(<XiaowenMascot mood="happy" autoBlink={false} />)
    expect(container.querySelector('text')).not.toBeInTheDocument()
  })

  it('applies custom className', () => {
    const { container } = render(<XiaowenMascot className="my-custom" />)
    expect(container.querySelector('svg')).toHaveClass('my-custom')
  })
})
