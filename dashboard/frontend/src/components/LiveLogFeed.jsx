import React, { useEffect, useRef } from 'react'

function formatTime(isoString) {
  if (!isoString) return '??:??:??'
  const d = new Date(isoString)
  const hh = String(d.getHours()).padStart(2, '0')
  const mm = String(d.getMinutes()).padStart(2, '0')
  const ss = String(d.getSeconds()).padStart(2, '0')
  return `${hh}:${mm}:${ss}`
}

function logColor(status) {
  switch (status) {
    case 'success': return 'text-[#00FF88]'
    case 'warning': return 'text-[#F59E0B]'
    case 'error': return 'text-[#EF4444]'
    default: return 'text-[#64748B]'
  }
}

export default function LiveLogFeed({ logs = [] }) {
  const containerRef = useRef(null)

  useEffect(() => {
    if (containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight
    }
  }, [logs])

  return (
    <div
      ref={containerRef}
      className="bg-black border border-[#1F1F1F] p-3 h-64 overflow-y-auto font-mono text-xs"
    >
      {logs.length === 0 ? (
        <div className="text-[#64748B]">No log entries.</div>
      ) : (
        logs.map((log, i) => (
          <div key={i} className={`${logColor(log.status)} leading-relaxed`}>
            [{formatTime(log.started_at || log.timestamp)}]{' '}
            <span className="text-[#F1F5F9]">{log.agent_name || log.agent || 'SYSTEM'}</span>
            {' → '}
            {log.status?.toUpperCase() || 'INFO'}{' '}
            {log.message || log.trigger || ''}
          </div>
        ))
      )}
    </div>
  )
}
