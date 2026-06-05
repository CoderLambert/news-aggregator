import { useState, useEffect, useRef, useCallback } from 'react'
import {
  listResearchSessions,
  getResearchSession,
  deleteResearchSession as apiDeleteSession,
  createResearchStream,
  researchChatStream,
  getResearchResults,
} from '../services/api'

const ERROR_MESSAGE = '研究过程中遇到了问题，请稍后再试。'

/**
 * Manages the research agent lifecycle.
 *
 * Phases:
 *   - 'idle'            : no active research
 *   - 'thinking'        : agent is processing (LLM deciding which tool to call)
 *   - 'tool_calling'    : agent is executing a tool
 *   - 'streaming'       : final answer text arriving
 *   - 'success'         : research complete
 *   - 'error'           : research failed
 *
 * Messages are stored in a format suitable for rendering:
 *   - user messages: { role: 'user', content: string }
 *   - assistant messages: { role: 'assistant', content: string, toolCalls?: ToolCallEntry[] }
 *   - ToolCallEntry: { callId, name, args, summary?, status: 'running'|'done' }
 */
export function useResearch() {
  const [sessions, setSessions] = useState([])
  const [activeSessionId, setActiveSessionId] = useState(null)
  const [messages, setMessages] = useState([])
  const [phase, setPhase] = useState('idle')
  const [activeToolCalls, setActiveToolCalls] = useState([])
  const [loadingSessions, setLoadingSessions] = useState(false)
  const [searchResults, setSearchResults] = useState([])

  // Track the "current" assistant message being built (tool calls + final text)
  const currentAssistantRef = useRef(null)
  const abortRef = useRef(null)
  // Keep a live ref to activeSessionId so callbacks can access the latest value
  const activeSessionIdRef = useRef(null)
  useEffect(() => { activeSessionIdRef.current = activeSessionId }, [activeSessionId])

  // ── Load sessions list ────────────────────────────────────────────────

  const loadSessions = useCallback(async () => {
    setLoadingSessions(true)
    try {
      const data = await listResearchSessions()
      setSessions(data.results || data)
    } catch (err) {
      console.error('Failed to load research sessions:', err)
    } finally {
      setLoadingSessions(false)
    }
  }, [])

  useEffect(() => {
    loadSessions()
  }, [loadSessions])

  // ── Load session messages when switching ──────────────────────────────

  useEffect(() => {
    if (!activeSessionId) {
      setMessages([])
      setSearchResults([])
      return
    }
    // When a new session is being created (phase is 'thinking' or active),
    // don't clear messages — the user's message was already added
    // optimistically in handleSend. We'll load the server state after
    // the stream completes.
    if (phase === 'thinking' || phase === 'tool_calling' || phase === 'streaming') {
      return
    }
    let cancelled = false
    ;(async () => {
      try {
        const [sessionData, resultsData] = await Promise.all([
          getResearchSession(activeSessionId),
          getResearchResults(activeSessionId, { detail: '1' }),
        ])
        if (cancelled) return
        // Convert stored OpenAI-format messages to render format
        const rendered = convertMessages(sessionData.messages || [])
        setMessages(rendered)
        setSearchResults(resultsData.results || resultsData || [])
        setPhase('idle')
      } catch (err) {
        if (cancelled) return
        console.error('Failed to load session:', err)
      }
    })()
    return () => { cancelled = true }
  }, [activeSessionId])

  // ── Send a research query ─────────────────────────────────────────────

  async function handleSend(query) {
    if (!query.trim()) return

    // Add user message
    const userMsg = { role: 'user', content: query.trim() }
    setMessages(prev => [...prev, userMsg])
    setPhase('thinking')
    setActiveToolCalls([])
    currentAssistantRef.current = { role: 'assistant', content: '', toolCalls: [] }

    try {
      let sessionId = activeSessionId
      let stream

      if (sessionId) {
        stream = researchChatStream(sessionId, query.trim())
      } else {
        // Create new session
        stream = createResearchStream(query.trim())
      }

      for await (const ev of stream) {
        // Capture session ID from 'session_created' event
        if (ev.type === 'session_created' && ev.session_id) {
          sessionId = ev.session_id
          setActiveSessionId(sessionId)
          continue
        }

        processEvent(ev)
      }

      // If no session ID captured from events, reload sessions to find it
      if (!sessionId) {
        loadSessions()
      }
    } catch (err) {
      console.error('Research stream error:', err)
      setPhase('error')
      // Show auth-required message for 401/403 errors
      const msg = err?.message?.includes('401') || err?.message?.includes('403')
        ? '请先登录后再使用研究助手 🔐'
        : ERROR_MESSAGE
      appendAssistantError(msg)
    }
  }

  // ── Process SSE events ────────────────────────────────────────────────

  function processEvent(ev) {
    switch (ev.type) {
      case 'thinking':
        setPhase('thinking')
        break

      case 'query_decomposed':
        // Decomposition is now handled internally by the agent;
        // kept as a no-op handler for backward compatibility
        break

      case 'tool_call': {
        setPhase('tool_calling')
        const entry = {
          callId: ev.call_id,
          name: ev.name,
          args: ev.args,
          summary: '',
          status: 'running',
        }
        setActiveToolCalls(prev => [...prev, entry])
        if (currentAssistantRef.current) {
          currentAssistantRef.current.toolCalls.push(entry)
          updateAssistantMessage()
        }
        break
      }

      case 'tool_result': {
        // Update the matching tool call entry with result data
        setActiveToolCalls(prev =>
          prev.map(tc =>
            tc.callId === ev.call_id
              ? {
                  ...tc,
                  summary: ev.summary || '',
                  status: 'done',
                  // Attach rich result data for ProcessTimeline rendering
                  articles: ev.articles || [],
                  webResults: ev.results || [],
                  articleTitle: ev.title || '',
                  articleId: ev.id || null,
                  articleSource: ev.source || '',
                  articleUrl: ev.url || '',
                  contentTruncated: ev.content_truncated || false,
                  originalLength: ev.original_length || 0,
                  contentLength: ev.length || 0,
                }
              : tc
          )
        )
        if (currentAssistantRef.current) {
          const tc = currentAssistantRef.current.toolCalls.find(
            t => t.callId === ev.call_id
          )
          if (tc) {
            tc.summary = ev.summary || ''
            tc.status = 'done'
            tc.articles = ev.articles || []
            tc.webResults = ev.results || []
            tc.articleTitle = ev.title || ''
            tc.articleId = ev.id || null
            tc.articleSource = ev.source || ''
            tc.articleUrl = ev.url || ''
            tc.contentTruncated = ev.content_truncated || false
            tc.originalLength = ev.original_length || 0
            tc.contentLength = ev.length || 0
          }
          updateAssistantMessage()
        }
        break
      }

      case 'text_delta': {
        setPhase('streaming')
        if (currentAssistantRef.current) {
          currentAssistantRef.current.content += ev.text || ''
          updateAssistantMessage()
        }
        break
      }

      case 'complete': {
        setPhase('success')
        currentAssistantRef.current = null
        setActiveToolCalls([])
        loadSessions() // Refresh session list (title may have been updated)
        // Refresh search results from the API now that the agent has finished
        const sid = activeSessionIdRef.current
        if (sid) {
          getResearchResults(sid, { detail: '1' })
            .then(data => setSearchResults(data.results || data || []))
            .catch(() => {})
        }
        break
      }

      case 'error': {
        setPhase('error')
        appendAssistantError(ev.message || ERROR_MESSAGE)
        currentAssistantRef.current = null
        setActiveToolCalls([])
        break
      }

      default:
        break
    }
  }

  // ── Helpers ───────────────────────────────────────────────────────────

  function updateAssistantMessage() {
    const assistant = currentAssistantRef.current
    if (!assistant) return
    setMessages(prev => {
      // Replace or append the current assistant message
      const last = prev[prev.length - 1]
      if (last && last.role === 'assistant' && last._isCurrent) {
        return [...prev.slice(0, -1), { ...assistant, _isCurrent: true }]
      }
      return [...prev, { ...assistant, _isCurrent: true }]
    })
  }

  function appendAssistantError(text) {
    setMessages(prev => [
      ...prev,
      { role: 'assistant', content: text, toolCalls: [] },
    ])
  }

  // ── Session management ────────────────────────────────────────────────

  function handleNewSession() {
    setActiveSessionId(null)
    setMessages([])
    setSearchResults([])
    setPhase('idle')
    setActiveToolCalls([])
    currentAssistantRef.current = null
  }

  function handleSelectSession(id) {
    if (id === activeSessionId) return
    setActiveSessionId(id)
    setPhase('idle')
    setActiveToolCalls([])
    currentAssistantRef.current = null
  }

  async function handleDeleteSession(id) {
    try {
      await apiDeleteSession(id)
      if (activeSessionId === id) {
        handleNewSession()
      }
      loadSessions()
    } catch (err) {
      console.error('Failed to delete session:', err)
    }
  }

  return {
    sessions,
    activeSessionId,
    messages,
    phase,
    activeToolCalls,
    loadingSessions,
    searchResults,
    handleSend,
    handleNewSession,
    handleSelectSession,
    handleDeleteSession,
    loadSessions,
  }
}

