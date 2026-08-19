import { useEffect, useRef, useState } from 'react'
import { apiGet } from '../api/client'
import type { DirectoryPerson } from '../types'

interface Props {
  value: string
  onChange: (email: string) => void
  onSelect?: (person: DirectoryPerson) => void
  placeholder?: string
}

// Operations Team Directory typeahead (2026-08 collaborative-workspace
// spec, section 4) — search by name/email/title/department/office instead
// of typing an email cold. Falls back to free-text entry for anyone not
// in the directory yet (e.g. their first-ever invite).
export default function PersonSearchInput({ value, onChange, onSelect, placeholder }: Props) {
  const [results, setResults] = useState<DirectoryPerson[]>([])
  const [open, setOpen] = useState(false)
  const debounceRef = useRef<number | null>(null)
  const containerRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  function handleInput(text: string) {
    onChange(text)
    if (debounceRef.current) window.clearTimeout(debounceRef.current)
    if (text.trim().length < 2) {
      setResults([])
      setOpen(false)
      return
    }
    debounceRef.current = window.setTimeout(async () => {
      try {
        const people = await apiGet<DirectoryPerson[]>(`/api/directory/search?q=${encodeURIComponent(text.trim())}`)
        setResults(people)
        setOpen(people.length > 0)
      } catch {
        setResults([])
      }
    }, 250)
  }

  function pick(person: DirectoryPerson) {
    onChange(person.email)
    onSelect?.(person)
    setOpen(false)
  }

  return (
    <div className="person-search" ref={containerRef}>
      <input
        placeholder={placeholder || 'Search name or email…'}
        value={value}
        onChange={(e) => handleInput(e.target.value)}
        onFocus={() => results.length > 0 && setOpen(true)}
      />
      {open && (
        <div className="person-search-results">
          {results.map((p) => (
            <button key={p.id} className="person-search-result" onClick={() => pick(p)}>
              <div>{p.name}</div>
              <div className="muted">
                {[p.job_title, p.email].filter(Boolean).join(' · ')}
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
