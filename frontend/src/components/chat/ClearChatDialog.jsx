import { useEffect } from 'react'
import { Button } from '../ui/button'
import XiaowenMascot from '../mascot/XiaowenMascot'

/**
 * Friendly confirmation modal for clearing saved chat history.
 * @param {{ open: boolean, onConfirm: () => void, onCancel: () => void, isClearing?: boolean, error?: string | null }} props
 */
export default function ClearChatDialog({ open, onConfirm, onCancel, isClearing = false, error = null }) {
  useEffect(() => {
    if (!open || isClearing) return
    function onKey(e) {
      if (e.key === 'Escape') onCancel?.()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, isClearing, onCancel])

  if (!open) return null

  return (
    <div
      className="pointer-events-auto fixed inset-0 z-[60] flex items-center justify-center p-4 animate-message-pop-in"
      role="alertdialog"
      aria-modal="true"
      aria-labelledby="clear-dialog-title"
      aria-busy={isClearing}
    >
      <div
        data-testid="clear-dialog-backdrop"
        className={`absolute inset-0 bg-neutral-900/40 backdrop-blur-sm ${isClearing ? 'cursor-wait' : ''}`}
        onClick={() => { if (!isClearing) onCancel?.() }}
        aria-hidden="true"
      />

      <div className="relative w-full max-w-sm rounded-3xl bg-white p-6 shadow-2xl ring-1 ring-neutral-100">
        <div className="flex flex-col items-center text-center">
          <div className="animate-mascot-bob">
            <XiaowenMascot mood="confused" size={72} showShadow autoBlink={false} />
          </div>
          <h2 id="clear-dialog-title" className="mt-3 text-base font-semibold text-neutral-900">
            真的要忘掉我们刚才聊的吗？
          </h2>
          <p className="mt-1.5 text-xs text-neutral-500 leading-relaxed">
            清空后就找不回啦，咱们要从头来过哦。
          </p>
        </div>

        {error && <p role="alert" className="mt-4 rounded-lg bg-rose-50 p-2 text-sm text-rose-700">{error}</p>}
        {isClearing && <p role="status" className="mt-4 text-center text-sm text-neutral-600">正在清空聊天记录…</p>}

        <div className="mt-5 flex gap-2">
          <Button
            type="button"
            variant="outline"
            className="flex-1 rounded-full h-10 text-sm"
            disabled={isClearing}
            onClick={onCancel}
          >
            再聊聊
          </Button>
          <Button
            type="button"
            className="flex-1 rounded-full h-10 text-sm bg-rose-500 hover:bg-rose-600 text-white"
            disabled={isClearing}
            onClick={onConfirm}
          >
            {isClearing ? '清空中…' : '清空'}
          </Button>
        </div>
      </div>
    </div>
  )
}
