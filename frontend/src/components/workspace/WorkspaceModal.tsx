import { useEffect, useId, useRef } from 'react'
import type { ReactNode } from 'react'
import { X } from 'lucide-react'

export default function WorkspaceModal({ title, children, onClose, busy = false, className = '' }: { title: string; children: ReactNode; onClose: () => void; busy?: boolean; className?: string }) {
  const ref = useRef<HTMLDialogElement>(null)
  const headingId = useId()
  const busyRef = useRef(busy)
  useEffect(() => { busyRef.current = busy }, [busy])
  useEffect(() => {
    const previous = document.activeElement
    const dialog = ref.current
    if (dialog && !dialog.open) dialog.showModal()
    return () => {
      dialog?.close()
      if (previous instanceof HTMLElement && previous.isConnected) previous.focus()
    }
  }, [])
  return <dialog ref={ref} className={`workspace-modal ${className}`} aria-labelledby={headingId} aria-busy={busy}
    onCancel={event => { event.preventDefault(); if (!busyRef.current) onClose() }}>
    <header className="workspace-modal-heading"><h2 id={headingId}>{title}</h2>
      <button type="button" className="workspace-icon" aria-label={'关闭' + title} onClick={onClose} disabled={busy}><X size={18} aria-hidden="true" /></button>
    </header>
    {children}
  </dialog>
}
