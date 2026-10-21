import type { ComponentProps } from 'react'
import { ChevronDown } from 'lucide-react'
import { cn } from '@/lib/utils'

// shadcn-style native select keeps the browser's keyboard picker inside dialogs.
function NativeSelect({ className, children, ...props }: ComponentProps<'select'>) {
  return <div className="relative min-w-0">
    <select data-slot="native-select" className={cn('h-9 w-full appearance-none rounded-md border border-input bg-background py-1 pl-3 pr-8 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:opacity-50', className)} {...props}>{children}</select>
    <ChevronDown className="pointer-events-none absolute right-2.5 top-2.5 size-4 opacity-50" aria-hidden="true" />
  </div>
}

export { NativeSelect }
