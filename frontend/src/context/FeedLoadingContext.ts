import { createContext } from 'react'

// Local layout coordination only; article data remains in TanStack Query.
export const FeedLoadingContext = createContext<((viewer: number | string) => void) | null>(null)
