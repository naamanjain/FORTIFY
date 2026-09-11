import { useEffect, useRef } from 'react'
import type { ChangeEvent, KeyboardEvent } from 'react'
import { Icon } from './Icon'

type SearchResult = { type: 'PERSONNEL' | 'UNIT'; key: string; title: string; detail: string }

export function GlobalSearch({ value, results, open, onChange, onSelect }: {
  value: string
  results: SearchResult[]
  open: boolean
  onChange: (value: string) => void
  onSelect: (result: SearchResult) => void
}) {
  const inputRef = useRef<HTMLInputElement>(null)
  useEffect(() => {
    const onKey = (event: globalThis.KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); inputRef.current?.focus() }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])
  const handleChange = (event: ChangeEvent<HTMLInputElement>) => onChange(event.target.value)
  const handleKey = (event: KeyboardEvent<HTMLInputElement>) => { if (event.key === 'Escape') onChange('') }
  return <div className="global-search">
    <Icon name="search" size={17} />
    <input ref={inputRef} value={value} onChange={handleChange} onKeyDown={handleKey} placeholder="Search people, units or cases" aria-label="Search people, units or cases" />
    <kbd>Ctrl K</kbd>
    {open && value.trim() && <div className="search-menu" role="listbox">
      {results.length ? results.map((result) => <button key={`${result.type}-${result.key}`} type="button" onClick={() => onSelect(result)}>
        <span className="search-result-kind">{result.type === 'PERSONNEL' ? 'PERSON' : 'UNIT'}</span>
        <strong>{result.title}</strong>
        <small>{result.detail}</small>
      </button>) : <div className="search-empty">No matching people or units.</div>}
    </div>}
  </div>
}
