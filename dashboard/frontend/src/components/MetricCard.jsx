import React from 'react'

export default function MetricCard({
  title,
  value,
  subtext,
  accentColor = '#3B82F6',
  badge,
  badgeColor
}) {
  return (
    <div className="bg-[#0D0D0D] border border-[#1F1F1F] rounded-none relative overflow-hidden p-5">
      {/* Top accent strip */}
      <div
        className="absolute top-0 left-0 right-0 h-[2px]"
        style={{ background: accentColor }}
      />

      <div className="mt-1">
        <div className="text-[#64748B] text-xs font-mono uppercase tracking-widest mb-3">
          {title}
        </div>

        <div className="flex items-baseline gap-3 mb-2">
          <div className="text-[#F1F5F9] text-3xl font-mono font-bold leading-none">
            {value ?? '—'}
          </div>
          {badge != null && (
            <span
              className="text-xs font-mono font-bold px-2 py-0.5 rounded-sm"
              style={{
                backgroundColor: badgeColor ? `${badgeColor}22` : '#3B82F622',
                color: badgeColor || '#3B82F6',
                border: `1px solid ${badgeColor ? `${badgeColor}44` : '#3B82F644'}`
              }}
            >
              {badge}
            </span>
          )}
        </div>

        {subtext != null && (
          <div className="text-[#64748B] text-xs">
            {subtext}
          </div>
        )}
      </div>
    </div>
  )
}
