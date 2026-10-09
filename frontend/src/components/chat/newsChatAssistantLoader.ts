let assistantPromise: Promise<typeof import('@/components/NewsChatAssistant')> | null = null

export function loadNewsChatAssistant() {
  assistantPromise ??= import('@/components/NewsChatAssistant').catch((error) => {
    assistantPromise = null
    throw error
  })
  return assistantPromise
}

export function prefetchNewsChatAssistant() {
  void loadNewsChatAssistant().catch(() => undefined)
}

export function reloadNewsChatPage() {
  window.location.reload()
}
