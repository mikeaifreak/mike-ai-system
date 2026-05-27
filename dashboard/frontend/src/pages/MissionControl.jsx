import React, { useEffect, useRef, useState } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import {
  getToken,
  getAgentStatus,
  getAgentLogs,
  sendAgentChatStream,
} from '../api'
import Sidebar from '../components/Sidebar'
import AgentCard from '../components/AgentCard'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const AGENT_NAMES = [
  'Finance Reconciliation Agent',
  'Google Sheets Sync Agent',
  'Slack Reporter Agent',
  'WhatsApp Alerts Agent',
  'Trend Watcher Agent',
  'Keyword Intelligence Agent',
]

// isCommand=true chips trigger pipeline execution on the backend
const QUICK_ACTIONS = {
  'Finance Reconciliation Agent': [
    { label: 'Run reconciliation now',   isCommand: true  },
    { label: 'Show last run results',    isCommand: false },
    { label: 'Any mismatches?',          isCommand: false },
    { label: 'Show 7-day reprocess log', isCommand: false },
  ],
  'Google Sheets Sync Agent': [
    { label: 'Sync now',                 isCommand: true  },
    { label: 'Last sync status',         isCommand: false },
    { label: 'How many rows pulled?',    isCommand: false },
    { label: 'Any errors?',              isCommand: false },
  ],
  'Slack Reporter Agent': [
    { label: 'Send report now',          isCommand: true  },
    { label: "Preview today's report",   isCommand: false },
    { label: 'Last report sent?',        isCommand: false },
    { label: 'Change report format',     isCommand: false },
  ],
  'WhatsApp Alerts Agent': [
    { label: 'Send EOD now',             isCommand: true  },
    { label: 'Last message sent?',       isCommand: false },
    { label: 'Test WhatsApp connection', isCommand: false },
    { label: 'Show alert history',       isCommand: false },
  ],
  'Trend Watcher Agent': [
    { label: 'Run trend scan',           isCommand: true  },
    { label: 'Top trends today',         isCommand: false },
    { label: 'Show keyword list',        isCommand: false },
    { label: 'Any anomalies?',           isCommand: false },
  ],
  'Keyword Intelligence Agent': [
    { label: 'Run keyword scan',         isCommand: true  },
    { label: 'Top keywords today',       isCommand: false },
    { label: 'Show competition scores',  isCommand: false },
    { label: 'Export keywords',          isCommand: false },
  ],
}

const AGENT_GREETINGS = {
  'Finance Reconciliation Agent':
    'Finance Reconciliation Agent online.\nI monitor data accuracy between Shopify and your P&L sheet. How can I help?',
  'Google Sheets Sync Agent':
    'Google Sheets Sync Agent online.\nI manage your P&L sheet synchronisation. What do you need?',
  'Slack Reporter Agent':
    'Slack Reporter Agent online.\nI handle your daily P&L reports. Ask me anything.',
  'WhatsApp Alerts Agent':
    'WhatsApp Alerts Agent online.\nI send your EOD summaries to WhatsApp. How can I help?',
  'Trend Watcher Agent':
    'Trend Watcher Agent online.\nI monitor product and market trends. What would you like to know?',
  'Keyword Intelligence Agent':
    'Keyword Intelligence Agent online.\nI analyse keyword performance. What are you looking for?',
}

const COMMAND_KEYWORDS_FE = new Set(['run', 'sync', 'send', 'execute', 'trigger'])
const PAGE_SIZE = 25

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function statusColor(status) {
  switch ((status || '').toLowerCase()) {
    case 'success': return 'text-[#00FF88]'
    case 'warning': return 'text-[#F59E0B]'
    case 'error':   return 'text-[#EF4444]'
    default:        return 'text-[#64748B]'
  }
}

function timeAgo(isoString) {
  if (!isoString) return '—'
  const diff = Math.floor((Date.now() - new Date(isoString).getTime()) / 1000)
  if (diff < 60)    return `${diff}s ago`
  if (diff < 3600)  return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return `${Math.floor(diff / 86400)}d ago`
}

function isCommandMsg(text) {
  const first = (text || '').trim().toLowerCase().split(/\s+/)[0] || ''
  return COMMAND_KEYWORDS_FE.has(first)
}

