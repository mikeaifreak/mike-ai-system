import React, { useState, useEffect } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { setToken } from '../api'

const NAV_ITEMS = [
  { path: '/dashboard', label: 'OVERVIEW', icon: '⬡' },
  { path: '/mission-control', label: 'MISSION CONTROL', icon: '◈' },
  { path: '/finance', label: 'FINANCE', icon: '▦' },
  { path: '/reports', label: 'REPORTS', icon: '≡' }
]

export default function Sidebar({ currentPath }) {
  const navigate = useNavigate()
  const [clock, setClock] = useState('')

  useEffect(() => {
    function tick() {
      const now = new Date()
      const hh = String(now.getHours()).padStart(2, '0')
      const mm = String(now.getMinutes()).padStart(2, '0')
      const ss = String(now.getSeconds()).padStart(2, '0')
      setClock(`${hh}:${mm}:${ss}`)
    }
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [])

  function handleSignOut() {
    setToken(null)
    navigate('/login')
  }

  return (
    <div className="w-64 min-h-screen bg-[#0D0D0D] border-r border-[#1F1F1F] flex flex-col fixed top-0 left-0 h-screen z-40">
      {/* Top branding */}
      <div className="px-6 pt-6 pb-4">
        <div className="text-[#00FF88] font-mono font-bold text-xl tracking-widest">
          MIKE AI
        </div>
        <div className="text-[#64748B] text-[10px] tracking-[0.25em] uppercase mt-1">
          Mission Control
        </div>
        <div className="border-t border-[#1F1F1F] mt-4 mb-4" />
        {/* System status */}
        <div className="flex items-center gap-2">
          <span
            className="inline-block w-2 h-2 rounded-full bg-[#00FF88] pulse-dot"
          />
          <span className="text-[#00FF88] text-xs font-mono">SYSTEMS ONLINE</span>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 px-3 py-2">
        {NAV_ITEMS.map((item) => {
          const isActive = currentPath === item.path
          return (
            <Link
              key={item.path}
              to={item.path}
              className={`flex items-center gap-3 px-3 py-3 mb-1 text-xs font-mono transition-all ${
                isActive
                  ? 'border-l-2 border-[#00FF88] text-white bg-[#1A1A1A] pl-[10px]'
                  : 'text-[#64748B] hover:bg-[#1A1A1A] hover:text-[#F1F5F9] border-l-2 border-transparent'
              }`}
            >
              <span className="text-base leading-none">{item.icon}</span>
              <span className="tracking-widest">{item.label}</span>
            </Link>
          )
        })}
      </nav>

      {/* Separator + Sign out */}
      <div className="px-3 pb-2">
        <div className="border-t border-[#1F1F1F] mb-3" />
        <button
          onClick={handleSignOut}
          className="w-full text-left px-3 py-2 text-xs font-mono text-[#64748B] hover:text-[#EF4444] hover:bg-[#1A1A1A] transition-all"
        >
          ⟵ SIGN OUT
        </button>
      </div>

      {/* Bottom status */}
      <div className="px-6 pb-6 pt-2 border-t border-[#1F1F1F]">
        <div className="text-[#64748B] text-xs font-mono mb-2">{clock}</div>
        <div className="flex items-center gap-2">
          <span className="inline-block w-2 h-2 rounded-full bg-[#00FF88] pulse-dot" />
          <span className="text-[#00FF88] text-xs font-mono">NOVA ONLINE</span>
        </div>
      </div>
    </div>
  )
}
