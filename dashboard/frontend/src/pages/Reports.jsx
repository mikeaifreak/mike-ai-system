import React, { useEffect, useState } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { getToken, getMTD, getWeekly, getMonthly } from '../api'
import Sidebar from '../components/Sidebar'

function formatCurrency(val) {
  if (val == null) return '—'
  return '$' + Number(val).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function formatPct(val) {
  if (val == null) return '—'
  return Number(val).toFixed(1) + '%'
}

export default function Reports() {
  const navigate = useNavigate()
  const location = useLocation()
  const [mtd, setMtd] = useState(null)
  const [weekly, setWeekly] = useState([])
  const [monthly, setMonthly] = useState([])

  useEffect(() => {
    if (!getToken()) navigate('/login')
  }, [navigate])

  useEffect(() => {
    async function fetchAll() {
      const [m, w, mo] = await Promise.allSettled([getMTD(), getWeekly(), getMonthly()])
      if (m.status === 'fulfilled') setMtd(m.value?.mtd || m.value || null)
      if (w.status === 'fulfilled') setWeekly(w.value?.weeks || w.value || [])
      if (mo.status === 'fulfilled') setMonthly(mo.value?.months || mo.value || [])
    }
    fetchAll()
  }, [])

  const mtdStats = mtd ? [
    { label: 'Revenue', value: formatCurrency(mtd.revenue) },
    { label: 'Profit', value: formatCurrency(mtd.profit) },
    { label: 'Ad Spend', value: formatCurrency(mtd.ad_spend) },
    { label: 'Refunds', value: formatCurrency(mtd.refunds ?? mtd.total_refunds) },
    { label: 'Avg ROAS', value: mtd.avg_roas != null ? `${Number(mtd.avg_roas).toFixed(2)}x` : '—' },
    { label: 'Avg Margin', value: formatPct(mtd.avg_margin ?? mtd.margin_pct) }
  ] : []

  return (
    <div className="flex bg-black min-h-screen">
      <Sidebar currentPath={location.pathname} />

      <main className="flex-1 ml-64 overflow-y-auto p-6 space-y-6">
        {/* Header */}
        <h1 className="text-2xl font-bold text-[#F1F5F9]">Reports</h1>

        {/* MTD Summary Card */}
        <div className="bg-[#0A0A0A] border border-[#1F1F1F] p-6">
          <div className="flex items-baseline gap-3 mb-5">
            <div className="text-[#64748B] font-mono text-xs uppercase tracking-widest">
              Month-to-Date Summary
            </div>
            {mtd?.days_of_data != null && (
              <div className="text-[#64748B] font-mono text-xs">
                {mtd.days_of_data} days of data this month
              </div>
            )}
          </div>

          {mtd ? (
            <div className="grid grid-cols-6 gap-4">
              {mtdStats.map((stat) => (
                <div key={stat.label}>
                  <div className="text-[#F1F5F9] text-2xl font-mono font-bold mb-1">
                    {stat.value}
                  </div>
                  <div className="text-[#64748B] text-xs font-mono uppercase tracking-wider">
                    {stat.label}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-[#64748B] font-mono text-xs">Loading MTD data...</div>
          )}
        </div>

        {/* Weekly Summaries */}
        <div className="bg-[#0A0A0A] border border-[#1F1F1F]">
          <div className="px-4 py-3 border-b border-[#1F1F1F]">
            <div className="text-[#64748B] font-mono text-xs uppercase tracking-widest">
              Weekly Summaries (Last 12 Weeks)
            </div>
          </div>
          <table className="w-full border-collapse text-xs">
            <thead>
              <tr className="border-b border-[#1F1F1F]">
                {['Week', 'Revenue', 'Profit', 'Ad Spend', 'ROAS', 'Margin%'].map((h) => (
                  <th key={h} className="py-2 px-4 text-[#64748B] font-mono text-xs uppercase tracking-wider font-normal text-right first:text-left">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {weekly.length === 0 ? (
                <tr>
                  <td colSpan={6} className="py-8 text-center text-[#64748B] font-mono text-xs">
                    No weekly data
                  </td>
                </tr>
              ) : (
                weekly.slice(0, 12).map((row, i) => (
                  <tr key={i} className="border-b border-[#0D0D0D] hover:bg-[#1A1A1A]">
                    <td className="py-2 px-4 font-mono text-[#64748B] text-xs">
                      {row.week_label || row.week || row.week_start || '—'}
                    </td>
                    <td className="py-2 px-4 font-mono text-[#F1F5F9] text-right text-xs">
                      {formatCurrency(row.revenue)}
                    </td>
                    <td className="py-2 px-4 font-mono text-right text-xs" style={{ color: (row.profit ?? 0) >= 0 ? '#00FF88' : '#EF4444' }}>
                      {formatCurrency(row.profit)}
                    </td>
                    <td className="py-2 px-4 font-mono text-[#F1F5F9] text-right text-xs">
                      {formatCurrency(row.ad_spend)}
                    </td>
                    <td className="py-2 px-4 font-mono text-right text-xs" style={{ color: (row.roas ?? 0) >= 2 ? '#00FF88' : (row.roas ?? 0) >= 1.5 ? '#F59E0B' : '#EF4444' }}>
                      {row.roas != null ? `${Number(row.roas).toFixed(2)}x` : '—'}
                    </td>
                    <td className="py-2 px-4 font-mono text-right text-xs" style={{ color: (row.margin_pct ?? 0) >= 20 ? '#00FF88' : (row.margin_pct ?? 0) >= 10 ? '#F59E0B' : '#EF4444' }}>
                      {formatPct(row.margin_pct)}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {/* Monthly Summaries */}
        <div className="bg-[#0A0A0A] border border-[#1F1F1F]">
          <div className="px-4 py-3 border-b border-[#1F1F1F]">
            <div className="text-[#64748B] font-mono text-xs uppercase tracking-widest">
              Monthly Summaries (Last 12 Months)
            </div>
          </div>
          <table className="w-full border-collapse text-xs">
            <thead>
              <tr className="border-b border-[#1F1F1F]">
                {['Month', 'Revenue', 'Profit', 'Ad Spend', 'ROAS', 'Margin%', 'Days'].map((h) => (
                  <th key={h} className="py-2 px-4 text-[#64748B] font-mono text-xs uppercase tracking-wider font-normal text-right first:text-left">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {monthly.length === 0 ? (
                <tr>
                  <td colSpan={7} className="py-8 text-center text-[#64748B] font-mono text-xs">
                    No monthly data
                  </td>
                </tr>
              ) : (
                monthly.slice(0, 12).map((row, i) => (
                  <tr key={i} className="border-b border-[#0D0D0D] hover:bg-[#1A1A1A]">
                    <td className="py-2 px-4 font-mono text-[#64748B] text-xs">
                      {row.month_label || row.month || '—'}
                    </td>
                    <td className="py-2 px-4 font-mono text-[#F1F5F9] text-right text-xs">
                      {formatCurrency(row.revenue)}
                    </td>
                    <td className="py-2 px-4 font-mono text-right text-xs" style={{ color: (row.profit ?? 0) >= 0 ? '#00FF88' : '#EF4444' }}>
                      {formatCurrency(row.profit)}
                    </td>
                    <td className="py-2 px-4 font-mono text-[#F1F5F9] text-right text-xs">
                      {formatCurrency(row.ad_spend)}
                    </td>
                    <td className="py-2 px-4 font-mono text-right text-xs" style={{ color: (row.roas ?? 0) >= 2 ? '#00FF88' : (row.roas ?? 0) >= 1.5 ? '#F59E0B' : '#EF4444' }}>
                      {row.roas != null ? `${Number(row.roas).toFixed(2)}x` : '—'}
                    </td>
                    <td className="py-2 px-4 font-mono text-right text-xs" style={{ color: (row.margin_pct ?? 0) >= 20 ? '#00FF88' : (row.margin_pct ?? 0) >= 10 ? '#F59E0B' : '#EF4444' }}>
                      {formatPct(row.margin_pct)}
                    </td>
                    <td className="py-2 px-4 font-mono text-[#64748B] text-right text-xs">
                      {row.days_of_data ?? row.days ?? '—'}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </main>
    </div>
  )
}
