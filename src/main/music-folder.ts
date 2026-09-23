// Listing the DJ's music folder for the in-app browser. Plain Node, no
// Electron imports, so it is unit-tested against a real temp folder.
//
// A DJ library can be 50k files across a deep crate hierarchy. The walk is
// capped so a mis-picked folder (say, the whole home directory) returns
// something usable instead of hanging; the UI tells the DJ when the cap hit.

import { readdir, stat } from 'fs/promises'
import { join } from 'path'
import { isAudioFileName } from '../shared/audioExtensions.ts'

export const MAX_ENTRIES = 20_000
export const MAX_DEPTH = 6

export interface MusicFile {
  path: string
  name: string
  size: number
  /** Last-modified time in ms since epoch; the closest thing to "date added". */
  mtime: number
}

export interface MusicFolderListing {
  files: MusicFile[]
  /** True when MAX_ENTRIES was reached: the list is NOT the whole folder. */
  capped: boolean
  /** True when some folder sat deeper than MAX_DEPTH and was not entered. */
  depthLimited: boolean
}

/** Folders worth skipping outright: macOS resource forks in unzipped crates,
 * and anything hidden. A DJ's real tracks never live in either. */
function skipEntry(name: string): boolean {
  return name.startsWith('.') || name === '__MACOSX'
}

export interface ListLimits {
  maxEntries?: number
  maxDepth?: number
}

export async function listMusicFolder(dir: string, limits: ListLimits = {}): Promise<MusicFolderListing> {
  const maxEntries = limits.maxEntries ?? MAX_ENTRIES
  const maxDepth = limits.maxDepth ?? MAX_DEPTH
  const result: MusicFolderListing = { files: [], capped: false, depthLimited: false }
  const pending: Array<{ path: string; name: string }> = []

  /** Returns false once the cap is hit, to stop the walk. */
  const walk = async (folder: string, depth: number): Promise<boolean> => {
    let entries
    try {
      entries = await readdir(folder, { withFileTypes: true })
    } catch {
      return true // unreadable folder: skip it, keep going
    }
    for (const e of entries) {
      if (skipEntry(e.name)) continue
      // Symlinks are skipped, not followed: a link out of the library would
      // otherwise pull an unrelated tree into the listing (and into the
      // file-access root that "inside the music folder" grants).
      if (e.isSymbolicLink()) continue
      const full = join(folder, e.name)
      if (e.isDirectory()) {
        if (depth >= maxDepth) {
          result.depthLimited = true
          continue
        }
        if (!(await walk(full, depth + 1))) return false
      } else if (e.isFile() && isAudioFileName(e.name)) {
        if (pending.length >= maxEntries) {
          result.capped = true
          return false
        }
        pending.push({ path: full, name: e.name })
      }
    }
    return true
  }

  await walk(dir, 1)

  // stat in batches: 20k sequential stats on a slow external drive would take
  // noticeably longer than the walk itself.
  const BATCH = 64
  for (let i = 0; i < pending.length; i += BATCH) {
    const chunk = pending.slice(i, i + BATCH)
    const stats = await Promise.all(
      chunk.map(async ({ path, name }) => {
        try {
          const s = await stat(path)
          return { path, name, size: s.size, mtime: s.mtimeMs }
        } catch {
          return null // vanished between readdir and stat
        }
      })
    )
    for (const s of stats) if (s) result.files.push(s)
  }
  return result
}
