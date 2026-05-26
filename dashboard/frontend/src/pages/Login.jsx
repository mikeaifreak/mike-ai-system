import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { login, setToken } from '../api'

export default function Login() {
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      const data = await login(username, password)
      setToken(data?.data?.token || data.access_token || data.token)
      navigate('/dashboard')
    } catch (err) {
      setError(err.message || 'Authentication failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-black flex flex-col items-center justify-center px-4">
      <div className="w-full max-w-sm">
        {/* Logo / Title */}
        <div className="text-center mb-10">
          <div className="text-[#00FF88] font-mono text-5xl font-bold tracking-widest mb-3">
            MIKE AI
          </div>
          <div className="text-[#64748B] text-sm tracking-[0.3em] uppercase mb-2">
            Mission Control
          </div>
          <div className="text-[#64748B] text-xs tracking-[0.2em] uppercase">
            Restricted Access
          </div>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-[#64748B] text-xs font-mono uppercase tracking-widest mb-2">
              Username
            </label>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
              autoComplete="username"
              className="bg-[#0A0A0A] border border-[#1F1F1F] text-[#F1F5F9] px-4 py-3 w-full focus:border-[#00FF88] outline-none font-mono"
              placeholder="username"
            />
          </div>
          <div>
            <label className="block text-[#64748B] text-xs font-mono uppercase tracking-widest mb-2">
              Password
            </label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              autoComplete="current-password"
              className="bg-[#0A0A0A] border border-[#1F1F1F] text-[#F1F5F9] px-4 py-3 w-full focus:border-[#00FF88] outline-none font-mono"
              placeholder="••••••••"
            />
          </div>

          {error && (
            <div className="text-[#EF4444] font-mono text-sm text-center py-2 border border-[#EF444433] bg-[#EF444411]">
              ✕ ACCESS DENIED — {error}
            </div>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full border border-[#00FF88] text-[#00FF88] font-mono px-8 py-3 hover:bg-[#00FF88] hover:text-black transition-all disabled:opacity-40 disabled:cursor-not-allowed mt-2"
          >
            {loading ? 'AUTHENTICATING...' : 'AUTHENTICATE →'}
          </button>
        </form>

        {/* Footer */}
        <div className="text-center mt-10 text-[#64748B] text-xs font-mono">
          MIKE AI MISSION CONTROL v1.0
        </div>
      </div>
    </div>
  )
}
