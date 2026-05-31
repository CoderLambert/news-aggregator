import { useEffect } from 'react'
import { Button } from '../ui/button'
import XiaowenMascot from '../mascot/XiaowenMascot'

/**
 * Friendly "are you sure" dialog when the user wants to clear chat history.
 *
 * Replaces the cold native `window.confirm` with an in-app modal that puts
 * 小闻 (the mascot) front-and-center and uses warm copy:
 *   "真的要忘掉我们刚才聊的吗？"
 *
 * Behavior:
 *  - Escape key  → onCancel
 *  - Backdrop    → onCancel
 *  - "再聊聊"    → onCancel
 *  - "清空"      → onConfirm (rose-colored = destructive)
 *
 * Kept as a self-contained component (no shadcn Dialog dependency) so we don't
 * have to register another shadcn primitive just for one use case.
 */
export default function ClearChatDialog({ open, onConfirm, onCancel }) {
  useEffect(() => {
    if (!open) return
    function onKey(e) {
      if (e.key === 'Escape') onCancel?.()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onCancel])

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center p-4 animate-message-pop-in"
      role="alertdialog"
      aria-modal="true"
      aria-labelledby="clear-dialog-title"
    >
      {/* Backdrop */}
      <div
        data-testid="clear-dialog-backdrop"
        className="absolute inset-0 bg-neutral-900/40 backdrop-blur-sm"
        onClick={onCancel}
      />

      {/* Card */}
      <div className="relative w-full max-w-sm rounded-3xl bg-white p-6 shadow-2xl ring-1 ring-neutral-100">
        <div className="flex flex-col items-center text-center">
          <div className="animate-mascot-bob">
            <XiaowenMascot mood="confused" size={72} showShadow autoBlink={false} />
          </div>
          <h2
            id="clear-dialog-title"
            className="mt-3 text-base font-semibold text-neutral-900"
          >
            真的要忘掉我们刚才聊的吗？
          </h2>
          <p className="mt-1.5 text-xs text-neutral-500 leading-relaxed">
            清空后就找不回啦，咱们要从头来过哦。
          </p>
        </div>

        <div className="mt-5 flex gap-2">
          <Button
            type="button"
            variant="outline"
            className="flex-1 rounded-full h-10 text-sm"
            onClick={onCancel}
          >
            再聊聊
          </Button>
          <Button
            type="button"
            className="flex-1 rounded-full h-10 text-sm bg-rose-500 hover:bg-rose-600 text-white"
            onClick={onConfirm}
          >
            清空
          </Button>
        </div>
      </div>
    </div>
  )
}
