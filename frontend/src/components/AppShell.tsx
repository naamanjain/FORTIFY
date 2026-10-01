import type { ReactNode } from 'react'
import { useEffect, useState } from 'react'
import { GlobalSearch } from './GlobalSearch'
import { Icon, type IconName } from './Icon'
import { currentAccess, FORTIFY_PURPOSE, FORTIFY_ROLE, PURPOSE, searchDashboard } from '../services/api'

type NavItem = { id: string; label: string; path: string; icon: IconName }
type SearchResult = { type: 'PERSONNEL' | 'UNIT'; key: string; title: string; detail: string }

const roleLabel: Record<string, string> = {
  WELFARE_OFFICER: 'Welfare Officer', COMMANDER: 'Command Leadership', AUDITOR: 'Security Auditor', SYSTEM_ADMINISTRATOR: 'System Administrator',
}
const purposeLabel: Record<string, string> = {
  WELFARE_SUPPORT: 'Welfare Support', AGGREGATE_OPERATIONS: 'Aggregate Operations', AUDIT: 'Audit', INFRASTRUCTURE_ADMIN: 'Infrastructure Admin',
}

export function AppShell({ navItems, activePath, query, searchResults, searchOpen, onQueryChange, onSearchSelect, onNavigate, children, searchEnabled = true }: {
  navItems: NavItem[]; activePath: string; query: string; searchResults: SearchResult[]; searchOpen: boolean;
  onQueryChange: (value: string) => void; onSearchSelect: (result: SearchResult) => void; onNavigate: (path: string) => void;
  notificationsOpen?: boolean; onToggleNotifications?: () => void; children?: ReactNode; searchEnabled?: boolean
}) {
  const role = roleLabel[FORTIFY_ROLE] ?? FORTIFY_ROLE
  const purpose = purposeLabel[FORTIFY_PURPOSE] ?? FORTIFY_PURPOSE
  const [globalQuery, setGlobalQuery] = useState(query)
  const [globalResults, setGlobalResults] = useState<SearchResult[]>(searchResults)
  const [globalOpen, setGlobalOpen] = useState(searchOpen)
  const [searchError, setSearchError] = useState<string | null>(null)

  useEffect(() => {
    if (!searchEnabled || !globalQuery.trim()) { setGlobalResults([]); setSearchError(null); return }
    const handle = window.setTimeout(() => {
      void searchDashboard(globalQuery.trim(), PURPOSE.WELFARE_SUPPORT)
        .then(r => { setGlobalResults(r.results as SearchResult[]); setSearchError(null) })
        .catch((e: Error) => {
          // A failed lookup must not present itself as "nothing found".
          setGlobalResults([]); setSearchError(e.message)
        })
    }, 140)
    return () => window.clearTimeout(handle)
  }, [globalQuery, searchEnabled])

  const effectiveQuery = searchEnabled ? globalQuery : query
  const effectiveResults = searchEnabled ? globalResults : searchResults
  const effectiveOpen = searchEnabled ? globalOpen : searchOpen
  const handleQuery = (value: string) => {
    if (searchEnabled) { setGlobalQuery(value); setGlobalOpen(Boolean(value.trim())) }
    onQueryChange(value)
  }
  const handleSelect = (result: SearchResult) => {
    if (searchEnabled) { setGlobalQuery(''); setGlobalOpen(false) }
    onSearchSelect(result)
    if (searchEnabled) onNavigate(result.type === 'PERSONNEL' ? `/person/${encodeURIComponent(result.key)}` : `/units/${encodeURIComponent(result.key)}`)
  }

  return <div className="app-shell">
    <aside className="sidebar" aria-label="Primary navigation">
      <button className="brand-block" type="button" onClick={() => onNavigate('/attention')} aria-label="Open Attention">
        <span className="brand-shield"><Icon name="shield" size={20} /></span>
        <span><strong>FORTIFY</strong><small>OPERATIONAL WELFARE</small></span>
      </button>
      <div className="demo-label">Demonstration environment · synthetic data</div>
      <nav className="sidebar-nav">
        {navItems.map(item => {
          const active = activePath === item.path || (item.path !== '/attention' && activePath.startsWith(item.path))
          return <button key={item.id} className={`sidebar-link ${active ? 'active' : ''}`} type="button" onClick={() => onNavigate(item.path)}>
            <Icon name={item.icon} size={18} /><span>{item.label}</span>
          </button>
        })}
      </nav>
      <div className="sidebar-spacer" />
      {/* This is build-time configuration, not a signed-in session. The
          prototype has no identity provider, and the label must say so - an
          avatar that looks like an authenticated user would misrepresent the
          security boundary. */}
      <div className="sidebar-footer">
        <div className="access-label">ACCESS CONTEXT</div>
        <strong>{role}</strong>
        <span>Purpose: {purpose}</span>
        <small className="access-auth-note">{currentAccess.label}</small>
      </div>
    </aside>
    <div className="workspace">
      <header className="topbar">
        <GlobalSearch value={effectiveQuery} results={effectiveResults} open={effectiveOpen} error={searchError} onChange={handleQuery} onSelect={handleSelect} />
        <div className="topbar-actions">
          <div className="purpose-compact"><span>{role}</span><strong>{purpose}</strong></div>
          <div className="user-menu"><span className="user-avatar" title={currentAccess.label}>{role.split(' ').map(x => x[0]).slice(0,2).join('')}</span><span className="user-menu-text"><strong>{role}</strong><small>Not authenticated</small></span></div>
        </div>
      </header>
      <main className="page-content">{children}</main>
    </div>
  </div>
}
