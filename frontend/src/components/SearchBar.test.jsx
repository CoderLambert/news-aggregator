/**
 * SearchBar — behaviour tests covering:
 *   - debounced onChange (300ms)
 *   - external `value` prop reflected in input immediately
 *   - mode buttons fire onModeChange
 *   - i18n labels switch with LanguageProvider
 *
 * Uses fireEvent (synchronous) instead of userEvent to avoid the classic
 * userEvent + fake-timer interlock on Vitest 4.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, act } from '@testing-library/react'
import SearchBar from './SearchBar'
import { LanguageProvider } from '../context/LanguageContext'

function renderWithLang(ui, lang = 'zh') {
  localStorage.setItem('newshub_lang', lang)
  return render(<LanguageProvider>{ui}</LanguageProvider>)
}

beforeEach(() => { vi.useFakeTimers() })
afterEach(() => {
  vi.useRealTimers()
  localStorage.clear()
})

describe('SearchBar', () => {
  it('renders with initial value from props', () => {
    renderWithLang(
      <SearchBar value="hello" onChange={() => {}} mode="hybrid" onModeChange={() => {}} />
    )
    expect(screen.getByPlaceholderText(/搜索/)).toHaveValue('hello')
  })

  it('updates input immediately when external value prop changes', () => {
    const { rerender } = renderWithLang(
      <SearchBar value="first" onChange={() => {}} mode="hybrid" onModeChange={() => {}} />
    )
    expect(screen.getByPlaceholderText(/搜索/)).toHaveValue('first')

    rerender(
      <LanguageProvider>
        <SearchBar value="second" onChange={() => {}} mode="hybrid" onModeChange={() => {}} />
      </LanguageProvider>
    )
    expect(screen.getByPlaceholderText(/搜索/)).toHaveValue('second')
  })

  it('debounces onChange by 300ms when typing', () => {
    const onChange = vi.fn()
    renderWithLang(
      <SearchBar value="" onChange={onChange} mode="hybrid" onModeChange={() => {}} />
    )

    const input = screen.getByPlaceholderText(/搜索/)
    fireEvent.change(input, { target: { value: 'r' } })
    fireEvent.change(input, { target: { value: 'react' } })

    expect(onChange).not.toHaveBeenCalled()

    act(() => { vi.advanceTimersByTime(350) })

    expect(onChange).toHaveBeenCalledTimes(1)
    expect(onChange).toHaveBeenLastCalledWith('react')
  })

  it('calls onModeChange when mode button is clicked', () => {
    const onModeChange = vi.fn()
    renderWithLang(
      <SearchBar value="" onChange={() => {}} mode="hybrid" onModeChange={onModeChange} />
    )
    fireEvent.click(screen.getByText('语义'))
    expect(onModeChange).toHaveBeenCalledWith('semantic')
  })

  it('shows English mode labels when lang is en', () => {
    renderWithLang(
      <SearchBar value="" onChange={() => {}} mode="hybrid" onModeChange={() => {}} />,
      'en'
    )
    expect(screen.getByText('Keyword')).toBeInTheDocument()
    expect(screen.getByText('Semantic')).toBeInTheDocument()
    expect(screen.getByText('Hybrid')).toBeInTheDocument()
  })
})
