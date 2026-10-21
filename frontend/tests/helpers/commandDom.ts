// jsdom lacks browser layout APIs used by cmdk. Filtering remains real.
import { vi } from 'vitest'
vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
Element.prototype.scrollIntoView = vi.fn()
