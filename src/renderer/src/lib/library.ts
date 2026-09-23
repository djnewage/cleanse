// Pure helpers for the music-folder browser: how a file name becomes a row
// (artist / title split), how rows sort, and how sizes and dates read.

import type { MusicFile } from '../types'

/** The drag payload a library row carries; FileUpload reads it back on drop. */
export const LIBRARY_DRAG_TYPE = 'application/x-cleanse-paths'

export interface LibraryRow extends MusicFile {
  title: string
  artist: string
  /** Lower-cased "artist title name" for the search box. */
  haystack: string
}

/** "Artist - Title.mp3" -> { artist: "Artist", title: "Title" }. DJ libraries
 * are overwhelmingly named this way; anything else is shown as-is under
 * SONG with an empty ARTIST. Only the FIRST " - " splits, so
 * "Artist - Title - Remix" keeps its remix in the title. */
export function splitArtistTitle(fileName: string): { artist: string; title: string } {
  const dot = fileName.lastIndexOf('.')
  const stem = dot > 0 ? fileName.slice(0, dot) : fileName
  const i = stem.indexOf(' - ')
  if (i <= 0) return { artist: '', title: stem }
  return { artist: stem.slice(0, i).trim(), title: stem.slice(i + 3).trim() }
}

export function toRow(file: MusicFile): LibraryRow {
  const { artist, title } = splitArtistTitle(file.name)
  return { ...file, artist, title, haystack: `${artist} ${title} ${file.name}`.toLowerCase() }
}

export type SortKey = 'title' | 'artist' | 'added' | 'size'
export interface SortSpec {
  key: SortKey
  dir: 'asc' | 'desc'
}

/** What a fresh click on each column header sorts by. Dates newest-first is
 * what "date added" means to a DJ; text and size ascend. */
export const DEFAULT_DIR: Record<SortKey, 'asc' | 'desc'> = {
  title: 'asc',
  artist: 'asc',
  added: 'desc',
  size: 'asc'
}

const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: 'base' })

export function sortRows(rows: LibraryRow[], sort: SortSpec): LibraryRow[] {
  const sign = sort.dir === 'asc' ? 1 : -1
  const sorted = [...rows]
  sorted.sort((a, b) => {
    let c = 0
    switch (sort.key) {
      case 'title':
        c = collator.compare(a.title, b.title)
        break
      case 'artist':
        // Blank artists sink to the bottom whichever way the column sorts.
        if (!a.artist !== !b.artist) return a.artist ? -1 : 1
        c = collator.compare(a.artist, b.artist) || collator.compare(a.title, b.title)
        break
      case 'added':
        c = a.mtime - b.mtime
        break
      case 'size':
        c = a.size - b.size
        break
    }
    return c * sign || collator.compare(a.name, b.name)
  })
  return sorted
}

export function filterRows(rows: LibraryRow[], query: string): LibraryRow[] {
  const terms = query.toLowerCase().split(/\s+/).filter(Boolean)
  if (terms.length === 0) return rows
  return rows.filter((r) => terms.every((t) => r.haystack.includes(t)))
}

export function formatSize(bytes: number): string {
  if (bytes >= 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  if (bytes >= 1024) return `${Math.round(bytes / 1024)} KB`
  return `${bytes} B`
}

/** Short enough for a narrow column: "Today", "Mon", "Sep 3", "Jun '25". */
export function formatAdded(mtime: number, now: number = Date.now()): string {
  const d = new Date(mtime)
  const ageDays = (now - mtime) / 86_400_000
  if (ageDays < 1 && new Date(now).toDateString() === d.toDateString()) return 'Today'
  if (ageDays < 7) return d.toLocaleDateString(undefined, { weekday: 'short' })
  if (d.getFullYear() === new Date(now).getFullYear()) {
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
  }
  return d.toLocaleDateString(undefined, { month: 'short', year: '2-digit' }).replace(' ', " '")
}

/** The last path segment, for either separator. */
export function folderName(path: string): string {
  return path.split(/[\\/]/).filter(Boolean).pop() || path
}
