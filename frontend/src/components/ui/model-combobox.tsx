import { useId, useRef, useState } from 'react'
import * as Popover from '@radix-ui/react-popover'
import { Command } from 'cmdk'
import { Check, ChevronsUpDown, Search } from 'lucide-react'
import { Button } from '@/components/ui/button'

interface Option { value: string; label: string; description?: string; disabled?: boolean }
/** shadcn-style Radix Popover + Command composition, with bounded scrolling. */
export function ModelCombobox({ label, options, value, onChange, disabled = false, searchLabel = "搜索模型", searchPlaceholder = "搜索模型名称或 ID…", emptyText = "没有匹配的可选模型。", placeholder = "搜索并选择模型", wrapLabels = false }: {
  label: string; options: Option[]; value: string; onChange: (value: string) => void; disabled?: boolean
  searchLabel?: string; searchPlaceholder?: string; emptyText?: string; placeholder?: string; wrapLabels?: boolean
}) {
  const [open, setOpen] = useState(false)
  const id = useId()
  const trigger = useRef<HTMLButtonElement>(null)
  const [container, setContainer] = useState<HTMLDialogElement | undefined>(undefined)
  const selected = options.find(option => option.value === value)
  return <Popover.Root open={open} onOpenChange={next => {
    if (next) setContainer(trigger.current?.closest("dialog") ?? undefined)
    setOpen(next)
  }}>
    <Popover.Trigger asChild>
      <Button ref={trigger} type="button" variant="outline" role="combobox" aria-label={label} aria-expanded={open} aria-controls={id}
        disabled={disabled} className="h-10 w-full min-w-0 justify-between font-normal">
        <span className="truncate" title={selected?.label}>{selected?.label ?? placeholder}</span><ChevronsUpDown className="size-4 shrink-0 text-muted-foreground" />
      </Button>
    </Popover.Trigger>
    <Popover.Portal container={container}><Popover.Content onEscapeKeyDown={event => event.stopPropagation()} align="start" sideOffset={6} collisionPadding={16}
      className="z-50 w-[var(--radix-popover-trigger-width)] min-w-64 max-w-[calc(100vw-32px)] overflow-hidden rounded-xl border bg-popover p-1 text-popover-foreground shadow-lg">
      <Command label={searchLabel} className="w-full" loop>
        <div className="model-picker-search flex items-center gap-2 border-b px-3"><Search className="size-4 text-muted-foreground" />
          <Command.Input aria-label={searchLabel} placeholder={searchPlaceholder} className="h-11 min-w-0 w-full bg-transparent text-sm outline-none" />
        </div>
        <Command.List id={id} className="max-h-64 overflow-y-auto overscroll-contain p-1">
          <Command.Empty className="p-5 text-center text-sm text-muted-foreground">{emptyText}</Command.Empty>
          {options.map(option => <Command.Item key={option.value || "none"} value={option.value || "none"} disabled={option.disabled} keywords={[option.label, option.description ?? ""]}
            onSelect={() => { onChange(option.value); setOpen(false) }}
            className="flex cursor-pointer items-center gap-3 rounded-md px-3 py-2 text-sm outline-none data-[selected=true]:bg-accent data-[selected=true]:text-accent-foreground data-[disabled=true]:pointer-events-none data-[disabled=true]:opacity-50">
            <div className="min-w-0 flex-1"><span title={option.label} className={wrapLabels ? "block whitespace-normal break-words" : "block truncate"}>{option.label}</span>
              {option.description && <span className="block truncate text-xs text-muted-foreground">{option.description}</span>}</div>
            {option.value === value && <Check className="size-4 text-primary" />}
          </Command.Item>)}
        </Command.List>
      </Command>
    </Popover.Content></Popover.Portal>
  </Popover.Root>
}
