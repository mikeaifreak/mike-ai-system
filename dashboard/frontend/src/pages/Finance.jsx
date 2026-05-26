import React, { useEffect, useState } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { getToken, getFinanceTable } from '../api'
import Sidebar from '../components/Sidebar'

function formatCurrency(val) {
  if (val == null) return '—'
  return '$' + Number(val).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function formatPct(val) {
  if (val == null) return '—'
  return Number(val).toFixed(1) + '%'
}

const RANGES = ['TODAY', '7D', '30D', 'MTD', 'ALL']
const RANGE_API_MAP = {
  TODAY: 'today',
  '7D': '7d',
  '30D': '30d',
  MTD: 'mtd',
  ALL: 'all'
}

function rowClass(row) {
  if (row.profit_pct < 0) return 'bg-[#EF444411]'
  if (row.refund_pct > 10) return 'bg-[#F59E0B11]'
  if (row.roas > 3) return 'bg-[#00FF8811]'
  return ''
}

function exportCSV(rows, columns) {
  const header = columns.map((c) => c.label).join(',')
  const body = rows.map((row) =>
    columns.map((c) => {
      const v = row[c.key]
      return v == null ? '' : String(v).includes(',') ? `"${v}"` : v
    }).join(',')
  ).join('\n')
  const csv = `${header}\n${body}`
  const blob = new Blob([csv], { type: 'text/csv' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `finance-export.csv`
  a.click()
  URL.revokeObjectURL(url)
}

const COLUMNS = [
  { key: 'report_date', label: 'Date' },
  { key: 'revenue', label: 'Revenue', format: formatCurrency },
  { key: 'cog', label: 'COG', format: formatCurrency },
  { key: 'ad_spend', label: 'Ad Spend', format: formatCurrency },
  { key: 'employee_cost', label: 'Employee', format: formatCurrency },
  { key: 'profit', label: 'Profit', format: formatCurrency },
  { key: 'roas', label: 'ROAS', format: (v) => v != null ? `${Number(v).toFixed(2)}x` : '—' },
  { key: 'refund_pct', label: 'Refund%', format: formatPct },
  { key: 'margin_pct', label: 'Margin%', format: formatPct }
]

export default function Finance() {
  const navigate = useNavigate()
  const location = useLocation()
  const [activeRange, setActiveRange] = useState('7D')
  const [tableData, setTableData] = useState({ rows: [], totals: null })
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!getToken()) navigate('/login')
  }, [navigate])

  async function fetchTable(range) {
    setLoading(true)
    try {
      const data = await getFinanceTable(RANGE_API_MAP[range] || range.toLowerCase())
      setTableData({
        rows: data?.data?.rows || [],
        totals: data?.data?.totals || null
      })
    } catch (_) {
      setTableData({ rows: [], totals: null })
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchTable(activeRange)
  }, [activeRange])

  const { rows, totals } = tableData

  const summaryStats = [
    { label: 'Total Revenue', value: formatCurrency(totals?.revenue) },
    { label: 'Total Profit', value: formatCurrency(totals?.profit) },
    { label: 'Avg ROAS', value: totals?.roas != null ? `${Number(totals.roas).toFixed(2)}x` : '—' },
    { label: 'Total Refunds', value: formatCurrency(totals?.refunds ?? totals?.total_refunds) }
  ]

  return (
    <div className="flex bg-black min-h-screen">
      <Sidebar currentPath={location.pathname} />

      <main className="flex-1 ml-64 overflow-y-auto p-6 space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-bold text-[#F1F5F9]">Finance Data</h1>
          <div className="flex items-center gap-1">
            {RANGES.map((r) => (
              <button
                key={r}
                onClick={() => setActiveRange(r)}
                className={`border font-mono text-xs px-3 py-1 transition-all ${
                  activeRange === r
                    ? 'border-[#00FF88] text-[#00FF88] bg-[#00FF8811]'
                    : 'border-[#1F1F1F] text-[#64748B] hover:border-[#00FF88] hover:text-[#00FF88]'
                }`}
              >
                {r}
              </button>
            ))}
          </div>
        </div>

        {/* Summary strip */}
        <div className="grid grid-cols-4 gap-4">
          {summaryStats.map((stat) => (
            <div key={stat.label} className="bg-[#0D0D0D] border border-[#1F1F1F] p-4">
              <div className="text-[#64748B] text-xs font-mono uppercase tracking-widest mb-2">
                {stat.label}
              </div>
              <div className="text-[#F1F5F9] text-xl font-mono font-bold">
                {stat.value}
              </div>
            </div>
          ))}
        </div>

        {/* Table */}
        <div className="bg-[#0A0A0A] border border-[#1F1F1F]">
          <div className="flex items-center justify-between px-4 py-3 border-b border-[#1F1F1F]">
            <div className="text-[#64748B] font-mono text-xs uppercase tracking-widest">
              {loading ? 'Loading...' : `${rows.length} rows`}
            </div>
            <button
              onClick={() => exportCSV(rows, COLUMNS)}
              className="border border-[#1F1F1F] text-[#64748B] font-mono text-xs px-3 py-1 hover:border-[#00FF88] hover:text-[#00FF88] transition-all"
            >
              EXPORT CSV ↓
            </button>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-xs">
              <thead>
                <tr className="border-b border-[#1F1F1F]">
                  {COLUMNS.map((col) => (
                    <th
                      key={col.key}
                      className="py-2 px-3 text-[#64748B] font-mono text-xs uppercase tracking-wider font-normal text-right first:text-left"
                    >
                      {col.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.length === 0 && !loading ? (
                  <tr>
                    <td colSpan={COLUMNS.length} className="py-8 text-center text-[#64748B] font-mono text-xs">
                      No data for selected range
                    </td>
                  </tr>
                ) : (
                  rows.map((row, i) => (
                    <tr key={i} className={`border-b border-[#0D0D0D] hover:bg-[#1A1A1A] ${rowClass(row)}`}>
                      {COLUMNS.map((col) => (
                        <td
                          key={col.key}
                          className="py-2 px-3 font-mono text-[#F1F5F9] text-right first:text-left first:text-[#64748B]"
                        >
                          {col.format ? col.format(row[col.key]) : (row[col.key] ?? '—')}
                        </td>
                      ))}
                    </tr>
                  ))
                )}

                {/* Totals row */}
                {totals && rows.length > 0 && (
                  <tr className="border-t-2 border-[#1F1F1F] bg-[#0D0D0D] font-bold">
                    <td className="py-3 px-3 font-mono text-[#64748B] text-xs">TOTAL</td>
                    <td className="py-3 px-3 font-mono text-[#F1F5F9] text-right text-xs">
                      {formatCurrency(totals.revenue)}
                    </td>
                    <td className="py-3 px-3 font-mono text-[#F1F5F9] text-right text-xs">
                      {formatCurrency(totals.cog)}
                    </td>
                    <td className="py-3 px-3 font-mono text-[#F1F5F9] text-right text-xs">
                      {formatCurrency(totals.ad_spend)}
                    </td>
                    <td className="py-3 px-3 font-mono text-[#F1F5F9] text-right text-xs">
                      {formatCurrency(totals.employee_cost)}
                    </td>
                    <td className="py-3 px-3 font-mono text-[#F1F5F9] text-right text-xs">
                      {formatCurrency(totals.profit)}
                    </td>
                    <td className="py-3 px-3 font-mono text-[#F1F5F9] text-right text-xs">
                      {totals.roas != null ? `${Number(totals.roas).toFixed(2)}x` : '—'}
                    </td>
                    <td className="py-3 px-3 font-mono text-[#F1F5F9] text-right text-xs">
                      {formatPct(totals.refund_pct)}
                    </td>
                    <td className="py-3 px-3 font-mono text-[#F1F5F9] text-right text-xs">
                      {formatPct(totals.margin_pct)}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </main>
    </div>
  )
}
