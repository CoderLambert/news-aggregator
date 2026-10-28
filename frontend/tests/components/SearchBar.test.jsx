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
import { MemoryRouter } from 'react-router-dom'
import SearchBar from '@/components/SearchBar'
import { LanguageProvider } from '@/context/LanguageContext'
import { usePreferencesStore } from '@/stores/preferences'

function renderWithLang(ui, lang = 'zh') {
  usePreferencesStore.getState().setLang(lang)
  return render(<MemoryRouter><LanguageProvider>{ui}</LanguageProvider></MemoryRouter>)
}

beforeEach(() => { vi.useFakeTimers() })
afterEach(() => {
  vi.useRealTimers()
  localStorage.clear()
  usePreferencesStore.getState().setLang('zh')
})

describe('SearchBar', () => {
  it('renders with initial value from props', () => {
    renderWithLang(
      <SearchBar value="hello" onChange={() => {}} mode="hybrid" onModeChange={() => {}} allowSemantic />
    )
    expect(screen.getByPlaceholderText(/搜索/)).toHaveValue('hello')
  })

  it('updates input immediately when external value prop changes', () => {
    const { rerender } = renderWithLang(
      <SearchBar value="first" onChange={() => {}} mode="hybrid" onModeChange={() => {}} allowSemantic />
    )
    expect(screen.getByPlaceholderText(/搜索/)).toHaveValue('first')

    rerender(
      <MemoryRouter><LanguageProvider>
        <SearchBar value="second" onChange={() => {}} mode="hybrid" onModeChange={() => {}} allowSemantic />
      </LanguageProvider></MemoryRouter>
    )
    expect(screen.getByPlaceholderText(/搜索/)).toHaveValue('second')
  })

  it('debounces onChange by 300ms when typing', () => {
    const onChange = vi.fn()
    renderWithLang(
      <SearchBar value="" onChange={onChange} mode="hybrid" onModeChange={() => {}} allowSemantic />
    )

    const input = screen.getByPlaceholderText(/搜索/)
    fireEvent.change(input, { target: { value: 'r' } })
    fireEvent.change(input, { target: { value: 'react' } })

    expect(onChange).not.toHaveBeenCalled()

    act(() => { vi.advanceTimersByTime(350) })

    expect(onChange).toHaveBeenCalledTimes(1)
    expect(onChange).toHaveBeenLastCalledWith('react')
  })

  it('calls the latest onChange callback if it changes while a debounce is pending', () => {
    const oldOnChange = vi.fn()
    const latestOnChange = vi.fn()
    const props = { value: '', mode: 'hybrid', onModeChange: () => {}, allowSemantic: true }
    const { rerender } = renderWithLang(<SearchBar {...props} onChange={oldOnChange} />)

    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'fresh' } })
    rerender(<MemoryRouter><LanguageProvider><SearchBar {...props} onChange={latestOnChange} /></LanguageProvider></MemoryRouter>)
    act(() => { vi.advanceTimersByTime(350) })

    expect(oldOnChange).not.toHaveBeenCalled()
    expect(latestOnChange).toHaveBeenCalledWith('fresh')
  })

  it('cancels a pending debounce when an external URL value replaces the draft', () => {
    const onChange = vi.fn()
    const props = { mode: 'hybrid', onChange, onModeChange: () => {}, allowSemantic: true }
    const { rerender } = renderWithLang(<SearchBar {...props} value="before" />)

    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'draft' } })
    rerender(<MemoryRouter><LanguageProvider><SearchBar {...props} value="after" /></LanguageProvider></MemoryRouter>)
    expect(screen.getByRole('searchbox')).toHaveValue('after')
    act(() => { vi.advanceTimersByTime(350) })

    expect(onChange).not.toHaveBeenCalled()
  })

  it.each([['semantic', '语义'], ['hybrid', '混合']])('calls onModeChange for enabled %s mode', (mode, label) => {
    const onModeChange = vi.fn()
    renderWithLang(
      <SearchBar value="" onChange={() => {}} mode="keyword" onModeChange={onModeChange} allowSemantic />
    )
    fireEvent.click(screen.getByRole('radio', { name: label }))
    expect(onModeChange).toHaveBeenCalledWith(mode)
  })

  it('shows English mode labels when lang is en', () => {
    renderWithLang(
      <SearchBar value="" onChange={() => {}} mode="hybrid" onModeChange={() => {}} allowSemantic />,
      'en'
    )
    expect(screen.getByText('Keyword')).toBeInTheDocument()
    expect(screen.getByText('Semantic')).toBeInTheDocument()
    expect(screen.getByText('Hybrid')).toBeInTheDocument()
  })

  it('carries the current draft and mode into advanced search', () => {
    renderWithLang(
      <SearchBar value="agent tools" onChange={() => {}} mode="keyword" onModeChange={() => {}} allowSemantic />
    )

    expect(screen.getByRole('link', { name: '高级搜索' })).toHaveAttribute('href', '/search?q=agent%20tools&mode=keyword')
  })

  it.each([false, undefined].flatMap((allowSemantic) =>
    ['semantic', 'hybrid'].map((mode) => ({ allowSemantic, mode })),
  ))('fails closed for allowSemantic=$allowSemantic and mode=$mode', ({ allowSemantic, mode }) => {
    const onChange = vi.fn()
    const onModeChange = vi.fn()
    renderWithLang(
      <SearchBar value="agent tools" onChange={onChange} mode={mode} onModeChange={onModeChange} allowSemantic={allowSemantic} />,
    )

    expect(screen.getByRole('radio', { name: '关键词' })).toHaveAttribute('aria-checked', 'true')
    expect(screen.queryByRole('radio', { name: '语义' })).not.toBeInTheDocument()
    expect(screen.queryByRole('radio', { name: '混合' })).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: '高级搜索' })).toHaveAttribute('href', '/search?q=agent%20tools&mode=keyword')
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'keyword update' } })
    act(() => { vi.advanceTimersByTime(350) })
    expect(onChange).toHaveBeenCalledWith('keyword update')
    expect(screen.getByRole('link', { name: '高级搜索' })).toHaveAttribute('href', '/search?q=keyword%20update&mode=keyword')
    expect(onModeChange).not.toHaveBeenCalled()
  })
})