// ── Message format converter ─────────────────────────────────────────────

/**
 * Convert OpenAI-format messages from the database into render-friendly format.
 * Groups consecutive tool_call + tool result messages with their assistant message.
 */
function convertMessages(rawMessages) {
  const result = []
  let i = 0

  while (i < rawMessages.length) {
    const msg = rawMessages[i]

    if (msg.role === 'system') {
      i++
      continue
    }

    if (msg.role === 'user') {
      result.push({ role: 'user', content: msg.content })
      i++
      continue
    }

    if (msg.role === 'assistant') {
      const assistant = {
        role: 'assistant',
        content: msg.content || '',
        toolCalls: [],
      }

      // Collect tool calls from this assistant message
      if (msg.tool_calls) {
        for (const tc of msg.tool_calls) {
          assistant.toolCalls.push({
            callId: tc.id,
            name: tc.function?.name || '',
            args: safeParseJSON(tc.function?.arguments || '{}'),
            summary: '',
            status: 'done',
          })
        }
      }

      result.push(assistant)
      i++

      // Skip following tool result messages (they're already captured in toolCalls)
      while (i < rawMessages.length && rawMessages[i].role === 'tool') {
        const toolMsg = rawMessages[i]
        // Try to match tool result to a toolCall entry
        const match = assistant.toolCalls.find(
          tc => tc.callId === toolMsg.tool_call_id
        )
        if (match) {
          const parsed = safeParseJSON(toolMsg.content || '{}')
          match.summary = buildToolSummary(match.name, parsed)
          // Populate rich result data from stored tool results
          match.articles = parsed.articles || []
          match.webResults = parsed.results || []
          match.articleTitle = parsed.title || ''
          match.articleId = parsed.id || null
          match.articleSource = parsed.source || ''
          match.articleUrl = parsed.url || ''
          match.contentTruncated = parsed.content_truncated || false
          match.originalLength = parsed.original_length || 0
          match.contentLength = parsed.length || 0
        }
        i++
      }
      continue
    }

    // Skip unknown roles
    i++
  }

  return result
}

function safeParseJSON(str) {
  try {
    return JSON.parse(str)
  } catch {
    return {}
  }
}

function buildToolSummary(name, result) {
  if (result.error) return `❌ ${result.error}`
  if (name === 'search_news') return `找到 ${result.total || 0} 篇相关文章`
  if (name === 'fetch_article') return `已获取文章`
  if (name === 'search_web') return `联网搜索到 ${(result.results || []).length} 条结果`
  if (name === 'fetch_webpage') return `已抓取网页`
  if (name === 'analyze_topic') return `分析完成: ${result.total_articles || 0} 篇文章`
  if (name === 'generate_report') return `报告结构生成`
  return `${name} 完成`
}
