import React from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { getToken } from './api'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import MissionControl from './pages/MissionControl'
import Finance from './pages/Finance'
import Reports from './pages/Reports'
import NovaChat from './components/NovaChat'

function RequireAuth({ children }) {
  if (!getToken()) {
    return <Navigate to="/login" replace />
  }
  return children
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route
          path="/dashboard"
          element={
            <RequireAuth>
              <Dashboard />
            </RequireAuth>
          }
        />
        <Route
          path="/mission-control"
          element={
            <RequireAuth>
              <MissionControl />
            </RequireAuth>
          }
        />
        <Route
          path="/finance"
          element={
            <RequireAuth>
              <Finance />
            </RequireAuth>
          }
        />
        <Route
          path="/reports"
          element={
            <RequireAuth>
              <Reports />
            </RequireAuth>
          }
        />
        <Route path="/" element={<Navigate to="/dashboard" replace />} />
      </Routes>
      {getToken() && <NovaChat />}
    </BrowserRouter>
  )
}
