import React, { useEffect, useState } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { getToken, getAgentStatus, getAgentLogs } from '../api'
import Sidebar from '../components/Sidebar'
import AgentCard from '../components/AgentCard'

const AGENT_NAMES = [
  'FINANCE RECONCILIATION AGENT',
  'GOOGLE SHEETS SYNC AGENT',
  'SLACK REPORTER AGENT',
  'WHATSAPP ALERTS AGENT',
  'TREND WATCHER AGENT',
  'KEYWORD INTELLIGENCE AGENT'
]

const PAGE_SIZE = 25

function statusColor(status) {
  switch ((status || '').toLowerCase()) {
    case 'success': return 'text-[#00FF88]'
    case 'warning': return 'text-[#F59E0B]'
    case 'error': return 'text-[#EF4444]'
    default: return 'text-[#64748B]'
  }
}

function timeAgo(isoString) {
  if (!isoString) return '—'
  const diff = Math.floor((Date.now() - new Date(isoString).getTime()) / 1000)
  if (diff < 60) return `${diff}s ago`
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return `${Math.floor(diff / 86400)}d ago`
}

export default function MissionControl() {
  const navigate = useNavigate()
  const location = useLocation()
  const [agentStatus, setAgentStatus] = useState([])
  const [logs, setLogs] = useState([])
  const [page, setPage] = useState(0)

  useEffect(() => {
    if (!getToken()) navigate('/login')
  }, [navigate])

  async function fetchData() {
    try {
      const [s, l] = await Promise.allSettled([
        getAgentStatus(),
        getAgentLogs(100)
      ])
      if (s.status === 'fulfilled') {
        setAgentStatus(s.value?.data || [])
      }
      if (l.status === 'fulfilled') {
        setLogs(l.value?.data || [])
      }
    } catch (_) {}
  }

  useEffect(() => {
    fetchData()
    const id = setInterval(fetchData, 30000)
    return () => clearInterval(id)
  }, [])

  // Build agent cards merging API data with the canonical name list
  const agentMap = {}
  agentStatus.forEach((a) => {
    const key = (a.agent_name || '').toUpperCase()
    agentMap[key] = a
  })

  const agentCards = AGENT_NAMES.map((name) => {
    return agentMap[name] || { agent_name: name, status: 'idle' }
  })

  // Determine system status
  const hasError = agentCards.some((a) => a.status === 'error')
  const systemLabel = hasError ? '● DEGRADED' : '● ALL SYSTEMS'
  const systemColor = hasError ? 'text-[#EF4444]' : 'text-[#00FF88]'

  // Pagination
  const totalPages = Math.ceil(logs.length / PAGE_SIZE)
  const pagedLogs = logs.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE)

  return (
    <div className="flex bg-black min-h-screen">
      <Sidebar currentPath={location.pathname} />

      <main className="flex-1 ml-64 overflow-y-auto p-6 space-y-6">
        {/* Header */}
        <div className="flex items-center gap-4">
          <h1 className="text-2xl font-bold text-[#F1F5F9]">Mission Control</h1>
          <span className={`font-mono text-xs ${systemColor} border px-2 py-1`}
            style={{ borderColor: hasError ? '#EF444444' : '#00FF8844', background: hasError ? '#EF444411' : '#00FF8811' }}>
            {systemLabel}
          </span>
        </div>

        {/* Agent Grid */}
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
                  <th key={h} className="text-left py-2 px-3 text-[#64748B] font-mono text-xs uppercase tracking-wider font-normal">
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
                      {log.trigger || '—'}
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
                  className="border border-[#1F1F1F] text-[#64748B] font-mono text-xs px-3 py-1 hover:border-[#00FF88] hover:text-[#00FF88] disabled:opacity-40 disabled:cursor-not-allowed transition-all"
                >
                  ← PREV
                </button>
                <button
                  onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
                  disabled={page >= totalPages - 1}
                  className="border border-[#1F1F1F] text-[#64748B] font-mono text-xs px-3 py-1 hover:border-[#00FF88] hover:text-[#00FF88] disabled:opacity-40 disabled:cursor-not-allowed transition-all"
                >
                  NEXT →
                </button>
              </div>
            </div>
          )}
        </div>
      </main>
    </div>
  )
}
