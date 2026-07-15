/**
 * Elevation + speed dual-axis chart for the active route.
 * Elevation bars are color-coded by grade (gradeColor.ts).
 * Speed is a blue line on the right Y axis.
 * Scrubbing fires onScrubPosition(0-1 fraction).
 *
 * Uses Chart.js via react-chartjs-2. Mirrors the physics model
 * by receiving the speed_profile already computed (by backend or usePhysics).
 */
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  BarElement,
  LineElement,
  PointElement,
  Tooltip,
  Legend,
  type ChartData,
  type ChartOptions,
} from 'chart.js'
import { Chart } from 'react-chartjs-2'
import { useRef, useCallback } from 'react'
import { gradeToColor } from '../../utils/gradeColor'
import type { Route } from '../../types'

ChartJS.register(CategoryScale, LinearScale, BarElement, LineElement, PointElement, Tooltip, Legend)

interface ProfilePanelProps {
  route: Route
  /** Called with the 0–1 scrub fraction, or null when the cursor leaves the chart. */
  onScrubPosition?: (fraction: number | null) => void
}

export function ProfilePanel({ route, onScrubPosition }: ProfilePanelProps) {
  const chartRef = useRef<ChartJS | null>(null)
  const { elevations, segment_distances, speed_profile, metadata } = route

  if (elevations.length < 2) return null

  // Bar colors by grade between consecutive nodes
  const barColors = elevations.slice(0, -1).map((elev, i) => {
    const dz = elevations[i + 1] - elev
    const ds = segment_distances[i] || 1
    return gradeToColor(dz / ds)
  })
  // Last bar same as previous
  barColors.push(barColors[barColors.length - 1])

  const labels = elevations.map((_, i) => i === 0 ? 'Start' : i === elevations.length - 1 ? 'End' : '')

  const data: ChartData<'bar' | 'line'> = {
    labels,
    datasets: [
      {
        type: 'bar' as const,
        label: 'Elevation (m)',
        data: elevations,
        backgroundColor: barColors,
        yAxisID: 'y',
        order: 2,
      },
      ...(speed_profile && speed_profile.length === elevations.length
        ? [{
            type: 'line' as const,
            label: 'Speed (km/h)',
            data: speed_profile,
            borderColor: '#3b82f6',
            backgroundColor: 'rgba(59,130,246,0.1)',
            borderWidth: 2,
            pointRadius: 0,
            tension: 0.3,
            yAxisID: 'y2',
            order: 1,
          }]
        : []),
    ],
  }

  const elevMin = Math.min(...elevations)
  const elevMax = Math.max(...elevations)
  const elevPad = Math.max((elevMax - elevMin) * 0.15, 2)

  const options: ChartOptions<'bar' | 'line'> = {
    responsive: true,
    maintainAspectRatio: false,
    animation: false,
    plugins: {
      legend: { display: false },
      tooltip: {
        callbacks: {
          label: ctx => {
            if (ctx.datasetIndex === 0) return `${Math.round(ctx.parsed.y ?? 0)} m`
            return `${Math.round(ctx.parsed.y ?? 0)} km/h`
          },
        },
      },
    },
    scales: {
      x: { display: false },
      y: {
        type: 'linear',
        position: 'left',
        min: elevMin - elevPad,
        max: elevMax + elevPad,
        title: { display: true, text: 'Elevation (m)', font: { size: 10 } },
        ticks: { font: { size: 10 } },
      },
      y2: {
        type: 'linear',
        position: 'right',
        title: { display: true, text: 'Speed (km/h)', font: { size: 10 } },
        ticks: { font: { size: 10 } },
        grid: { drawOnChartArea: false },
      },
    },
    onHover: (_event, _elements, chart) => {
      if (!onScrubPosition || !chart.tooltip) return
      const active = chart.tooltip.dataPoints
      if (active && active.length > 0) {
        const idx = active[0].dataIndex
        onScrubPosition(idx / (elevations.length - 1))
      }
    },
  }

  // Clear the scrub (null) on leave so the map pin is removed, rather than
  // snapping it back to the route start (position 0).
  const handleMouseLeave = useCallback(() => {
    onScrubPosition?.(null)
  }, [onScrubPosition])

  return (
    <div style={{ padding: '12px 16px 8px' }}>
      <div style={{ fontSize: '12px', color: '#6b7280', marginBottom: '6px' }}>
        {metadata.name} &middot; {Math.round(metadata.total_descent_m)} m descent &middot; {Math.round(metadata.avg_grade_pct)}% avg grade
      </div>
      <div style={{ height: '140px' }} onMouseLeave={handleMouseLeave}>
        <Chart ref={chartRef as never} type="bar" data={data} options={options} />
      </div>
    </div>
  )
}
