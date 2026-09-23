// Which files the renderer may read.
//
// The renderer names paths all day — "play this", "decode this for a waveform"
// — and until now main did whatever it was asked: media:// streamed any file on
// the machine and read-audio-file handed any file back as bytes. Adding a
// folder browser is the moment to draw the line, because the browser is the
// first feature that reads files the DJ never individually chose. The rule:
//
//   a path is allowed if the DJ CHOSE it (dropped, picked in a dialog, or an
//   edit this app saved for them), or it is INSIDE a folder this app trusts
//   (the music folder they picked, and the app's own preview/stem temp dirs).
//
// Dropped files are granted one at a time as they are dropped, so nothing the
// DJ does today stops working. No Electron imports, so it is unit-tested. It
// decides; src/main/index.ts enforces.

import { isAbsolute, sep, basename, dirname, join, resolve } from 'path'
import { realpath } from 'fs/promises'

export interface FileAccess {
  /** Files the DJ chose (or this app saved for them). Any spelling; resolved here. */
  grant: (paths: string[]) => Promise<void>
  /** The canonical path if the renderer may read it, otherwise null. */
  allow: (path: unknown) => Promise<string | null>
  /** `allow`, for the places where a refusal must stop the request. */
  require: (path: unknown, what: string) => Promise<string>
  /** Add a trusted folder (the music folder). Replaces any previous folder
   * under the same label, so changing the music folder revokes the old one. */
  setRoot: (label: string, dir: string | null) => void
  /** Make paths that are readable NOW (through a root) stay readable after
   * that root goes away: a song queued from the music folder must still play
   * after the DJ changes or forgets the folder. Cannot widen access — a path
   * that is not already allowed is ignored. */
  keep: (paths: unknown[]) => Promise<void>
  size: () => number
}

export class FileAccessError extends Error {
  constructor(what: string) {
    // Deliberately without the path: this message can reach the renderer and Sentry.
    super(`Cleanse was asked for ${what} it was never given. This is a bug — it has been reported.`)
    this.name = 'FileAccessError'
  }
}

/**
 * The identity of a file for "is this the same file?". Given a canonical path
 * (realpath), it folds the differences that don't make a different file:
 * Unicode form everywhere, separators and letter case on the platforms whose
 * filesystems ignore it — `C:\Music\a.mp3` and `c:\music\A.MP3` are one track
 * on Windows.
 */
export function pathKey(canonicalPath: string, platform: NodeJS.Platform = process.platform): string {
  let k = canonicalPath.normalize('NFC')
  if (platform === 'win32') k = k.replace(/\//g, '\\')
  return platform === 'win32' || platform === 'darwin' ? k.toLowerCase() : k
}

/** Canonical path (symlinks resolved, true casing on Windows). A file that isn't
 * there yet still has an identity: the deepest folder that DOES exist is resolved
 * and the rest is appended. Without that a not-yet-written preview and the
 * folder it will land in are spelled two ways wherever the temp folder is
 * reached through a link — always on macOS (/var -> /private/var) — and a '..'
 * after a missing folder is never collapsed. */
export async function canonical(p: string): Promise<string> {
  try {
    return await realpath(p)
  } catch {
    /* not there (or not readable): resolve as much of it as exists */
  }
  const rest = [basename(p)]
  let dir = dirname(p)
  while (dir !== dirname(dir)) {
    try {
      return join(await realpath(dir), ...rest) // join() collapses any '..' left in `rest`
    } catch {
      rest.unshift(basename(dir))
      dir = dirname(dir)
    }
  }
  return resolve(p)
}

/** Is `path` the folder `root` itself or something inside it? A boundary check,
 * not a prefix check: "…/Music-evil/x" starts with "…/Music" and is not in it.
 * Both arguments are pathKey()s, so case and separators are already folded. */
export function isInside(rootKey: string, pathKeyValue: string, separator: string = sep): boolean {
  if (!rootKey) return false
  const root = rootKey.endsWith(separator) ? rootKey.slice(0, -1) : rootKey
  return pathKeyValue === root || pathKeyValue.startsWith(root + separator)
}

/** media://<encoded absolute path> -> the path, or null if it isn't one.
 * Chromium rewrites "C:/x" as "C/x" in a non-standard URL; put the colon back
 * BEFORE any check is made on the result. Nothing after the prefix is treated
 * as a query: the renderer never adds one, and "Where Is The Love?.mp3" is a
 * legal file name. */
export function mediaUrlToPath(url: string): string | null {
  const prefix = 'media://'
  if (typeof url !== 'string' || !url.toLowerCase().startsWith(prefix)) return null
  let path: string
  try {
    path = decodeURIComponent(url.slice(prefix.length))
  } catch {
    return null
  }
  if (/^[a-zA-Z]\//.test(path)) path = path[0] + ':' + path.slice(1)
  return path || null
}

export function createFileAccess(
  roots: string[],
  platform: NodeJS.Platform = process.platform,
  max = 20_000
): FileAccess {
  const granted = new Set<string>()
  const namedRoots = new Map<string, string>()
  const separator = platform === 'win32' ? '\\' : '/'
  const key = (p: string): string => pathKey(p, platform)

  const resolvePath = async (path: unknown): Promise<string | null> => {
    if (typeof path !== 'string' || !path || path.length > 4096) return null
    if (path.includes('\0')) return null
    if (!isAbsolute(path)) return null // never relative to wherever main happens to run
    return canonical(path) // symlinks resolved: a link inside an allowed folder can point anywhere
  }

  const inRoots = async (real: string): Promise<boolean> => {
    const k = key(real)
    for (const root of [...roots, ...namedRoots.values()]) {
      // Resolved each time: the folder may not exist until the first preview is
      // written, and TEMP is often spelled two ways (8.3 short names on Windows).
      if (isInside(key(await canonical(root)), k, separator)) return true
    }
    return false
  }

  const allow = async (path: unknown): Promise<string | null> => {
    const real = await resolvePath(path)
    if (!real) return null
    return granted.has(key(real)) || (await inRoots(real)) ? real : null
  }

  return {
    grant: async (paths) => {
      for (const p of paths) {
        const real = await resolvePath(p)
        if (!real) continue
        if (granted.size >= max) granted.delete(granted.values().next().value as string) // oldest out
        granted.add(key(real))
      }
    },
    allow,
    require: async (path, what) => {
      const real = await allow(path)
      if (!real) throw new FileAccessError(what)
      return real
    },
    setRoot: (label, dir) => {
      if (dir) namedRoots.set(label, dir)
      else namedRoots.delete(label)
    },
    keep: async (paths) => {
      for (const p of paths) {
        const real = await allow(p)
        if (!real) continue
        if (granted.size >= max) granted.delete(granted.values().next().value as string)
        granted.add(key(real))
      }
    },
    size: () => granted.size
  }
}
