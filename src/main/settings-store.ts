// Machine-local preferences the MAIN process needs: folders on this computer.
// These live in settings.json next to history.json, not in localStorage (the
// renderer can't hand main a path it should trust) and not in Firestore (a
// path on this Mac means nothing on the DJ's Windows laptop).
//
// Only main writes these, and only from a folder the DJ picked in a native
// dialog. That is what lets the music folder double as a file-access root:
// the renderer never gets to name a folder and then read everything under it.

import { app } from 'electron'
import { join } from 'path'
import { readFileSync, writeFileSync, existsSync } from 'fs'

export interface AppSettings {
  /** The DJ's library, browsed in-app instead of through the OS file dialog. */
  musicFolder: string | null
  /** Where batch exports land, remembered so the folder picker stops asking. */
  exportFolder: string | null
}

const DEFAULTS: AppSettings = { musicFolder: null, exportFolder: null }

function getSettingsFilePath(): string {
  return join(app.getPath('userData'), 'settings.json')
}

export function getSettings(): AppSettings {
  const filePath = getSettingsFilePath()
  if (!existsSync(filePath)) return { ...DEFAULTS }
  try {
    const parsed = JSON.parse(readFileSync(filePath, 'utf-8'))
    if (!parsed || typeof parsed !== 'object') return { ...DEFAULTS }
    return {
      musicFolder: typeof parsed.musicFolder === 'string' ? parsed.musicFolder : null,
      exportFolder: typeof parsed.exportFolder === 'string' ? parsed.exportFolder : null
    }
  } catch {
    return { ...DEFAULTS }
  }
}

export function updateSettings(patch: Partial<AppSettings>): AppSettings {
  const next = { ...getSettings(), ...patch }
  writeFileSync(getSettingsFilePath(), JSON.stringify(next, null, 2))
  return next
}
