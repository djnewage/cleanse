import { app } from 'electron'
import { join } from 'path'
import { readFileSync, writeFileSync, existsSync } from 'fs'

export interface HistoryEntry {
  id: string
  originalFileName: string
  originalFilePath: string
  censoredFilePath: string
  dateCreated: number
  wordCount: number
  profanityCount: number
  duration: number
  language: string
}

const MAX_ENTRIES = 100

function getHistoryFilePath(): string {
  return join(app.getPath('userData'), 'history.json')
}

export function getHistory(): HistoryEntry[] {
  const filePath = getHistoryFilePath()
  if (!existsSync(filePath)) return []
  try {
    const data = readFileSync(filePath, 'utf-8')
    const parsed = JSON.parse(data)
    if (Array.isArray(parsed)) return parsed
    return []
  } catch {
    return []
  }
}

export function addHistoryEntry(entry: Omit<HistoryEntry, 'id'>): HistoryEntry {
  const history = getHistory()
  const newEntry: HistoryEntry = {
    ...entry,
    id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
  }
  history.unshift(newEntry)
  if (history.length > MAX_ENTRIES) {
    history.length = MAX_ENTRIES
  }
  writeFileSync(getHistoryFilePath(), JSON.stringify(history, null, 2))
  return newEntry
}

export function deleteHistoryEntry(id: string): void {
  const history = getHistory().filter((entry) => entry.id !== id)
  writeFileSync(getHistoryFilePath(), JSON.stringify(history, null, 2))
}