// ---------------------------------------------------------------------------
// AgentChatPanel — right 40% column
// ---------------------------------------------------------------------------

const JETBRAINS = { fontFamily: '"JetBrains Mono", ui-monospace, monospace' }

function AgentChatPanel() {
  const [selectedAgent, setSelectedAgent] = useState(AGENT_NAMES[0])
  const [messages, setMessages] = useState([
    { role: 'agent', content: AGENT_GREETINGS[AGENT_NAMES[0]], isCommand: false },
  ])
  const [input, setInput]       = useState('')
  const [streaming, setStreaming] = useState(false)
  const messagesEndRef = useRef(null)
  const inputRef       = useRef(null)

  // Reset chat to greeting when agent changes
  useEffect(() => {
    setMessages([
      { role: 'agent', content: AGENT_GREETINGS[selectedAgent], isCommand: false },
    ])
    setInput('')
    setStreaming(false)
  }, [selectedAgent])

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  async function handleSend(text, chipIsCommand = false) {
    const msg = (text !== undefined ? text : input).trim()
    if (!msg || streaming) return

    setInput('')
    const isCmd = chipIsCommand || isCommandMsg(msg)

    setMessages((prev) => [
      ...prev,
      { role: 'user',  content: msg },
      { role: 'agent', content: '', streaming: true, isCommand: isCmd },
    ])
    setStreaming(true)

    try {
      await sendAgentChatStream(
        selectedAgent,
        msg,
        (chunk) => {
          setMessages((prev) => {
            const updated = [...prev]
            const last = updated[updated.length - 1]
            if (last?.role === 'agent') {
              updated[updated.length - 1] = {
                ...last,
                content: last.content + chunk,
              }
            }
            return updated
          })
        },
        () => {
          setStreaming(false)
          setMessages((prev) => {
            const updated = [...prev]
            const last = updated[updated.length - 1]
            if (last?.role === 'agent') {
              updated[updated.length - 1] = { ...last, streaming: false }
            }
            return updated
          })
        },
      )
    } catch (err) {
      setStreaming(false)
      setMessages((prev) => {
        const updated = [...prev]
        const last = updated[updated.length - 1]
        if (last?.role === 'agent') {
          updated[updated.length - 1] = {
            ...last,
            content: `Error: ${err.message}`,
            streaming: false,
          }
        }
        return updated
      })
    }
  }

  function handleKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const chips         = QUICK_ACTIONS[selectedAgent] || []
  const agentFirstName = selectedAgent.split(' ')[0]

  return (
    <aside className="w-2/5 flex-shrink-0 border-l border-[#1F1F1F] flex flex-col">

      {/* ─── Header ─── */}
      <div className="px-4 py-3 border-b border-[#1F1F1F] flex-shrink-0">
        <div
          className="text-[#00FF88] font-bold text-[11px] tracking-[0.18em] uppercase"
          style={JETBRAINS}
        >
          Talk to Your Agents
        </div>
        <div className="text-[#3A3A3A] text-[10px] mt-0.5" style={JETBRAINS}>
          Select an agent — ask questions or run commands
        </div>
      </div>

      {/* ─── Agent Selector ─── */}
      <div className="px-4 py-3 border-b border-[#1F1F1F] flex-shrink-0">
        <div className="relative">
          <select
            value={selectedAgent}
            onChange={(e) => setSelectedAgent(e.target.value)}
            className="w-full bg-[#0D0D0D] border border-[#2A2A2A] text-[#F1F5F9] text-xs
                       px-3 py-2 pr-8 focus:border-[#00FF88] focus:outline-none
                       appearance-none cursor-pointer hover:border-[#3A3A3A] transition-colors"
            style={JETBRAINS}
          >
            {AGENT_NAMES.map((name) => (
              <option key={name} value={name} className="bg-[#0D0D0D]">
                {name}
              </option>
            ))}
          </select>
          {/* Chevron */}
          <div className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-[#64748B] text-[10px]">
            ▾
          </div>
        </div>
      </div>

      {/* ─── Messages ─── */}
      <div className="flex-1 overflow-y-auto p-3 space-y-3 min-h-0">
        {messages.map((msg, i) => (
          <div
            key={i}
            className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
          >
            {msg.role === 'user' ? (
              <div
                className="bg-[#1A1A1A] text-[#F1F5F9] px-3 py-2 text-[11px] max-w-[85%]"
                style={JETBRAINS}
              >
                {msg.content}
              </div>
            ) : (
              <div
                className="bg-[#040404] border border-[#181818] px-3 py-2.5 text-[11px]
                           max-w-full w-full"
                style={JETBRAINS}
              >
                <div
                  className="text-[#00FF88] whitespace-pre-wrap leading-relaxed"
                  style={{ wordBreak: 'break-word' }}
                >
                  {msg.content || ''}
                </div>
                {msg.streaming && (
                  <span
                    className="inline-block text-[#00FF88] ml-0.5"
                    style={{ animation: 'pulse-dot 0.8s ease-in-out infinite' }}
                  >
                    ▋
                  </span>
                )}
              </div>
            )}
          </div>
        ))}
        <div ref={messagesEndRef} />
      </div>

      {/* ─── Quick Action Chips ─── */}
      <div className="flex flex-wrap gap-1.5 px-3 py-2.5 border-t border-[#1F1F1F] flex-shrink-0">
        {chips.map((chip) => (
          <button
            key={chip.label}
            onClick={() => handleSend(chip.label, chip.isCommand)}
            disabled={streaming}
            className="border border-[#1E1E1E] text-[#64748B] text-[10px] px-2.5 py-1
                       hover:border-[#00FF88] hover:text-[#00FF88] transition-all
                       disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
            style={JETBRAINS}
          >
            {chip.label}
          </button>
        ))}
      </div>

      {/* ─── Input Bar ─── */}
      <div className="border-t border-[#1F1F1F] p-3 flex gap-2 flex-shrink-0">
        <input
          ref={inputRef}
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={streaming}
          placeholder={`Ask or command ${agentFirstName}...`}
          className="bg-black border border-[#1F1F1F] text-[#F1F5F9] px-3 py-2 flex-1 text-[11px]
                     focus:border-[#00FF88] outline-none disabled:opacity-40
                     placeholder-[#2A2A2A]"
          style={JETBRAINS}
        />
        <button
          onClick={() => handleSend()}
          disabled={streaming || !input.trim()}
          className="bg-[#00FF88] text-black px-4 py-2 font-bold text-xs
                     disabled:opacity-40 disabled:cursor-not-allowed
                     hover:bg-[#00DD77] transition-colors"
          style={JETBRAINS}
          aria-label="Send"
        >
          {streaming ? '···' : '→'}
        </button>
      </div>

    </aside>
  )
}

// ---------------------------------------------------------------------------
// MissionControl — main page with 60/40 split layout
// ---------------------------------------------------------------------------

export default function MissionControl() {
  const navigate = useNavigate()
  const location = useLocation()
  const [agentStatus, setAgentStatus] = useState([])
  const [logs, setLogs]   = useState([])
  const [page, setPage]   = useState(0)

  useEffect(() => {
    if (!getToken()) navigate('/login')
  }, [navigate])

  async function fetchData() {
    try {
      const [s, l] = await Promise.allSettled([
        getAgentStatus(),
        getAgentLogs(100),
      ])
      if (s.status === 'fulfilled') setAgentStatus(s.value?.data || [])
      if (l.status === 'fulfilled') setLogs(l.value?.data || [])
    } catch (_) {}
  }

  useEffect(() => {
    fetchData()
    const id = setInterval(fetchData, 30000)
    return () => clearInterval(id)
  }, [])

  // Merge API data with canonical agent name list (case-insensitive)
  const agentMap = {}
  agentStatus.forEach((a) => {
    agentMap[(a.agent_name || '').toUpperCase()] = a
  })
  const agentCards = AGENT_NAMES.map((name) =>
    agentMap[name.toUpperCase()] || { agent_name: name, status: 'idle' }
  )

  const hasError    = agentCards.some((a) => a.status === 'error')
  const systemLabel = hasError ? '● DEGRADED' : '● ALL SYSTEMS'
  const systemColor = hasError ? 'text-[#EF4444]' : 'text-[#00FF88]'

  const totalPages = Math.ceil(logs.length / PAGE_SIZE)
  const pagedLogs  = logs.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE)

  return (
    <div className="flex bg-black h-screen overflow-hidden">
      <Sidebar currentPath={location.pathname} />

      {/* ── Split content: left 60%, right 40% ── */}
      <div className="flex-1 ml-64 flex overflow-hidden">

        {/* ════════════ LEFT — Agent Grid + Log ════════════ */}
        <main className="w-3/5 overflow-y-auto p-6 space-y-6">

          {/* Header */}
          <div className="flex items-center gap-4">
            <h1 className="text-2xl font-bold text-[#F1F5F9]">Mission Control</h1>
            <span
              className={`font-mono text-xs ${systemColor} border px-2 py-1`}
              style={{
                borderColor: hasError ? '#EF444444' : '#00FF8844',
                background:  hasError ? '#EF444411' : '#00FF8811',
              }}
            >
              {systemLabel}
            </span>
          </div>

          {/* Agent Grid (2 columns) */}
          <div className="grid grid-cols-2 gap-4">
            {agentCards.map((agent) => (
              <AgentCard key={agent.agent_name} agent={agent} />
            ))}
          </div>

          {/* Execution Log */}
          <div className="bg-[#0A0A0A] border border-[#1F1F1F] p-4">
            <div className="text-[#64748B] font-mono text-xs uppercase tracking-widest mb-3">
              Execution Log
            </div>
            <table className="w-full border-collapse text-xs">
              <thead>
                <tr className="border-b border-[#1F1F1F]">
                  {['Time', 'Agent', 'Trigger', 'Status', 'Duration', 'Rows', 'Tokens'].map((h) => (
                    <th
                      key={h}
                      className="text-left py-2 px-3 text-[#64748B] font-mono text-xs
                                 uppercase tracking-wider font-normal"
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {pagedLogs.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="py-4 px-3 text-[#64748B] font-mono text-center">
                      No execution logs
                    </td>
                  </tr>
                ) : (
                  pagedLogs.map((log, i) => (
                    <tr key={i} className="hover:bg-[#1A1A1A] border-b border-[#0D0D0D]">
                      <td className="py-2 px-3 font-mono text-[#64748B] whitespace-nowrap">
                        {timeAgo(log.started_at || log.timestamp)}
                      </td>
                      <td className="py-2 px-3 font-mono text-[#F1F5F9] uppercase text-xs">
                        {log.agent_name || log.agent || '—'}
                      </td>
                      <td className="py-2 px-3 font-mono text-[#64748B]">
                        {log.trigger_type || log.trigger || '—'}
                      </td>
                      <td className={`py-2 px-3 font-mono uppercase ${statusColor(log.status)}`}>
                        {log.status || '—'}
                      </td>
                      <td className="py-2 px-3 font-mono text-[#64748B]">
                        {log.duration_ms != null ? `${log.duration_ms}ms` : '—'}
                      </td>
                      <td className="py-2 px-3 font-mono text-[#64748B]">
                        {log.rows_processed ?? '—'}
                      </td>
                      <td className="py-2 px-3 font-mono text-[#64748B]">
                        {log.tokens_used ?? '—'}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>

            {/* Pagination */}
            {totalPages > 1 && (
              <div className="flex items-center justify-between mt-4 pt-3 border-t border-[#1F1F1F]">
                <div className="text-[#64748B] font-mono text-xs">
                  Page {page + 1} of {totalPages} ({logs.length} entries)
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={() => setPage((p) => Math.max(0, p - 1))}
                    disabled={page === 0}
                    className="border border-[#1F1F1F] text-[#64748B] font-mono text-xs px-3 py-1
                               hover:border-[#00FF88] hover:text-[#00FF88]
                               disabled:opacity-40 disabled:cursor-not-allowed transition-all"
                  >
                    ← PREV
                  </button>
                  <button
                    onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
                    disabled={page >= totalPages - 1}
                    className="border border-[#1F1F1F] text-[#64748B] font-mono text-xs px-3 py-1
                               hover:border-[#00FF88] hover:text-[#00FF88]
                               disabled:opacity-40 disabled:cursor-not-allowed transition-all"
                  >
                    NEXT →
                  </button>
                </div>
              </div>
            )}
          </div>

        </main>

        {/* ════════════ RIGHT — Agent Chat Panel ════════════ */}
        <AgentChatPanel />

      </div>
    </div>
  )
}
