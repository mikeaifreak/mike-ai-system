import React from 'react'

function timeAgo(isoString) {
  if (!isoString) return '—'
  const diff = Math.floor((Date.now() - new Date(isoString).getTime()) / 1000)
  if (diff < 60) return `${diff}s ago`
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return `${Math.floor(diff / 86400)}d ago`
}

function ChannelBadge({ channel }) {
  const ch = (channel || '').toLowerCase()
  if (ch.includes('slack')) {
    return (
      <span className="text-[10px] font-mono font-bold px-1.5 py-0.5 bg-[#4A154B33] text-[#E01E5A] border border-[#E01E5A44]">
        SL
      </span>
    )
  }
  if (ch.includes('whatsapp')) {
    return (
      <span className="text-[10px] font-mono font-bold px-1.5 py-0.5 bg-[#25D36633] text-[#25D366] border border-[#25D36644]">
        WA
      </span>
    )
  }
  return (
    <span className="text-[10px] font-mono font-bold px-1.5 py-0.5 bg-[#1F1F1F] text-[#64748B] border border-[#1F1F1F]">
      {(channel || 'UN').slice(0, 2).toUpperCase()}
    </span>
  )
}

export default function AlertRow({ alert }) {
  const { alert_type = '', channel = '', message_preview = '', delivered = false, sent_at = null } = alert || {}
  const isAnomaly = alert_type.toLowerCase().includes('anomaly')

  return (
    <tr className={isAnomaly ? 'bg-[#EF444411]' : ''}>
      <td className="py-2 px-3 border-b border-[#1F1F1F]">
        <ChannelBadge channel={channel} />
      </td>
      <td className="py-2 px-3 border-b border-[#1F1F1F]">
        <span className="font-mono text-xs uppercase text-[#64748B]">
          {alert_type || '—'}
        </span>
      </td>
      <td className="py-2 px-3 border-b border-[#1F1F1F] max-w-xs">
        <span className="text-[#F1F5F9] text-xs truncate block">
          {message_preview || '—'}
        </span>
      </td>
      <td className="py-2 px-3 border-b border-[#1F1F1F]">
        <span className="text-[#64748B] text-xs font-mono whitespace-nowrap">
          {timeAgo(sent_at)}
        </span>
      </td>
    </tr>
  )
}
