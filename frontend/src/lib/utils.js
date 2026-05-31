/**
 * cn — class-name merger used by every shadcn component.
 *
 * clsx handles conditional class composition (falsy / object / array forms)
 * and twMerge resolves Tailwind utility conflicts so that the *last* class
 * always wins (e.g. `cn('px-2', 'px-4')` → `'px-4'`, not `'px-2 px-4'`).
 */
import { clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs) {
  return twMerge(clsx(inputs))
}
