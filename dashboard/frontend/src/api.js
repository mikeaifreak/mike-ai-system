const BASE = import.meta.env.VITE_API_URL || '/api'

let token = null

export function setToken(t) {
  token = t
}

export function getToken() {
  return token
}

export async function apiFetch(path, options = {}) {
  const headers = {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(options.headers || {})
  }
  const res = await fetch(`${BASE}${path}`, { ...options, headers })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || res.statusText)
  }
  return res.json()
}

export async function login(username, password) {
  const res = await fetch(`${BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password })
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Login failed' }))
    throw new Error(err.detail || 'Login failed')
  }
  return res.json()
}

export function getTodayMetrics() {
  return apiFetch('/metrics/today')
}

export function getChartData(days = 30) {
  return apiFetch(`/metrics/chart?days=${days}`)
}

export function getAgentStatus() {
  return apiFetch('/agents/status')
}

export function getAgentLogs(limit = 20) {
  return apiFetch(`/agents/logs?limit=${limit}`)
}

export function getRecentAlerts(limit = 8) {
  return apiFetch(`/alerts/recent?limit=${limit}`)
}

export function getFinanceTable(range = '7d') {
  return apiFetch(`/finance/table?range=${range}`)
}

export function getMTD() {
  return apiFetch('/reports/mtd')
}

export function getWeekly() {
  return apiFetch('/reports/weekly')
}

export function getMonthly() {
  return apiFetch('/reports/monthly')
}

export async function sendAgentChatStream(agentName, message, onChunk, onDone) {
  const res = await fetch(`${BASE}/chat/agent`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {})
    },
    body: JSON.stringify({ agent_name: agentName, message })
  })

  if (!res.ok) {
    throw new Error('Agent chat request failed')
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    const chunk = decoder.decode(value, { stream: true })
    const lines = chunk.split('\n')

    for (const line of lines) {
      if (line.startsWith('data: ')) {
        const data = line.slice(6) // no trim — preserve newlines in command output
        if (data.trim() === '[DONE]') {
          onDone()
          return
        }
        if (data) {
          onChunk(data)
        }
      }
    }
  }

  onDone()
}

export async function sendNovaChatStream(message, onChunk, onDone) {
  const res = await fetch(`${BASE}/chat`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {})
    },
    body: JSON.stringify({ message })
  })

  if (!res.ok) {
    throw new Error('Chat request failed')
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    const chunk = decoder.decode(value, { stream: true })
    const lines = chunk.split('\n')

    for (const line of lines) {
      if (line.startsWith('data: ')) {
        const data = line.slice(6).trim()
        if (data === '[DONE]') {
          onDone()
          return
        }
        if (data) {
          onChunk(data)
        }
      }
    }
  }

  onDone()
}
