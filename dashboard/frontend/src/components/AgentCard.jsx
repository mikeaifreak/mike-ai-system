import React from 'react'

function timeAgo(isoString) {
  if (!isoString) return '—'
  const diff = Math.floor((Date.now() - new Date(isoString).getTime()) / 1000)
  if (diff < 60) return `${diff}s ago`
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return `${Math.floor(diff / 86400)}d ago`
}

function StatusDot({ status }) {
  if (status === 'running' || status === 'success') {
    return (
      <span className="inline-block w-2 h-2 rounded-full bg-[#00FF88] pulse-dot flex-shrink-0" />
    )
  }
  if (status === 'error') {
    return (
      <span className="inline-block w-2 h-2 rounded-full bg-[#EF4444] flex-shrink-0" />
    )
  }
  return (
    <span className="inline-block w-2 h-2 rounded-full bg-[#64748B] flex-shrink-0" />
  )
}

export default function AgentCard({ agent }) {
  const {
    agent_name = 'UNKNOWN AGENT',
    status = 'idle',
    started_at = null,
    duration_ms = null,
    today_runs = 0,
    success_rate = null,
    error_message = null
  } = agent || {}

  const statusColor =
    status === 'success' || status === 'running'
      ? '#00FF88'
      : status === 'error'
      ? '#EF4444'
      : '#64748B'

  return (
    <div className="bg-[#0D0D0D] border border-[#1F1F1F] p-4">
      {/* Header */}
      <div className="flex items-center gap-2 mb-4">
        <StatusDot status={status} />
        <div className="font-mono text-sm uppercase text-[#F1F5F9] truncate">
          {agent_name}
        </div>
        <span
          className="ml-auto text-xs font-mono px-2 py-0.5 border flex-shrink-0"
          style={{
            color: statusColor,
            borderColor: `${statusColor}44`,
            background: `${statusColor}11`
          }}
        >
          {status.toUpperCase()}
        </span>
      </div>

      {/* Stats grid */}
      <div className="grid grid-cols-2 gap-3 mb-4">
        <div>
          <div className="text-[#64748B] text-[10px] font-mono uppercase tracking-wider mb-1">
            Last Run
          </div>
          <div className="text-[#F1F5F9] text-xs font-mono">
            {timeAgo(started_at)}
          </div>
        </div>
        <div>
          <div className="text-[#64748B] text-[10px] font-mono uppercase tracking-wider mb-1">
            Today's Runs
          </div>
          <div className="text-[#F1F5F9] text-xs font-mono">
            {today_runs ?? '—'}
          </div>
        </div>
        <div>
          <div className="text-[#64748B] text-[10px] font-mono uppercase tracking-wider mb-1">
            Success Rate
          </div>
          <div className="text-[#F1F5F9] text-xs font-mono">
            {success_rate != null ? `${success_rate}%` : '—'}
          </div>
        </div>
        <div>
          <div className="text-[#64748B] text-[10px] font-mono uppercase tracking-wider mb-1">
            Avg Duration
          </div>
          <div className="text-[#F1F5F9] text-xs font-mono">
            {duration_ms != null ? `${duration_ms}ms` : '—'}
          </div>
        </div>
      </div>

      {/* Last error */}
      <div className="border-t border-[#1F1F1F] pt-3">
        <div className="text-[#64748B] text-[10px] font-mono uppercase tracking-wider mb-1">
          Last Error
        </div>
        {error_message ? (
          <div className="text-[#EF4444] text-xs font-mono truncate" title={error_message}>
            {error_message}
          </div>
        ) : (
          <div className="text-[#00FF88] text-xs font-mono">None</div>
        )}
      </div>
    </div>
  )
}
