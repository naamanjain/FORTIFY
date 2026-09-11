import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { TrendPoint } from '../types/dashboard'

export function RiskTrendChart({ points }: { points: TrendPoint[] }) {
  return (
    <div className="chart-card">
      <div className="card-heading">
        <div>
          <p className="card-kicker">30-day operating view</p>
          <h2>Average predicted welfare signal</h2>
        </div>
      </div>
      <div className="chart-wrap">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={points} margin={{ top: 8, right: 12, left: 4, bottom: 8 }}>
            <XAxis dataKey="date" tick={{ fontSize: 11 }} minTickGap={28} />
            <YAxis domain={[0, 1]} tick={{ fontSize: 11 }} />
            <Tooltip formatter={(value) => Number(value).toFixed(3)} />
            <Line type="monotone" dataKey="average_probability" strokeWidth={2.5} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
