import React from 'react'
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
  Filler
} from 'chart.js'
import { Line } from 'react-chartjs-2'

ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
  Filler
)

export default function PLChart({ data = [] }) {
  const labels = data.map((d) => {
    const date = new Date(d.report_date)
    return `${date.getMonth() + 1}/${date.getDate()}`
  })

  const chartData = {
    labels,
    datasets: [
      {
        label: 'Revenue',
        data: data.map((d) => d.revenue ?? 0),
        borderColor: '#3B82F6',
        backgroundColor: 'transparent',
        pointBackgroundColor: '#3B82F6',
        pointRadius: 3,
        pointStyle: 'circle',
        tension: 0.3,
        fill: false
      },
      {
        label: 'Profit',
        data: data.map((d) => d.profit ?? 0),
        borderColor: '#00FF88',
        backgroundColor: '#00FF8811',
        pointBackgroundColor: '#00FF88',
        pointRadius: 3,
        pointStyle: 'circle',
        tension: 0.3,
        fill: true
      }
    ]
  }

  const options = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: {
        display: true,
        labels: {
          color: '#64748B',
          font: { family: '"JetBrains Mono"', size: 11 },
          usePointStyle: true,
          pointStyle: 'circle',
          boxWidth: 8
        }
      },
      tooltip: {
        backgroundColor: '#0D0D0D',
        borderColor: '#1F1F1F',
        borderWidth: 1,
        titleColor: '#64748B',
        bodyColor: '#F1F5F9',
        titleFont: { family: '"JetBrains Mono"', size: 11 },
        bodyFont: { family: '"JetBrains Mono"', size: 11 },
        callbacks: {
          label: (ctx) => {
            const val = ctx.parsed.y
            return ` ${ctx.dataset.label}: $${val.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
          }
        }
      }
    },
    scales: {
      x: {
        grid: { color: '#1F1F1F' },
        ticks: {
          color: '#64748B',
          font: { family: '"JetBrains Mono"', size: 10 },
          maxTicksLimit: 10
        },
        border: { color: '#1F1F1F' }
      },
      y: {
        grid: { color: '#1F1F1F' },
        ticks: {
          color: '#64748B',
          font: { family: '"JetBrains Mono"', size: 10 },
          callback: (val) => `$${(val / 1000).toFixed(0)}k`
        },
        border: { color: '#1F1F1F' }
      }
    }
  }

  return (
    <div className="h-64 relative">
      {data.length === 0 ? (
        <div className="flex items-center justify-center h-full text-[#64748B] font-mono text-xs">
          No data available
        </div>
      ) : (
        <Line data={chartData} options={options} />
      )}
    </div>
  )
}
