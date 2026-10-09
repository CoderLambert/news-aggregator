import { useEffect, useRef, type KeyboardEvent } from 'react'

interface LazyModalStateProps {
  label: string
  message: string
  onClose: () => void
  onRetry?: () => void
  variant: 'research' | 'chat'
}

export default function LazyModalState({ label, message, onClose, onRetry, variant }: LazyModalStateProps) {
  const dialogRef = useRef<HTMLDivElement | null>(null)
  const closeRef = useRef<HTMLButtonElement | null>(null)
  const zIndex = variant === 'chat' ? 'z-50' : 'z-40'
  const backdropZIndex = variant === 'chat' ? 'z-40' : 'z-30'
  const panelPosition = variant === 'chat'
    ? 'rounded-t-3xl sm:inset-auto sm:bottom-6 sm:right-6 sm:w-[450px] sm:rounded-2xl'
    : 'rounded-t-2xl sm:bottom-6 sm:left-auto sm:right-6 sm:w-[600px] sm:rounded-2xl'

  useEffect(() => {
    const originalOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    closeRef.current?.focus()
    return () => { document.body.style.overflow = originalOverflow }
  }, [])

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === 'Escape') {
      event.preventDefault()
      onClose()
      return
    }
    if (event.key !== 'Tab') return
    const controls = Array.from(dialogRef.current?.querySelectorAll<HTMLElement>('button:not(:disabled)') ?? [])
    if (!controls.length) return
    const currentIndex = controls.indexOf(document.activeElement as HTMLElement)
    const nextIndex = event.shiftKey
      ? (currentIndex <= 0 ? controls.length - 1 : currentIndex - 1)
      : (currentIndex >= controls.length - 1 ? 0 : currentIndex + 1)
    event.preventDefault()
    controls[nextIndex]?.focus()
  }

  return (
    <>
      <div aria-hidden="true" className={`fixed inset-0 ${backdropZIndex} bg-black/20 backdrop-blur-sm`} onClick={onClose} />
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label={label}
        onKeyDown={handleKeyDown}
        className={`fixed inset-x-0 bottom-0 ${zIndex} flex h-48 items-center justify-center border border-border bg-background shadow-2xl ${panelPosition}`}
      >
        <div className="px-16 text-center">
          <p role={onRetry ? 'alert' : 'status'} className="text-sm text-muted-foreground">{message}</p>
          {onRetry && (
            <button type="button" onClick={onRetry} className="mt-4 min-h-11 rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground">
              重试加载
            </button>
          )}
        </div>
        <button ref={closeRef} type="button" onClick={onClose} className="absolute right-3 top-3 min-h-11 rounded-lg px-3 text-sm text-muted-foreground hover:bg-muted">
          关闭
        </button>
      </div>
    </>
  )
}
