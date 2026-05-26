import React, { useState, useRef, useEffect } from 'react'
import { sendNovaChatStream } from '../api'

const QUICK_CHIPS = [
  "Yesterday's profit?",
  "This week's ROAS",
  "Any anomalies?"
]

function numberifyText(text) {
  // Wrap numbers in green spans for NOVA messages
  return text.replace(/(\$[\d,]+\.?\d*|\d+\.?\d*%|[\d,]+\.?\d+)/g, (match) => {
    return `<span style="color:#00FF88">${match}</span>`
  })
}

export default function NovaChat() {
  const [open, setOpen] = useState(false)
  const [messages, setMessages] = useState([
    { role: 'nova', content: 'Hello Mike. I\'m NOVA, your AI Finance Assistant. Ask me anything about today\'s performance, trends, or anomalies.' }
  ])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const messagesEndRef = useRef(null)
  const inputRef = useRef(null)

  useEffect(() => {
    if (messagesEndRef.current) {
      messagesEndRef.current.scrollIntoView({ behavior: 'smooth' })
    }
  }, [messages])

  useEffect(() => {
    if (open && inputRef.current) {
      inputRef.current.focus()
    }
  }, [open])

  async function handleSend(text) {
    const msg = (text || input).trim()
    if (!msg || streaming) return

    setInput('')
    setMessages((prev) => [...prev, { role: 'user', content: msg }])
    setStreaming(true)

    // Add empty nova message to stream into
    setMessages((prev) => [...prev, { role: 'nova', content: '', streaming: true }])

    try {
      await sendNovaChatStream(
        msg,
        (chunk) => {
          setMessages((prev) => {
            const updated = [...prev]
            const last = updated[updated.length - 1]
            if (last && last.role === 'nova') {
              updated[updated.length - 1] = { ...last, content: last.content + chunk }
            }
            return updated
          })
        },
        () => {
          setStreaming(false)
          setMessages((prev) => {
            const updated = [...prev]
            const last = updated[updated.length - 1]
            if (last && last.role === 'nova') {
              updated[updated.length - 1] = { ...last, streaming: false }
            }
            return updated
          })
        }
      )
    } catch (err) {
      setStreaming(false)
      setMessages((prev) => {
        const updated = [...prev]
        const last = updated[updated.length - 1]
        if (last && last.role === 'nova') {
          updated[updated.length - 1] = {
            ...last,
            content: `Error: ${err.message}`,
            streaming: false
          }
        }
        return updated
      })
    }
  }

  function handleKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="fixed bottom-6 right-6 z-50 w-14 h-14 bg-[#00FF88] nova-glow rounded-full flex items-center justify-center text-black text-2xl font-bold transition-transform hover:scale-110"
        title="Open NOVA Chat"
        aria-label="Open NOVA Chat"
      >
        ✦
      </button>
    )
  }

  return (
    <div className="fixed bottom-6 right-6 z-50 w-96 h-[520px] bg-[#0A0A0A] border border-[#1F1F1F] flex flex-col shadow-2xl">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-[#1F1F1F] flex-shrink-0">
        <div>
          <div className="text-[#00FF88] font-mono font-bold text-sm tracking-widest">NOVA</div>
          <div className="text-[#64748B] text-xs font-mono">AI Finance Assistant ● ONLINE</div>
        </div>
        <button
          onClick={() => setOpen(false)}
          className="text-[#64748B] hover:text-[#F1F5F9] text-lg leading-none font-mono"
          aria-label="Close"
        >
          ✕
        </button>
      </div>

      {/* Quick chips */}
      <div className="flex flex-wrap gap-2 px-3 py-2 border-b border-[#1F1F1F] flex-shrink-0">
        {QUICK_CHIPS.map((chip) => (
          <button
            key={chip}
            onClick={() => handleSend(chip)}
            disabled={streaming}
            className="border border-[#1F1F1F] text-[#64748B] text-xs px-3 py-1 hover:border-[#00FF88] hover:text-[#00FF88] font-mono cursor-pointer transition-all disabled:opacity-40"
          >
            {chip}
          </button>
        ))}
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-3 space-y-3">
        {messages.map((msg, i) => (
          <div
            key={i}
            className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
          >
            {msg.role === 'user' ? (
              <div className="bg-[#1A1A1A] text-[#F1F5F9] px-3 py-2 text-sm max-w-[80%] rounded-none">
                {msg.content}
              </div>
            ) : (
              <div className="bg-[#0D0D0D] text-[#F1F5F9] font-mono text-sm max-w-[85%] px-3 py-2 border border-[#1F1F1F]">
                <div
                  dangerouslySetInnerHTML={{ __html: numberifyText(msg.content || '') }}
                />
                {msg.streaming && (
                  <span
                    className="inline-block ml-0.5 text-[#00FF88]"
                    style={{ animation: 'pulse-dot 0.8s ease-in-out infinite' }}
                  >
                    ▋
                  </span>
                )}
              </div>
            )}
          </div>
        ))}
        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div className="border-t border-[#1F1F1F] p-3 flex gap-2 flex-shrink-0">
        <input
          ref={inputRef}
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={streaming}
          placeholder="Ask NOVA anything..."
          className="bg-black border border-[#1F1F1F] text-[#F1F5F9] px-3 py-2 flex-1 font-mono text-sm focus:border-[#00FF88] outline-none disabled:opacity-40"
        />
        <button
          onClick={() => handleSend()}
          disabled={streaming || !input.trim()}
          className="bg-[#00FF88] text-black px-4 py-2 font-mono font-bold text-sm disabled:opacity-40 disabled:cursor-not-allowed hover:bg-[#00DD77] transition-colors"
        >
          {streaming ? '...' : '→'}
        </button>
      </div>
    </div>
  )
}
