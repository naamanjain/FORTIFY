import type { ReactNode } from 'react'

type IconName = 'shield' | 'alert' | 'person' | 'units' | 'trend' | 'data' | 'review' | 'audit' | 'settings' | 'search' | 'bell' | 'help' | 'chevron' | 'arrowUp' | 'arrowDown' | 'arrowRight' | 'check' | 'lock' | 'refresh' | 'external'

const paths: Record<IconName, ReactNode> = {
  shield: <path d="M12 3 5 6v5c0 4.5 2.7 7.8 7 10 4.3-2.2 7-5.5 7-10V6l-7-3Zm0 5v10" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />,
  alert: <><circle cx="12" cy="12" r="8.5" fill="none" stroke="currentColor" strokeWidth="1.7"/><path d="m12 8.3.1 4.1M12 15.8h.01" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"/></>,
  person: <><circle cx="12" cy="8" r="3" fill="none" stroke="currentColor" strokeWidth="1.7"/><path d="M5.5 20c.7-3.1 2.8-4.7 6.5-4.7s5.8 1.6 6.5 4.7" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round"/></>,
  units: <><rect x="4" y="5" width="6" height="6" rx="1" fill="none" stroke="currentColor" strokeWidth="1.6"/><rect x="14" y="5" width="6" height="6" rx="1" fill="none" stroke="currentColor" strokeWidth="1.6"/><rect x="9" y="13" width="6" height="6" rx="1" fill="none" stroke="currentColor" strokeWidth="1.6"/><path d="M10 8h4M12 11v2" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/></>,
  trend: <path d="m4 16 5-5 3 3 6-7M14 7h4v4" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"/>,
  data: <><ellipse cx="12" cy="6.5" rx="6.5" ry="2.8" fill="none" stroke="currentColor" strokeWidth="1.6"/><path d="M5.5 6.5v5c0 1.6 2.9 2.8 6.5 2.8s6.5-1.2 6.5-2.8v-5M5.5 11.5v5c0 1.6 2.9 2.8 6.5 2.8s6.5-1.2 6.5-2.8v-5" fill="none" stroke="currentColor" strokeWidth="1.6"/></>,
  review: <><rect x="5" y="4" width="14" height="16" rx="2" fill="none" stroke="currentColor" strokeWidth="1.6"/><path d="M8.5 9h7M8.5 13h7M8.5 17h4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/></>,
  audit: <><path d="M7 4h10v4H7zM5 8h14v11H5z" fill="none" stroke="currentColor" strokeWidth="1.5"/><path d="M9 12h6M9 15h4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/></>,
  settings: <path d="M12 8.5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7Zm0-5v2M12 18.5v2M4.9 5l1.4 1.4M17.7 17.7l1.4 1.4M3 12h2M19 12h2M4.9 19l1.4-1.4M17.7 6.4 19.1 5" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>,
  search: <><circle cx="10.5" cy="10.5" r="5.5" fill="none" stroke="currentColor" strokeWidth="1.7"/><path d="m15 15 4 4" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round"/></>,
  bell: <><path d="M6.5 16.5h11l-1.1-1.9V10a4.4 4.4 0 0 0-8.8 0v4.6L6.5 16.5ZM10 19h4" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/></>,
  help: <><circle cx="12" cy="12" r="8.5" fill="none" stroke="currentColor" strokeWidth="1.6"/><path d="M9.5 9.7A2.6 2.6 0 0 1 12 8.2c1.6 0 2.8 1 2.8 2.4 0 1.8-2 2.1-2.5 3.2M12 16h.01" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/></>,
  chevron: <path d="m9 6 6 6-6 6" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"/>,
  arrowUp: <path d="m7 15 5-6 5 6" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"/>,
  arrowDown: <path d="m7 9 5 6 5-6" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"/>,
  arrowRight: <path d="m9 6 6 6-6 6" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"/>,
  check: <path d="m5.5 12 4.1 4.1L18.5 7" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"/>,
  lock: <><rect x="6" y="10" width="12" height="9" rx="1.5" fill="none" stroke="currentColor" strokeWidth="1.6"/><path d="M8.5 10V7.8a3.5 3.5 0 0 1 7 0V10" fill="none" stroke="currentColor" strokeWidth="1.6"/></>,
  refresh: <path d="M18 8a7 7 0 1 0 1.2 7M18 8V4.5M18 8h-3.5" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"/>,
  external: <><path d="M14 5h5v5M19 5l-7 7" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/><path d="M17 13.5V18H6V7h4.5" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/></>,
}

export function Icon({ name, size = 18 }: { name: IconName; size?: number }) {
  return <svg aria-hidden="true" width={size} height={size} viewBox="0 0 24 24" fill="none" focusable="false">{paths[name]}</svg>
}
