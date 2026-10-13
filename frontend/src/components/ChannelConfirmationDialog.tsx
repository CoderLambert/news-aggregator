import { useEffect, useRef } from 'react'
import { Button } from '@/components/ui/button'

export default function ChannelConfirmationDialog({ description, pending, error, onConfirm, onCancel }: {
  description: string; pending: boolean; error?: string; onConfirm: () => void; onCancel: () => void
}) {
  const dialogRef = useRef<HTMLDialogElement>(null)
  const cancelRef = useRef<HTMLButtonElement>(null)
  const pendingRef = useRef(pending)
  useEffect(() => { pendingRef.current = pending }, [pending])
  useEffect(() => {
    const dialog = dialogRef.current
    const previous = document.activeElement
    dialog?.showModal()
    cancelRef.current?.focus()
    return () => {
      dialog?.close()
      if (previous instanceof HTMLElement && previous.isConnected) previous.focus()
    }
  }, [])
  return <dialog ref={dialogRef} role="alertdialog" aria-labelledby="channel-confirm-title" aria-describedby="channel-confirm-description"
    aria-busy={pending} onCancel={e => { e.preventDefault(); if (!pendingRef.current) onCancel() }}
    className="m-auto w-[min(92vw,28rem)] rounded-xl border border-border bg-card p-5 text-foreground shadow-xl backdrop:bg-black/40">
    <h2 id="channel-confirm-title" className="font-semibold">确认操作</h2>
    <p id="channel-confirm-description" className="my-3 text-sm">{description}</p>
    {error && <p role="alert" className="my-3 text-sm text-red-700">{error}</p>}
    <div className="flex gap-2"><Button disabled={pending} onClick={onConfirm}>{pending ? '正在处理…' : '确认'}</Button>
      <Button ref={cancelRef} variant="outline" disabled={pending} onClick={onCancel}>取消</Button></div>
  </dialog>
}
