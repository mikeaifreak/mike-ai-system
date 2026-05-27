import React, { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import {
  getToken,
  getTodayMetrics,
  getChartData,
  getAgentLogs,
  getRecentAlerts,
  getStores,
} from '../api'
import Sidebar from '../components/Sidebar'
import MetricCard from '../components/MetricCard'
import PLChart from '../components/PLChart'
import LiveLogFeed from '../components/LiveLogFeed'
import AlertRow from '../components/AlertRow'

// ---------------------------------------------------------------------------
// Currency helpers — never hardcoded, always read from store data
// ---------------------------------------------------------------------------
const CURRENCY_SYMBOLS = {
  USD: '$', EUR: '€', GBP: '£', CAD: 'CA$', AUD: 'A$',
  CHF: 'Fr', JPY: '¥', SEK: 'kr', NOK: 'kr', DKK: 'kr',
}

function currencySymbol(code) {
  return CURRENCY_SYMBOLS[String(code || 'USD').toUpperCase()] ?? (code + ' ')
}

function formatCurrency(val, currency = 'USD') {
  if (val == null) return '—'
  const sym = currencySymbol(currency)
  return sym + Number(val).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
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
const INTERVAL_CHART   = 300_000  // 30-day P&L chart

// ---------------------------------------------------------------------------
// Store Selector — compact dropdown in dashboard header
// ---------------------------------------------------------------------------
function StoreSelector({ stores, selectedId, onChange }) {
  const isAll = selectedId === null

  return (
    <div className="relative">
      <select
        value={selectedId ?? '__all__'}
        onChange={(e) => onChange(e.target.value === '__all__' ? null : e.target.value)}
        className="bg-[#0A0A0A] border border-[#1F1F1F] text-[#F1F5F9] font-mono text-xs
                   px-3 py-2 pr-8 focus:border-[#00FF88] focus:outline-none
                   appearance-none cursor-pointer hover:border-[#2A2A2A] transition-colors"
      >
        <option value="__all__" className="bg-[#0A0A0A]">All Stores (EUR)</option>
        {stores.map((s) => (
          <option key={s.store_id} value={s.store_id} className="bg-[#0A0A0A]">
            {s.display_name} ({s.currency})
          </option>
        ))}
      </select>
      <div className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2
                      text-[#64748B] text-[10px]">
        ▾
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Dashboard
// ---------------------------------------------------------------------------
export default function Dashboard() {
  const navigate = useNavigate()
  const location = useLocation()

  // Stores
  const [stores,          setStores]          = useState([])
  const [selectedStoreId, setSelectedStoreId] = useState(null)  // null = All Stores

  // Data state
  const [metrics,    setMetrics]    = useState(null)
  const [chartData,  setChartData]  = useState([])
  const [logs,       setLogs]       = useState([])
  const [alerts,     setAlerts]     = useState([])

  // Clock + LIVE indicator
  const [now,           setNow]           = useState(new Date())
  const [lastUpdatedAt, setLastUpdatedAt] = useState(null)
  const [secondsSince,  setSecondsSince]  = useState(0)

  // Auth guard
  useEffect(() => {
    if (!getToken()) navigate('/login')
  }, [navigate])

  // Fetch store list once on mount
  useEffect(() => {
    getStores()
      .then((res) => { if (res?.data) setStores(res.data) })
      .catch(() => {})
  }, [])

  // Wall clock
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1_000)
    return () => clearInterval(id)
  }, [])

  // "X seconds ago" counter — resets on each successful fetch
  useEffect(() => {
    setSecondsSince(0)
    const id = setInterval(() => setSecondsSince((s) => s + 1), 1_000)
    return () => clearInterval(id)
  }, [lastUpdatedAt])

  const touch = useCallback(() => setLastUpdatedAt(Date.now()), [])

  // ------------------------------------------------------------------
  // Fetch functions — keyed by selectedStoreId
  // ------------------------------------------------------------------
  const fetchMetrics = useCallback(async () => {
    try {
      const res = await getTodayMetrics(selectedStoreId)
      if (res?.data) { setMetrics((prev) => ({ ...(prev || {}), ...res.data })); touch() }
    } catch (_) {}
  }, [selectedStoreId, touch])

  const fetchAgentStatus = useCallback(async () => {
    try {
      const res = await getTodayMetrics(selectedStoreId)
      if (res?.data) {
        setMetrics((prev) => ({
          ...(prev || {}),
          active_agents: res.data.active_agents,
          last_sync:     res.data.last_sync,
        }))
        touch()
      }
    } catch (_) {}
  }, [selectedStoreId, touch])

  const fetchLogs = useCallback(async () => {
    try {
      const res = await getAgentLogs(20)
      if (res?.data) { setLogs(res.data); touch() }
    } catch (_) {}
  }, [touch])

  const fetchAlerts = useCallback(async () => {
    try {
      const res = await getRecentAlerts(8)
      if (res?.data) { setAlerts(res.data); touch() }
    } catch (_) {}
  }, [touch])

  const fetchChart = useCallback(async () => {
    try {
      const res = await getChartData(30, selectedStoreId)
      if (res?.data) { setChartData(res.data); touch() }
    } catch (_) {}
  }, [selectedStoreId, touch])

  // Re-fetch everything when store selection changes
  useEffect(() => {
    setMetrics(null)
    setChartData([])
    fetchMetrics()
    fetchChart()
  }, [selectedStoreId])  // eslint-disable-line react-hooks/exhaustive-deps

  // Mount: initial load + polling
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
  // Determine active currency
  // ------------------------------------------------------------------
  // When a specific store is selected → use that store's native currency.
  // When "All Stores" is selected → everything is in EUR (backend aggregates).
  const activeCurrency = (() => {
    if (selectedStoreId === null) return 'EUR'
    const store = stores.find((s) => s.store_id === selectedStoreId)
    return store?.currency ?? metrics?.currency ?? 'USD'
  })()

  // ------------------------------------------------------------------
  // Derived metric values
  // ------------------------------------------------------------------
  const today      = metrics?.today || {}
  const revenue    = today.revenue
  const profit     = today.profit
  const roas       = today.roas
  const marginPct  = today.margin_pct ?? (
    revenue && profit && Number(revenue) !== 0
      ? Number(profit) / Number(revenue) * 100
      : null
  )
  const revenueChg = metrics?.pct_change?.revenue ?? null

  const activeAgents  = metrics?.active_agents ?? null
  const lastSync      = metrics?.last_sync || null

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

  // LIVE label
  const liveLabel =
    lastUpdatedAt == null
      ? 'Connecting…'
      : secondsSince < 5
        ? 'Just updated'
        : `Last updated: ${secondsSince}s ago`

  // Store selector label for the greeting
  const storeLabel = selectedStoreId === null
    ? 'All Stores'
    : stores.find((s) => s.store_id === selectedStoreId)?.display_name ?? selectedStoreId

  // ------------------------------------------------------------------
  // Render
  // ------------------------------------------------------------------
  return (
    <div className="flex bg-black min-h-screen">
      <Sidebar currentPath={location.pathname} />

      <main className="flex-1 ml-64 overflow-y-auto p-6 space-y-6">

        {/* Header row */}
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <h1 className="text-3xl font-bold text-[#F1F5F9]">Good morning, Mike.</h1>
            <div className="text-[#00FF88] font-mono text-sm mt-1">
              ● AI systems operational — {dateStr} {timeStr}
            </div>
          </div>

          {/* Right: store selector + LIVE indicator */}
          <div className="flex items-center gap-3 flex-shrink-0 mt-1">
            {/* Store selector */}
            <StoreSelector
              stores={stores}
              selectedId={selectedStoreId}
              onChange={setSelectedStoreId}
            />

            {/* ● LIVE indicator */}
            <div className="flex items-center gap-2 bg-[#0A0A0A] border border-[#1F1F1F] px-3 py-2">
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
        </div>

        {/* Store context line */}
        {selectedStoreId !== null && (
          <div className="text-[#64748B] font-mono text-xs -mt-3">
            Viewing: <span className="text-[#F1F5F9]">{storeLabel}</span>
            {' '}· native currency: <span className="text-[#00FF88]">{activeCurrency}</span>
          </div>
        )}
        {selectedStoreId === null && stores.length > 1 && (
          <div className="text-[#64748B] font-mono text-xs -mt-3">
            Viewing: <span className="text-[#F1F5F9]">All {stores.length} stores</span>
            {' '}· converted to <span className="text-[#00FF88]">EUR</span>
          </div>
        )}

        {/* Row 1: Metric cards */}
        <div className="grid grid-cols-4 gap-4">
          <MetricCard
            title={`Today's Revenue${selectedStoreId === null && stores.length > 1 ? ' (EUR)' : ''}`}
            value={formatCurrency(revenue, activeCurrency)}
            subtext={revenueChg != null
              ? `${revenueChg >= 0 ? '+' : ''}${formatPct(revenueChg)} vs yesterday`
              : 'No prior day data'}
            accentColor="#3B82F6"
          />
          <MetricCard
            title={`Today's Profit${selectedStoreId === null && stores.length > 1 ? ' (EUR)' : ''}`}
            value={formatCurrency(profit, activeCurrency)}
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
              {selectedStoreId === null && stores.length > 1 &&
                <span className="ml-2 text-[#3A3A3A] normal-case">· EUR</span>}
            </div>
            <PLChart data={chartData} currency={activeCurrency} />
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
                {['Channel', 'Type', 'Message', 'Time'].map((h) => (
                  <th key={h} className="text-left py-2 px-3 text-[#64748B] font-mono
                                          text-xs uppercase tracking-widest font-normal">
                    {h}
                  </th>
                ))}
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

      {/* Pulse keyframe */}
      <style>{`
        @keyframes pulse-dot {
          0%, 100% { opacity: 1; transform: scale(1); }
          50%       { opacity: 0.4; transform: scale(0.85); }
        }
      `}</style>
    </div>
  )
}
