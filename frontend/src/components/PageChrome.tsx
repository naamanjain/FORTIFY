import type { ReactNode } from 'react'
export function PageChrome({ eyebrow, title, subtitle, right, children }: { eyebrow?: string; title: string; subtitle?: string; right?: ReactNode; children?: ReactNode }) {
  return <>
    <div className="page-header"><div><div className="eyebrow">{eyebrow}</div><h1>{title}</h1>{subtitle && <p>{subtitle}</p>}</div>{right}</div>
    {children}
  </>
}
