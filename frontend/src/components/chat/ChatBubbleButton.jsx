/**
 * Floating action button — opens the chat panel.
 */
export default function ChatBubbleButton({ onOpen }) {
  return (
    <button
      type="button"
      onClick={onOpen}
      aria-label="打开 AI 新闻助手"
      title="AI 助手"
      className="fixed bottom-6 right-6 z-50 w-14 h-14 bg-gradient-to-br from-violet-500 to-indigo-600
                 text-white rounded-full shadow-lg hover:shadow-xl hover:scale-105 active:scale-95
                 transition-all duration-200 flex items-center justify-center group"
    >
      <svg className="w-7 h-7 group-hover:rotate-12 transition-transform" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.455 2.456L21.75 6l-1.036.259a3.375 3.375 0 00-2.455 2.456zM16.894 20.567L16.5 21.75l-.394-1.183a2.25 2.25 0 00-1.423-1.423L13.5 18.75l1.183-.394a2.25 2.25 0 001.423-1.423l.394-1.183.394 1.183a2.25 2.25 0 001.423 1.423l1.183.394-1.183.394a2.25 2.25 0 00-1.423 1.423z" />
      </svg>
    </button>
  )
}
