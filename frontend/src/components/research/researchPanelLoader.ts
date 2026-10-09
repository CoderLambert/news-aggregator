let panelPromise: Promise<typeof import('./ResearchPanel')> | null = null

export function loadResearchPanel() {
  panelPromise ??= import('./ResearchPanel').catch((error) => {
    panelPromise = null
    throw error
  })
  return panelPromise
}

export function prefetchResearchPanel() {
  void loadResearchPanel().catch(() => undefined)
}
