// The library sidebar: the DJ's music folder as a dense, sortable table —
// the shape every DJ already reads all night in Serato / Rekordbox — instead
// of an OS file dialog per import. Click a row's + (or double-click, or
// Enter) to queue it; drag rows onto the drop zone; shift/cmd-click to pick
// several. The list is windowed by hand (fixed 28px rows) so a 20k-file
// folder scrolls without a virtualization dependency.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { MusicFile, MusicFolderListing } from '../types'
import {
  DEFAULT_DIR,
  filterRows,
  folderName,
  formatAdded,
  formatSize,
  sortRows,
  toRow,
  type LibraryRow,
  type SortKey,
  type SortSpec
} from '../lib/library'

/** The drag payload a row puts on the clipboard; FileUpload reads it back. */
export const LIBRARY_DRAG_TYPE = 'application/x-cleanse-paths'

const ROW_H = 28
const OVERSCAN = 8
const SORT_STORAGE_KEY = 'cleanse-library-sort'

interface MusicFolderProps {
  folder: string
  listing: MusicFolderListing | null
  loading: boolean
  /** filePaths already in the queue: shown as added, not addable again. */
  queuedPaths: Set<string>
  disabled: boolean
  notice: string | null
  onAdd: (files: Array<{ path: string; name: string }>) => void
  onChangeFolder: () => void
  onForgetFolder: () => void
  onRefresh: () => void
  onCollapse: () => void
}

function loadSort(): SortSpec {
  try {
    const raw = localStorage.getItem(SORT_STORAGE_KEY)
    if (raw) {
      const parsed = JSON.parse(raw)
      if (parsed && parsed.key in DEFAULT_DIR && (parsed.dir === 'asc' || parsed.dir === 'desc')) return parsed
    }
  } catch {
    /* private window, blocked storage: fall through */
  }
  return { key: 'added', dir: 'desc' }
}

