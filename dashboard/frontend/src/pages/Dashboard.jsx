import React, { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { getToken, getTodayMetrics, getChartData, getAgentLogs, getRecentAlerts } from '../api'
import Sidebar from '../components/Sidebar'
import MetricCard from '../components/MetricCard'
import PLChart from '../components/PLChart'
import LiveLogFeed from '../components/LiveLogFeed'
import AlertRow from '../components/AlertRow'

// ---------------------------------------------------------------------------
// Formatters
// ---------------------------------------------------------------------------
function formatCurrency(val) {
  if (val == null) return '—'
  return '$' + Number(val).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function formatPct(val) {
  if (val == null) return '—'
  return Number(val).toFixed(1) + '%'
}

// ---------------------------------------------------------------------------
// Polling intervals (ms)
// ---------------------------------------------------------------------------
const INTERVAL_METRICS = 60_000   // Today's revenue / profit / ROAS
const INTERVAL_AGENTS  = 10_000   // Active agent count + last sync
const INTERVAL_LOGS    = 10_000   // Agent run log table
const INTERVAL_ALERTS  = 30_000   // Alerts table
const INTERVAL_CHART   = 300_000  // 30-day P&L chart (5 min — rarely changes)

// ---------------------------------------------------------------------------
// Dashboard
// ---------------------------------------------------------------------------
export default function Dashboard() {
  const navigate = useNavigate()
  const location = useLocation()

  // Data state
  const [metrics,    setMetrics]    = useState(null)
  const [chartData,  setChartData]  = useState([])
  const [logs,       setLogs]       = useState([])
  const [alerts,     setAlerts]     = useState([])

  // Clock + LIVE indicator
  const [now,              setNow]              = useState(new Date())
  const [lastUpdatedAt,    setLastUpdatedAt]    = useState(null)   // Date.now() of most recent successful fetch
  const [secondsSince,     setSecondsSince]     = useState(0)

  // Auth guard
  useEffect(() => {
    if (!getToken()) navigate('/login')
  }, [navigate])

  // Wall clock — ticks every second
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1_000)
    return () => clearInterval(id)
  }, [])

  // "Last updated X seconds ago" counter — resets when lastUpdatedAt changes
  useEffect(() => {
    setSecondsSince(0)
    const id = setInterval(() => setSecondsSince(s => s + 1), 1_000)
    return () => clearInterval(id)
  }, [lastUpdatedAt])

  // Helper: mark a successful update
  const touch = useCallback(() => setLastUpdatedAt(Date.now()), [])

  // ------------------------------------------------------------------
  // Fetch functions — each on its own interval
  // ------------------------------------------------------------------

  // Metrics (revenue, profit, roas) — 60 s
  const fetchMetrics = useCallback(async () => {
    try {
      const res = await getTodayMetrics()
      if (res?.data) {
        setMetrics(prev => ({ ...(prev || {}), ...res.data }))
        touch()
      }
    } catch (_) {}
  }, [touch])

  // Agent status (active_agents, last_sync) — 10 s
  // Comes from the same endpoint; we keep it separate so the agent count
  // stays up-to-date without re-fetching the slower parts.
  const fetchAgentStatus = useCallback(async () => {
    try {
      const res = await getTodayMetrics()
      if (res?.data) {
        setMetrics(prev => ({
          ...(prev || {}),
          active_agents: res.data.active_agents,
          last_sync:     res.data.last_sync,
        }))
        touch()
      }
    } catch (_) {}
  }, [touch])

  // Logs — 10 s
  const fetchLogs = useCallback(async () => {
    try {
      const res = await getAgentLogs(20)
      if (res?.data) { setLogs(res.data); touch() }
    } catch (_) {}
  }, [touch])

  // Alerts — 30 s
  const fetchAlerts = useCallback(async () => {
    try {
      const res = await getRecentAlerts(8)
      if (res?.data) { setAlerts(res.data); touch() }
    } catch (_) {}
  }, [touch])

  // Chart — 300 s
  const fetchChart = useCallback(async () => {
    try {
      const res = await getChartData(30)
      if (res?.data) { setChartData(res.data); touch() }
    } catch (_) {}
  }, [touch])

  // ------------------------------------------------------------------
  // Mount: initial load + polling setup
  // ------------------------------------------------------------------
  useEffect(() => {
    fetchMetrics()
    fetchAgentStatus()
    fetchLogs()
    fetchAlerts()
    fetchChart()

    const ids = [
      setInterval(fetchMetrics,     INTERVAL_METRICS),
      setInterval(fetchAgentStatus, INTERVAL_AGENTS),
      setInterval(fetchLogs,        INTERVAL_LOGS),
      setInterval(fetchAlerts,      INTERVAL_ALERTS),
      setInterval(fetchChart,       INTERVAL_CHART),
    ]
    return () => ids.forEach(clearInterval)
  }, [fetchMetrics, fetchAgentStatus, fetchLogs, fetchAlerts, fetchChart])

  // ------------------------------------------------------------------
  // Derived values
  // ------------------------------------------------------------------
  const today       = metrics?.today || {}
  const revenue     = today.revenue
  const profit      = today.profit
  const roas        = today.roas
  const marginPct   = today.margin_pct
  const revenueChg  = today.revenue_change_pct

  const activeAgents = metrics?.active_agents ?? null
  const lastSync     = metrics?.last_sync || null

  const roasColor =
    roas == null   ? '#64748B'
    : roas >= 2.0  ? '#00FF88'
    : roas >= 1.5  ? '#F59E0B'
    : '#EF4444'

  const marginColor =
    marginPct == null  ? '#64748B'
    : marginPct >= 20  ? '#00FF88'
    : marginPct >= 10  ? '#F59E0B'
    : '#EF4444'

  const dateStr      = now.toLocaleDateString('en-US', { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' })
  const timeStr      = now.toLocaleTimeString('en-US', { hour12: false })
  const agentsDisplay = activeAgents != null ? `${activeAgents} / 6` : '— / 6'
  const lastSyncDisplay = lastSync
    ? `Last sync ${Math.floor((Date.now() - new Date(lastSync).getTime()) / 60_000)}m ago`
    : 'Awaiting sync'

  // ------------------------------------------------------------------
  // LIVE indicator label
  // ------------------------------------------------------------------
  const liveLabel =
    lastUpdatedAt == null
      ? 'Connecting…'
      : secondsSince < 5
        ? 'Just updated'
        : `Last updated: ${secondsSince}s ago`

  // ------------------------------------------------------------------
  // Render
  // ------------------------------------------------------------------
  return (
    <div className="flex bg-black min-h-screen">
      <Sidebar currentPath={location.pathname} />

      <main className="flex-1 ml-64 overflow-y-auto p-6 space-y-6">

        {/* Header row: greeting + LIVE indicator */}
        <div className="flex items-start justify-between">
          <div>
            <h1 className="text-3xl font-bold text-[#F1F5F9]">Good morning, Mike.</h1>
            <div className="text-[#00FF88] font-mono text-sm mt-1">
              ● AI systems operational — {dateStr} {timeStr}
            </div>
          </div>

          {/* ● LIVE indicator */}
          <div className="flex items-center gap-2 bg-[#0A0A0A] border border-[#1F1F1F] px-3 py-2 mt-1 rounded-sm">
            <span
              className="w-2 h-2 rounded-full bg-[#00FF88]"
              style={{ animation: 'pulse-dot 1.5s ease-in-out infinite' }}
            />
            <span className="text-[#00FF88] font-mono text-xs font-semibold tracking-widest">
              LIVE
            </span>
            <span className="text-[#64748B] font-mono text-xs">
              · {liveLabel}
            </span>
          </div>
        </div>

        {/* Row 1: Metric cards */}
        <div className="grid grid-cols-4 gap-4">
          <MetricCard
            title="Today's Revenue"
            value={formatCurrency(revenue)}
            subtext={revenueChg != null
              ? `${revenueChg >= 0 ? '+' : ''}${formatPct(revenueChg)} vs yesterday`
              : 'No prior day data'}
            accentColor="#3B82F6"
          />
          <MetricCard
            title="Today's Profit"
            value={formatCurrency(profit)}
            badge={marginPct != null ? formatPct(marginPct) : null}
            badgeColor={marginColor}
            subtext="Net margin"
            accentColor="#00FF88"
          />
          <MetricCard
            title="ROAS"
            value={roas != null ? Number(roas).toFixed(2) + 'x' : '—'}
            subtext={roas != null
              ? (roas >= 2 ? 'Above target' : roas >= 1.5 ? 'Near target' : 'Below target')
              : ''}
            accentColor={roasColor}
          />
          <MetricCard
            title="Active Agents"
            value={agentsDisplay}
            subtext={lastSyncDisplay}
            accentColor="#00FF88"
          />
        </div>

        {/* Row 2: Chart + Log */}
        <div className="grid grid-cols-5 gap-4">
          <div className="col-span-3 bg-[#0A0A0A] border border-[#1F1F1F] p-4">
            <div className="text-[#64748B] font-mono text-xs uppercase tracking-widest mb-4">
              30-Day Performance
            </div>
            <PLChart data={chartData} />
          </div>
          <div className="col-span-2 bg-[#0A0A0A] border border-[#1F1F1F] p-4">
            <div className="text-[#64748B] font-mono text-xs uppercase tracking-widest mb-2">
              System Log
            </div>
            <LiveLogFeed logs={logs} />
          </div>
        </div>

        {/* Row 3: Alerts */}
        <div className="bg-[#0A0A0A] border border-[#1F1F1F] p-4">
          <div className="text-[#64748B] font-mono text-xs uppercase tracking-widest mb-3">
            Alerts
          </div>
          <table className="w-full border-collapse">
            <thead>
              <tr className="border-b border-[#1F1F1F]">
                <th className="text-left py-2 px-3 text-[#64748B] font-mono text-xs uppercase tracking-widest font-normal">Channel</th>
                <th className="text-left py-2 px-3 text-[#64748B] font-mono text-xs uppercase tracking-widest font-normal">Type</th>
                <th className="text-left py-2 px-3 text-[#64748B] font-mono text-xs uppercase tracking-widest font-normal">Message</th>
                <th className="text-left py-2 px-3 text-[#64748B] font-mono text-xs uppercase tracking-widest font-normal">Time</th>
              </tr>
            </thead>
            <tbody>
              {alerts.length === 0 ? (
                <tr>
                  <td colSpan={4} className="py-4 px-3 text-[#64748B] font-mono text-xs text-center">
                    No recent alerts
                  </td>
                </tr>
              ) : (
                alerts.map((alert, i) => <AlertRow key={i} alert={alert} />)
              )}
            </tbody>
          </table>
        </div>

      </main>

      {/* Pulse keyframe — injected inline so no Tailwind plugin needed */}
      <style>{`
        @keyframes pulse-dot {
          0%, 100% { opacity: 1; transform: scale(1); }
          50%       { opacity: 0.4; transform: scale(0.85); }
        }
      `}</style>
    </div>
  )
}
