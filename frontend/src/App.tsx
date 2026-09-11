import './styles/app.css'
import { useEffect, useState } from 'react'
import Attention from './pages/Attention'
import PersonProfile from './pages/PersonProfile'
import UnitCommand from './pages/UnitCommand'
import DataSignals from './pages/DataSignals'
import DataCollection from './pages/DataCollection'
import Governance from './pages/Governance'
import Reviews from './pages/Reviews'
import Personnel from './pages/Personnel'
import Trends from './pages/Trends'
import NotFound from './pages/NotFound'

function RouteView({ path }: { path: string }) {
  if (path === '/' || path === '/attention') return <Attention />
  if (path.startsWith('/person/')) return <PersonProfile personId={decodeURIComponent(path.slice('/person/'.length))} />
  if (path === '/personnel') return <Personnel />
  if (path === '/units') return <UnitCommand />
  if (path.startsWith('/units/')) return <UnitCommand unitId={decodeURIComponent(path.slice('/units/'.length))} />
  if (path === '/trends') return <Trends />
  if (path === '/data/signals') return <DataSignals />
  if (path === '/data/collection') return <DataCollection />
  if (path === '/reviews') return <Reviews />
  if (path === '/governance') return <Governance />
  return <NotFound />
}

export default function App() {
  const [path, setPath] = useState(window.location.pathname)
  useEffect(() => { const h=()=>setPath(window.location.pathname); window.addEventListener('popstate',h); return ()=>window.removeEventListener('popstate',h) }, [])
  return <RouteView path={path} />
}