export default function MusicFolder({
  folder,
  listing,
  loading,
  queuedPaths,
  disabled,
  notice,
  onAdd,
  onChangeFolder,
  onForgetFolder,
  onRefresh,
  onCollapse
}: MusicFolderProps): React.JSX.Element {
  const [query, setQuery] = useState('')
  const [debouncedQuery, setDebouncedQuery] = useState('')
  const [sort, setSort] = useState<SortSpec>(loadSort)
  const [selected, setSelected] = useState<Set<string>>(() => new Set())
  const anchorRef = useRef<number | null>(null)
  const viewportRef = useRef<HTMLDivElement>(null)
  const [scrollTop, setScrollTop] = useState(0)
  const [viewportH, setViewportH] = useState(400)

  useEffect(() => {
    const t = setTimeout(() => setDebouncedQuery(query), 150)
    return () => clearTimeout(t)
  }, [query])

  useEffect(() => {
    try {
      localStorage.setItem(SORT_STORAGE_KEY, JSON.stringify(sort))
    } catch {
      /* per-viewer convenience only */
    }
  }, [sort])

  useEffect(() => {
    const el = viewportRef.current
    if (!el) return
    const ro = new ResizeObserver(() => setViewportH(el.clientHeight))
    ro.observe(el)
    setViewportH(el.clientHeight)
    return () => ro.disconnect()
  }, [])

  const allRows = useMemo(() => (listing ? listing.files.map(toRow) : []), [listing])
  const rows = useMemo(() => sortRows(filterRows(allRows, debouncedQuery), sort), [allRows, debouncedQuery, sort])

  // A refresh or a new folder can drop rows that were selected.
  useEffect(() => {
    setSelected((prev) => {
      if (prev.size === 0) return prev
      const alive = new Set(allRows.map((r) => r.path))
      const next = new Set([...prev].filter((p) => alive.has(p)))
      return next.size === prev.size ? prev : next
    })
  }, [allRows])

  const toFile = (r: MusicFile): { path: string; name: string } => ({ path: r.path, name: r.name })

  const addRows = useCallback(
    (list: LibraryRow[]) => {
      if (disabled) return
      const fresh = list.filter((r) => !queuedPaths.has(r.path))
      onAdd((fresh.length > 0 ? fresh : list).map(toFile))
      setSelected(new Set())
    },
    [disabled, onAdd, queuedPaths]
  )

  const selectedRows = useMemo(() => rows.filter((r) => selected.has(r.path)), [rows, selected])

  const handleRowClick = (e: React.MouseEvent, index: number): void => {
    const row = rows[index]
    if (e.shiftKey && anchorRef.current !== null) {
      const [a, b] = [anchorRef.current, index].sort((x, y) => x - y)
      const range = rows.slice(a, b + 1).map((r) => r.path)
      setSelected((prev) => (e.metaKey || e.ctrlKey ? new Set([...prev, ...range]) : new Set(range)))
      return
    }
    anchorRef.current = index
    if (e.metaKey || e.ctrlKey) {
      setSelected((prev) => {
        const next = new Set(prev)
        if (next.has(row.path)) next.delete(row.path)
        else next.add(row.path)
        return next
      })
    } else {
      setSelected(new Set([row.path]))
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent): void => {
    if (e.target instanceof HTMLInputElement) return // the search box keeps its own keys
    if (e.key === 'Enter' && selectedRows.length > 0) {
      e.preventDefault()
      addRows(selectedRows)
    } else if (e.key === 'Escape') {
      setSelected(new Set())
    } else if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'a') {
      e.preventDefault()
      setSelected(new Set(rows.map((r) => r.path)))
    }
  }

  const handleDragStart = (e: React.DragEvent, row: LibraryRow): void => {
    // Dragging a selected row carries the whole selection; any other row, itself.
    const payload = (selected.has(row.path) ? selectedRows : [row]).map(toFile)
    e.dataTransfer.setData(LIBRARY_DRAG_TYPE, JSON.stringify(payload))
    e.dataTransfer.setData('text/plain', payload.map((f) => f.path).join('\n'))
    e.dataTransfer.effectAllowed = 'copy'
  }

  const clickSort = (key: SortKey): void => {
    setSort((prev) => (prev.key === key ? { key, dir: prev.dir === 'asc' ? 'desc' : 'asc' } : { key, dir: DEFAULT_DIR[key] }))
  }

  // Windowing
  const total = rows.length
  const first = Math.max(0, Math.floor(scrollTop / ROW_H) - OVERSCAN)
  const last = Math.min(total, Math.ceil((scrollTop + viewportH) / ROW_H) + OVERSCAN)
  const visible = rows.slice(first, last)

  // A plain render function, not a nested component: a nested component
  // remounts on every render and would drop focus right after a sort click.
  const renderHeader = (label: string, k: SortKey, className: string): React.JSX.Element => (
    <button
      key={k}
      onClick={() => clickSort(k)}
      className={`${className} text-left text-[10px] font-semibold uppercase tracking-wider transition-colors ${
        sort.key === k ? 'text-text-primary' : 'text-text-tertiary hover:text-text-secondary'
      }`}
      title={`Sort by ${label.toLowerCase()}`}
    >
      {label}
      {sort.key === k && <span className="ml-1 opacity-70">{sort.dir === 'asc' ? '▲' : '▼'}</span>}
    </button>
  )

  const addableSelected = selectedRows.filter((r) => !queuedPaths.has(r.path)).length

  return (
    <aside className="@container flex flex-col h-full bg-surface border-r border-border select-none" onKeyDown={handleKeyDown}>
      {/* Folder header */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-border">
        <span className="text-base leading-none">🗂</span>
        <div className="min-w-0 flex-1">
          <div className="text-sm font-semibold truncate" title={folder}>
            {folderName(folder)}
          </div>
          <div className="text-[10px] text-text-tertiary truncate">
            {loading ? 'Reading folder…' : `${allRows.length.toLocaleString()} songs`}
          </div>
        </div>
        <button
          onClick={onRefresh}
          disabled={loading}
          className="text-text-tertiary hover:text-text-primary text-sm px-1 disabled:opacity-40"
          title="Refresh (new files aren't picked up automatically)"
        >
          ↻
        </button>
        <button
          onClick={onChangeFolder}
          className="text-[11px] text-text-tertiary hover:text-text-primary px-1"
          title="Choose a different music folder"
        >
          Change
        </button>
        <button
          onClick={onForgetFolder}
          className="text-text-tertiary hover:text-text-primary text-sm px-1"
          title="Stop showing this folder"
        >
          ×
        </button>
        <button
          onClick={onCollapse}
          className="text-text-tertiary hover:text-text-primary text-sm px-1"
          title="Hide library"
        >
          ‹
        </button>
      </div>

      {/* Search */}
      <div className="px-2 py-1.5 border-b border-border">
        <div className="relative">
          <svg className="absolute left-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-text-tertiary" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="9" cy="9" r="6" />
            <path d="m14 14 4 4" strokeLinecap="round" />
          </svg>
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search"
            spellCheck={false}
            className="w-full bg-app border border-border rounded pl-7 pr-2 py-1 text-xs text-text-primary placeholder:text-text-disabled focus:outline-none focus:border-blue-500"
          />
        </div>
      </div>

      {/* Column headers */}
      <div className="flex items-center gap-2 px-2 h-6 border-b border-border-strong bg-app/60">
        <span className="w-5 shrink-0" />
        {renderHeader('Song', 'title', 'flex-1 min-w-0')}
        {renderHeader('Artist', 'artist', 'hidden @[18rem]:block flex-1 min-w-0')}
        {renderHeader('Added', 'added', 'w-12 shrink-0 text-right')}
        {renderHeader('Size', 'size', 'hidden @[23rem]:block w-14 shrink-0 text-right')}
      </div>

      {/* Rows */}
      <div
        ref={viewportRef}
        onScroll={(e) => setScrollTop(e.currentTarget.scrollTop)}
        className="flex-1 overflow-y-auto overflow-x-hidden focus:outline-none"
        tabIndex={0}
      >
        {!loading && total === 0 ? (
          <div className="px-3 py-8 text-center text-xs text-text-tertiary">
            {allRows.length === 0 ? 'No audio files found in this folder' : 'No songs match your search'}
          </div>
        ) : (
          <div style={{ height: total * ROW_H, position: 'relative' }}>
            {visible.map((row, i) => {
              const index = first + i
              const isSelected = selected.has(row.path)
              const queued = queuedPaths.has(row.path)
              return (
                <div
                  key={row.path}
                  draggable={!disabled}
                  onDragStart={(e) => handleDragStart(e, row)}
                  onClick={(e) => handleRowClick(e, index)}
                  onDoubleClick={() => !queued && addRows([row])}
                  style={{ position: 'absolute', top: index * ROW_H, height: ROW_H, left: 0, right: 0 }}
                  className={`group flex items-center gap-2 px-2 text-[13px] border-b border-border/60 cursor-default ${
                    isSelected
                      ? 'bg-blue-600 text-white'
                      : queued
                        ? 'text-text-disabled hover:bg-elevated/60'
                        : 'text-text-primary hover:bg-elevated'
                  }`}
                  title={`${row.name}\n${formatSize(row.size)}`}
                >
                  <span className="w-5 shrink-0 flex items-center justify-center">
                    {queued ? (
                      <span className={`text-[11px] ${isSelected ? 'text-white/80' : 'text-green-500'}`} title="Already in the queue">
                        ✓
                      </span>
                    ) : (
                      <button
                        onClick={(e) => {
                          e.stopPropagation()
                          addRows([row])
                        }}
                        disabled={disabled}
                        className={`w-4 h-4 rounded text-[13px] leading-none font-bold opacity-0 group-hover:opacity-100 focus:opacity-100 transition-opacity disabled:opacity-0 ${
                          isSelected ? 'bg-white/20 text-white hover:bg-white/30' : 'bg-blue-600 text-white hover:bg-blue-500'
                        }`}
                        title="Add to queue"
                      >
                        +
                      </button>
                    )}
                  </span>
                  <span className="flex-1 min-w-0 truncate">{row.title}</span>
                  <span className={`hidden @[18rem]:block flex-1 min-w-0 truncate ${isSelected ? 'text-white/80' : 'text-text-secondary'}`}>
                    {row.artist}
                  </span>
                  <span className={`w-12 shrink-0 text-right text-[11px] tabular-nums ${isSelected ? 'text-white/80' : 'text-text-tertiary'}`}>
                    {formatAdded(row.mtime)}
                  </span>
                  <span className={`hidden @[23rem]:block w-14 shrink-0 text-right text-[11px] tabular-nums ${isSelected ? 'text-white/80' : 'text-text-tertiary'}`}>
                    {formatSize(row.size)}
                  </span>
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* Footer: selection actions and caveats */}
      <div className="border-t border-border px-2 py-1.5 flex flex-col gap-1 text-[11px] text-text-tertiary">
        <div className="flex items-center gap-2 min-h-6">
          <span className="truncate">
            {selected.size > 0
              ? `${selected.size.toLocaleString()} selected`
              : total !== allRows.length
                ? `${total.toLocaleString()} of ${allRows.length.toLocaleString()}`
                : 'Click + or drag to the queue'}
          </span>
          {selected.size > 0 && (
            <button
              onClick={() => addRows(selectedRows)}
              disabled={disabled || addableSelected === 0}
              className="ml-auto px-2 py-0.5 rounded bg-blue-600 text-white font-medium hover:bg-blue-500 disabled:bg-elevated disabled:text-text-disabled"
            >
              Add {addableSelected > 0 ? addableSelected : selected.size}
            </button>
          )}
        </div>
        {notice && <div className="text-amber-400">{notice}</div>}
        {listing?.capped && (
          <div className="text-amber-400">
            Showing the first {listing.maxEntries.toLocaleString()} files — the folder holds more
          </div>
        )}
        {listing?.depthLimited && !listing.capped && (
          <div>Folders nested deeper than {listing.maxDepth} levels were skipped</div>
        )}
      </div>
    </aside>
  )
}
