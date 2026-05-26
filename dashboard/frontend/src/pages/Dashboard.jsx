import React, { useEffect, useState } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { getToken, getTodayMetrics, getChartData, getAgentLogs, getRecentAlerts } from '../api'
import Sidebar from '../components/Sidebar'
import MetricCard from '../components/MetricCard'
import PLChart from '../components/PLChart'
import LiveLogFeed from '../components/LiveLogFeed'
import AlertRow from '../components/AlertRow'

function formatCurrency(val) {
  if (val == null) return '—'
  return '$' + Number(val).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function formatPct(val) {
  if (val == null) return '—'
  return Number(val).toFixed(1) + '%'
}

export default function Dashboard() {
  const navigate = useNavigate()
  const location = useLocation()
  const [metrics, setMetrics] = useState(null)
  const [chartData, setChartData] = useState([])
  const [logs, setLogs] = useState([])
  const [alerts, setAlerts] = useState([])
  const [now, setNow] = useState(new Date())

  useEffect(() => {
    if (!getToken()) navigate('/login')
  }, [navigate])

  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(id)
  }, [])

  async function fetchMain() {
    try {
      const [m, c, a] = await Promise.allSettled([
        getTodayMetrics(),
        getChartData(30),
        getRecentAlerts(8)
      ])
      if (m.status === 'fulfilled') setMetrics(m.value?.data || null)
      if (c.status === 'fulfilled') setChartData(c.value?.data || [])
      if (a.status === 'fulfilled') setAlerts(a.value?.data || [])
    } catch (_) {}
  }

  async function fetchLogs() {
    try {
      const data = await getAgentLogs(20)
      setLogs(data?.data || [])
    } catch (_) {}
  }

  useEffect(() => {
    fetchMain()
    const id = setInterval(fetchMain, 30000)
    return () => clearInterval(id)
  }, [])

  useEffect(() => {
    fetchLogs()
    const id = setInterval(fetchLogs, 10000)
    return () => clearInterval(id)
  }, [])

  const today = metrics?.today || {}
  const revenue = today.revenue
  const profit = today.profit
  const roas = today.roas
  const activeAgents = metrics?.active_agents ?? null
  const lastSync = metrics?.last_sync || null
  const revenueChange = today.revenue_change_pct
  const marginPct = today.margin_pct

  // ROAS color
  const roasColor =
    roas == null ? '#64748B'
    : roas >= 2.0 ? '#00FF88'
    : roas >= 1.5 ? '#F59E0B'
    : '#EF4444'

  // Margin badge color
  const marginColor =
    marginPct == null ? '#64748B'
    : marginPct >= 20 ? '#00FF88'
    : marginPct >= 10 ? '#F59E0B'
    : '#EF4444'

  const dateStr = now.toLocaleDateString('en-US', { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' })
  const timeStr = now.toLocaleTimeString('en-US', { hour12: false })

  const agentsDisplay = activeAgents != null ? `${activeAgents} / 6` : '— / 6'
  const lastSyncDisplay = lastSync
    ? `Last sync ${Math.floor((Date.now() - new Date(lastSync).getTime()) / 60000)}m ago`
    : 'Awaiting sync'

  return (
    <div className="flex bg-black min-h-screen">
      <Sidebar currentPath={location.pathname} />

      <main className="flex-1 ml-64 overflow-y-auto p-6 space-y-6">
        {/* Header */}
        <div>
          <h1 className="text-3xl font-bold text-[#F1F5F9]">Good morning, Mike.</h1>
          <div className="text-[#00FF88] font-mono text-sm mt-1">
            ● AI systems operational — {dateStr} {timeStr}
          </div>
        </div>

        {/* Row 1: Metric cards */}
        <div className="grid grid-cols-4 gap-4">
          <MetricCard
            title="Today's Revenue"
            value={formatCurrency(revenue)}
            subtext={revenueChange != null ? `${revenueChange >= 0 ? '+' : ''}${formatPct(revenueChange)} vs yesterday` : 'No prior day data'}
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
            subtext={roas != null ? (roas >= 2 ? 'Above target' : roas >= 1.5 ? 'Near target' : 'Below target') : ''}
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
    </div>
  )
}
