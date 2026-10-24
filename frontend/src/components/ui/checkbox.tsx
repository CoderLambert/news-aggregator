import type { ComponentProps } from 'react'

import { cn } from '@/lib/utils'

// This repository does not ship Radix Checkbox. Keep the native semantic input
// behind one shared control instead of duplicating hand-styled checkboxes.
type CheckboxProps = Omit<ComponentProps<'input'>, 'type'>

function Checkbox({ className, ...props }: CheckboxProps) {
  return (
    <input
      type="checkbox"
      data-slot="checkbox"
      className={cn(
        'size-4 shrink-0 cursor-pointer rounded border-border accent-primary outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50',
        className,
      )}
      {...props}
    />
  )
}

export { Checkbox }
