import * as Sentry from '@sentry/electron/main'
import { app, shell, BrowserWindow, ipcMain, dialog, protocol } from 'electron'

// Errors that originate from user-facing file-state checks (file moved, renamed,
// missing volume) are surfaced to the user as friendly toasts; reporting them
// to Sentry just creates noise. Drop them before they leave the process.
const USER_FACING_ERROR_PATTERNS = [
  /File no longer exists on disk/i,
  /File not found:/i
]

function isUserFacingError(message: string | undefined): boolean {
  if (!message) return false
  return USER_FACING_ERROR_PATTERNS.some((re) => re.test(message))
}

Sentry.init({
  dsn: 'https://c27473b596f92b07557b89836e8e0941@o4510700679593984.ingest.us.sentry.io/4510875528921088',
  release: `cleanse@${app.getVersion()}`,
  integrations: (defaults) => defaults.filter((i) => i.name !== 'PreloadInjection'),
  beforeSend(event) {
    const msg = event.exception?.values?.[0]?.value ?? event.message
    return isUserFacingError(msg) ? null : event
  }
})

import { join, extname, basename } from 'path'
import { createReadStream } from 'fs'
import { stat, readFile, writeFile, statfs } from 'fs/promises'
import { randomUUID } from 'crypto'
import { Readable } from 'stream'
import { existsSync, rmSync } from 'fs'
import { tmpdir } from 'os'
import { electronApp, optimizer, is } from '@electron-toolkit/utils'
import { autoUpdater } from 'electron-updater'
import log from 'electron-log'
import {
  startPythonBackend,
  stopPythonBackend,
  stopPythonBackendAndWait,
  isBackendReady,
  isBackendAlive,
  getBackendLogPath,
  fetchBackend,
  fetchBackendStreaming,
  setProgressCallback,
  setTranscriptionProgressCallback,
  setModelDownloadProgressCallback,
  getDeviceInfo
} from './python-bridge'
import { getHistory, addHistoryEntry, deleteHistoryEntry } from './history-store'
import { getSettings, updateSettings } from './settings-store'
import { listMusicFolder, MAX_ENTRIES, MAX_DEPTH } from './music-folder'
import { createFileAccess, FileAccessError, mediaUrlToPath } from './file-access'
import { AUDIO_EXTENSIONS } from '../shared/audioExtensions'

// Which files the renderer may read (see file-access.ts). The app's own temp
// folders are always in; the music folder joins when the DJ picks one; every
// dropped, picked or exported file is granted one at a time.
const PREVIEW_DIR = join(tmpdir(), 'cleanse-preview')
const STEMS_DIR = join(tmpdir(), 'cleanse-separated')
const fileAccess = createFileAccess([PREVIEW_DIR, STEMS_DIR])

function refused(what: string): FileAccessError {
  const err = new FileAccessError(what)
  log.warn(`[file-access] refused ${what}`) // no path: main.log is shared in bug reports
  Sentry.captureException(err)
  return err
}

async function describeBackendError(originalMsg: string): Promise<string> {
  // Yield to event loop so the child process 'exit' event can propagate
  await new Promise((resolve) => setTimeout(resolve, 500))
  const logPath = getBackendLogPath()
  const logHint = logPath ? ` Check logs: ${logPath}` : ''
  if (!isBackendAlive()) {
    return `Backend process crashed.${logHint}`
  }
  return `${originalMsg}${logHint}`
}

// Configure auto-updater logging
autoUpdater.logger = log
autoUpdater.autoDownload = false
// Install only from the explicit "Restart & Update" button. Installing on a
// normal quit would launch the NSIS installer while the backend is still being
// torn down, and a DJ closing the app before a gig does not expect a multi-GB
// install to start.
autoUpdater.autoInstallOnAppQuit = false

// Free disk needed for an in-app update to finish. The Windows installer is
// ~1.9 GB and the installed app ~2.7 GB; during the update NSIS parks the old
// install in %TEMP%, extracts the 1.8 GB archive there, extracts 2.7 GB again
// into the install dir, and electron-updater keeps two copies of the installer.
// Running out after the uninstall step leaves the user with no app at all,
// which is how a 1.20.0 -> 1.20.1 update "deleted" Cleanse. macOS only unzips.
const UPDATE_FREE_SPACE_BYTES = process.platform === 'win32' ? 12 * 1024 ** 3 : 3 * 1024 ** 3

async function freeSpaceOnAppVolume(): Promise<number | null> {
  try {
    const st = await statfs(app.getPath('exe'))
    return Number(st.bavail) * Number(st.bsize)
  } catch (err) {
    log.warn('[AutoUpdater] Could not read free space:', err)
    return null
  }
}

let mainWindow: BrowserWindow | null = null

function createWindow(): void {
  mainWindow = new BrowserWindow({
    width: 1100,
    height: 750,
    minWidth: 800,
    minHeight: 600,
    show: false,
    autoHideMenuBar: true,
    icon: join(__dirname, '../../build/icon.png'),
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      sandbox: false
    }
  })

  mainWindow.on('ready-to-show', () => {
    mainWindow!.show()
  })

  mainWindow.webContents.setWindowOpenHandler((details) => {
    shell.openExternal(details.url)
    return { action: 'deny' }
  })

  if (is.dev && process.env['ELECTRON_RENDERER_URL']) {
    mainWindow.loadURL(process.env['ELECTRON_RENDERER_URL'])
  } else {
    mainWindow.loadURL('app://./index.html')
  }
}

// --- IPC Handlers ---

// Avoids "Object has been destroyed" when the renderer quits while an async
// operation (e.g. backend startup, progress stream) is still in flight. The
// optional-chaining pattern `mainWindow?.webContents.send(...)` only guards
// null, not destroyed state.
function sendToMain(channel: string, ...args: unknown[]): void {
  if (!mainWindow || mainWindow.isDestroyed()) return
  const wc = mainWindow.webContents
  if (!wc || wc.isDestroyed()) return
  wc.send(channel, ...args)
}

// Fast-fail when the source audio has been moved/renamed/deleted between import and
// processing. Without this, the backend call runs for up to 30s before returning
// "File not found", and the user just sees a noisy stack trace in Sentry.
async function ensureFileExists(filePath: string): Promise<void> {
  try {
    await stat(filePath)
  } catch {
    throw new Error(
      `File no longer exists on disk: ${basename(filePath)}. It may have been moved, renamed, or deleted — please re-add it from its current location.`
    )
  }
}

ipcMain.handle('read-audio-file', async (_event, filePath: string) => {
  const real = await fileAccess.allow(filePath)
  if (!real) throw refused('an audio file')
  const buffer = await readFile(real)
  return buffer.buffer
})

// Dropped files never pass through a dialog in main; the preload grants them
// the moment it turns the File into a path (see preload getPathForFile).
ipcMain.on('grant-file-access', (_event, filePath: string) => {
  void fileAccess.grant([filePath])
})

// Songs queued from the music folder are readable through the folder root;
// this pins them so they keep playing after the DJ changes or forgets the
// folder. It only ever pins what is already readable, so the renderer
// cannot use it to reach anything new.
ipcMain.handle('keep-file-access', async (_event, paths: string[]) => {
  if (Array.isArray(paths)) await fileAccess.keep(paths)
})

ipcMain.handle('select-audio-file', async () => {
  if (!mainWindow) return null
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ['openFile'],
    filters: [{ name: 'Audio Files', extensions: [...AUDIO_EXTENSIONS] }]
  })
  if (result.canceled || result.filePaths.length === 0) return null
  await fileAccess.grant(result.filePaths)
  return result.filePaths[0]
})

ipcMain.handle('select-audio-files', async () => {
  if (!mainWindow) return []
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ['openFile', 'multiSelections'],
    filters: [{ name: 'Audio Files', extensions: [...AUDIO_EXTENSIONS] }]
  })
  if (result.canceled || result.filePaths.length === 0) return []
  await fileAccess.grant(result.filePaths)
  return result.filePaths
})

ipcMain.handle('select-output-directory', async () => {
  if (!mainWindow) return null
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ['openDirectory', 'createDirectory'],
    defaultPath: getSettings().exportFolder ?? undefined
  })
  if (result.canceled || result.filePaths.length === 0) return null
  // Remembered so the next batch export doesn't have to ask again.
  updateSettings({ exportFolder: result.filePaths[0] })
  return result.filePaths[0]
})

// --- Settings + music folder ---
//
// The folders in settings are only ever set from a native dialog handled
// here, never from a renderer-supplied string: the music folder is also a
// file-access root, so letting the renderer name it would let it name "/".

ipcMain.handle('get-settings', () => {
  const settings = getSettings()
  // An export folder on an unplugged drive would make every batch export
  // fail silently; report it as unset so the picker asks again. The music
  // folder is kept: its listing just comes back empty until the drive is back.
  if (settings.exportFolder && !existsSync(settings.exportFolder)) settings.exportFolder = null
  return settings
})

ipcMain.handle('select-music-folder', async () => {
  if (!mainWindow) return null
  const result = await dialog.showOpenDialog(mainWindow, {
    title: 'Choose your music folder',
    properties: ['openDirectory'],
    defaultPath: getSettings().musicFolder ?? undefined
  })
  if (result.canceled || result.filePaths.length === 0) return null
  const dir = result.filePaths[0]
  updateSettings({ musicFolder: dir })
  fileAccess.setRoot('music', dir)
  return dir
})

ipcMain.handle('clear-music-folder', () => {
  updateSettings({ musicFolder: null })
  fileAccess.setRoot('music', null)
})

ipcMain.handle('clear-export-folder', () => {
  updateSettings({ exportFolder: null })
})

ipcMain.handle('list-music-folder', async () => {
  // Always the folder in settings, never a path from the renderer.
  const dir = getSettings().musicFolder
  if (!dir) return { files: [], capped: false, depthLimited: false, maxEntries: MAX_ENTRIES, maxDepth: MAX_DEPTH }
  const listing = await listMusicFolder(dir)
  return { ...listing, maxEntries: MAX_ENTRIES, maxDepth: MAX_DEPTH }
})

ipcMain.handle('select-output-path', async (_event, defaultName: string) => {
  if (!mainWindow) return null
  const exportFolder = getSettings().exportFolder
  const result = await dialog.showSaveDialog(mainWindow, {
    // Open in the remembered export folder; the DJ can still pick another.
    defaultPath: exportFolder ? join(exportFolder, defaultName) : defaultName,
    filters: [
      { name: 'Audio Files', extensions: ['mp3', 'wav', 'ogg', 'm4a', 'flac', 'aiff'] }
    ]
  })
  if (result.canceled || !result.filePath) return null
  await fileAccess.grant([result.filePath]) // history plays the edit from here
  return result.filePath
})

ipcMain.handle('get-backend-status', () => {
  return { ready: isBackendReady() }
})

ipcMain.handle('warmup-model', async () => {
  try {
    console.log('[IPC] warmup-model called')
    setModelDownloadProgressCallback((data) => {
      sendToMain('model-download-progress', data)
    })

    const result = await fetchBackendStreaming<{ status: string }>('/warmup', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({})
    })

    return result
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err)
    console.error('[IPC] warmup-model error:', msg)
    throw new Error(`Model warmup failed: ${msg}`)
  } finally {
    setModelDownloadProgressCallback(null)
  }
})

ipcMain.handle('get-audio-metadata', async (_event, filePath: string) => {
  try {
    const resp = await fetchBackend('/metadata', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: filePath })
    })
    if (!resp.ok) return { artist: null, title: null, album: null, duration: null }
    return await resp.json()
  } catch {
    return { artist: null, title: null, album: null, duration: null }
  }
})

ipcMain.handle(
  'fetch-lyrics',
  async (_event, artist: string | null, title: string | null, duration?: number, fileName?: string) => {
  try {
    console.log(`[Lyrics] Fetching for: "${artist}" - "${title}" (file: ${fileName ?? 'n/a'})`)
    const resp = await fetchBackend('/fetch-lyrics', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ artist, title, duration, file_name: fileName })
    })
    if (!resp.ok) {
      console.log(`[Lyrics] Fetch failed: HTTP ${resp.status}`)
      return { plain_lyrics: null, synced_lyrics: null }
    }
    const result = await resp.json()
    console.log(`[Lyrics] Success: plain=${!!result.plain_lyrics}, synced=${!!result.synced_lyrics}`)
    return result
  } catch (err) {
    console.error('[Lyrics] Fetch error:', err)
    return { plain_lyrics: null, synced_lyrics: null }
  }
})

ipcMain.handle('transcribe-file', async (_event, filePath: string, turbo: boolean = false, vocalsPath?: string, lyrics?: string, syncedLyrics?: string, dualPass: boolean = true, lyricsFromTags: boolean = true) => {
  await ensureFileExists(filePath)
  try {
    console.log('[IPC] transcribe-file called with:', filePath, 'turbo:', turbo, 'vocalsPath:', vocalsPath, 'hasLyrics:', !!lyrics, 'dualPass:', dualPass, 'lyricsFromTags:', lyricsFromTags)
    setTranscriptionProgressCallback((data) => {
      sendToMain('transcription-progress', data)
    })

    const body: Record<string, unknown> = { path: filePath, turbo, dual_pass: dualPass }
    if (vocalsPath) {
      body.vocals_path = vocalsPath
    }
    if (lyrics) {
      body.lyrics = lyrics
      body.lyrics_from_tags = lyricsFromTags
    }
    if (syncedLyrics) {
      body.synced_lyrics = syncedLyrics
    }

    const result = await fetchBackendStreaming<{
      words: Array<Record<string, unknown>>
      duration: number
      language: string
      language_probability?: number
      language_source?: string
      language_low_confidence?: boolean
    }>('/transcribe', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    })

    return result
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err)
    const cause = err instanceof Error && err.cause ? ` [cause: ${err.cause}]` : ''
    throw new Error(`Transcription error: ${await describeBackendError(msg + cause)}`)
  } finally {
    setTranscriptionProgressCallback(null)
  }
})

ipcMain.handle('separate-audio', async (_event, filePath: string, turbo: boolean = false) => {
  await ensureFileExists(filePath)
  try {
    console.log('[IPC] separate-audio called with:', filePath, 'turbo:', turbo)
    setProgressCallback((data) => {
      sendToMain('separation-progress', data)
    })

    const result = await fetchBackendStreaming<{
      vocals_path: string
      accompaniment_path: string
    }>('/separate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: filePath, turbo })
    })

    return result
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err)
    const cause = err instanceof Error && err.cause ? ` [cause: ${err.cause}]` : ''
    throw new Error(`Separation error: ${await describeBackendError(msg + cause)}`)
  } finally {
    setProgressCallback(null)
  }
})

ipcMain.handle(
  'preview-audio',
  async (
    _event,
    args: {
      filePath: string
      censorWords: Array<{ word: string; start: number; end: number; censor_type: string }>
      vocalsPath?: string
      accompanimentPath?: string
      crossfadeMs: number
      paddingBeforeMs?: number
      paddingAfterMs?: number
      outputFormat?: string
    }
  ) => {
    await ensureFileExists(args.filePath)
    try {
      const body: Record<string, unknown> = {
        path: args.filePath,
        words: args.censorWords,
        crossfade_ms: args.crossfadeMs
      }
      if (args.paddingBeforeMs !== undefined) {
        body.padding_before_ms = args.paddingBeforeMs
      }
      if (args.paddingAfterMs !== undefined) {
        body.padding_after_ms = args.paddingAfterMs
      }
      if (args.vocalsPath && args.accompanimentPath) {
        body.vocals_path = args.vocalsPath
        body.accompaniment_path = args.accompanimentPath
      }
      if (args.outputFormat) {
        body.output_format = args.outputFormat
      }

      const resp = await fetchBackend('/preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      })

      if (!resp.ok) {
        const err = await resp.json()
        const detail = err.detail
        const message =
          typeof detail === 'string'
            ? detail
            : Array.isArray(detail)
              ? detail.map((d: { msg?: string }) => d.msg || JSON.stringify(d)).join('; ')
              : JSON.stringify(detail)
        throw new Error(message || 'Preview generation failed')
      }

      const result = await resp.json()
      return result.output_path
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      throw new Error(`Preview error: ${await describeBackendError(msg)}`)
    }
  }
)

ipcMain.handle(
  'censor-audio',
  async (
    _event,
    filePath: string,
    words: Array<{ word: string; start: number; end: number; censor_type: string }>,
    outputPath?: string,
    vocalsPath?: string,
    accompanimentPath?: string,
    crossfadeMs?: number,
    paddingBeforeMs?: number,
    paddingAfterMs?: number,
    outputFormat?: string
  ) => {
    await ensureFileExists(filePath)
    try {
      const body: Record<string, unknown> = { path: filePath, words, output_path: outputPath }
      if (vocalsPath && accompanimentPath) {
        body.vocals_path = vocalsPath
        body.accompaniment_path = accompanimentPath
      }
      if (crossfadeMs !== undefined) {
        body.crossfade_ms = crossfadeMs
      }
      if (paddingBeforeMs !== undefined) {
        body.padding_before_ms = paddingBeforeMs
      }
      if (paddingAfterMs !== undefined) {
        body.padding_after_ms = paddingAfterMs
      }
      if (outputFormat) {
        body.output_format = outputFormat
      }

      const resp = await fetchBackend('/censor', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      })

      if (!resp.ok) {
        const err = await resp.json()
        const detail = err.detail
        const message =
          typeof detail === 'string'
            ? detail
            : Array.isArray(detail)
              ? detail.map((d: { msg?: string }) => d.msg || JSON.stringify(d)).join('; ')
              : JSON.stringify(detail)
        throw new Error(message || 'Censoring failed')
      }

      const result = await resp.json()
      // Batch exports name their output inside the chosen folder without a
      // per-file dialog, so this is where the edit gets its grant.
      if (typeof result?.output_path === 'string') await fileAccess.grant([result.output_path])
      return result
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      throw new Error(`Censor error: ${await describeBackendError(msg)}`)
    }
  }
)

// --- History IPC Handlers ---

ipcMain.handle('get-history', async () => {
  const history = getHistory()
  // Edits this app saved in earlier sessions: the history list plays them.
  await fileAccess.grant(history.map((h) => h.censoredFilePath))
  return history
})

ipcMain.handle('add-history-entry', (_event, entry) => {
  return addHistoryEntry(entry)
})

ipcMain.handle('delete-history-entry', (_event, id: string) => {
  deleteHistoryEntry(id)
})

// --- Shell IPC Handlers ---

ipcMain.handle('open-external', (_event, url: string) => {
  return shell.openExternal(url)
})

// A stable per-installation id for analytics. It lives in userData so it
// survives the renderer's localStorage being cleared, and unlike a hardware id
// it carries nothing identifying. Generated once, on first request.
let machineIdPromise: Promise<string> | null = null
ipcMain.handle('get-machine-id', () => {
  if (!machineIdPromise) {
    machineIdPromise = (async () => {
      const file = join(app.getPath('userData'), 'machine-id')
      try {
        const existing = (await readFile(file, 'utf8')).trim()
        if (/^[0-9a-f-]{36}$/i.test(existing)) return existing
      } catch {
        /* first run */
      }
      const id = randomUUID()
      await writeFile(file, id, 'utf8').catch(() => {})
      return id
    })()
  }
  return machineIdPromise
})

ipcMain.handle('get-device-info', async () => {
  try {
    return await getDeviceInfo()
  } catch (err) {
    console.error('[IPC] Failed to get device info:', err)
    return { gpu_available: false, device_type: 'cpu', device_name: 'CPU', turbo_supported: false }
  }
})

// --- Auto-Updater ---

function setupAutoUpdater(): void {
  autoUpdater.on('update-available', (info) => {
    log.info('[AutoUpdater] Update available:', info.version)
    sendToMain('update-available', {
      version: info.version,
      releaseNotes: info.releaseNotes
    })
  })

  autoUpdater.on('download-progress', (progress) => {
    sendToMain('download-progress', {
      percent: progress.percent
    })
  })

  autoUpdater.on('update-downloaded', (info) => {
    log.info('[AutoUpdater] Update downloaded:', info.version)
    sendToMain('update-downloaded', {
      version: info.version
    })
  })

  autoUpdater.on('update-not-available', () => {
    log.info('[AutoUpdater] No update available')
    sendToMain('update-not-available')
  })

  autoUpdater.on('error', (err) => {
    log.error('[AutoUpdater] Error:', err)
    sendToMain('update-error', err.message)
  })
}

ipcMain.handle('download-update', async () => {
  const free = await freeSpaceOnAppVolume()
  if (free !== null && free < UPDATE_FREE_SPACE_BYTES) {
    const needGb = Math.round(UPDATE_FREE_SPACE_BYTES / 1024 ** 3)
    const haveGb = (free / 1024 ** 3).toFixed(1)
    const message =
      `Not enough free space to update. Cleanse needs about ${needGb} GB free ` +
      `during the update (${haveGb} GB available). Free up space and try again.`
    log.warn(`[AutoUpdater] ${message}`)
    sendToMain('update-error', message)
    return { started: false, message }
  }
  await autoUpdater.downloadUpdate()
  return { started: true }
})

ipcMain.handle('install-update', async () => {
  // Kill the backend tree first: NSIS cannot replace files that
  // cleanse-backend.exe or its ffmpeg children hold open, and quitAndInstall
  // spawns the installer before before-quit gets a chance to run.
  log.info('[AutoUpdater] Stopping backend before install')
  await stopPythonBackendAndWait()
  // isSilent=true runs the NSIS installer with /S: no wizard, and no
  // per-user/per-machine page that could flip the install mode mid-update.
  // isForceRunAfter=true relaunches the app when the installer finishes.
  autoUpdater.quitAndInstall(true, true)
})

ipcMain.handle('check-for-updates', async () => {
  try {
    const result = await autoUpdater.checkForUpdates()
    return { updateAvailable: !!result?.updateInfo }
  } catch (err) {
    log.error('[AutoUpdater] Manual check failed:', err)
    return { updateAvailable: false }
  }
})

// Propagate the authenticated user identity from the renderer so Sentry events
// captured in the main process are tagged with the same uid as renderer-side events.
ipcMain.on('set-sentry-user', (_event, user: { id: string; email?: string } | null) => {
  Sentry.setUser(user)
})

// --- App Lifecycle ---

function getAudioMimeType(filePath: string): string {
  const ext = extname(filePath).toLowerCase()
  const mimeTypes: Record<string, string> = {
    '.mp3': 'audio/mpeg',
    '.wav': 'audio/wav',
    '.ogg': 'audio/ogg',
    '.m4a': 'audio/mp4',
    '.flac': 'audio/flac',
    '.aac': 'audio/aac',
    '.wma': 'audio/x-ms-wma',
    '.aiff': 'audio/aiff',
    '.aif': 'audio/aiff'
  }
  return mimeTypes[ext] || 'application/octet-stream'
}

function getMimeType(filePath: string): string {
  const ext = extname(filePath).toLowerCase()
  const mimeTypes: Record<string, string> = {
    '.html': 'text/html',
    '.js': 'text/javascript',
    '.css': 'text/css',
    '.json': 'application/json',
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.gif': 'image/gif',
    '.svg': 'image/svg+xml',
    '.ico': 'image/x-icon',
    '.woff': 'font/woff',
    '.woff2': 'font/woff2',
    '.ttf': 'font/ttf'
  }
  return mimeTypes[ext] || 'application/octet-stream'
}

protocol.registerSchemesAsPrivileged([
  {
    scheme: 'media',
    privileges: {
      secure: true,
      standard: false,
      supportFetchAPI: true,
      stream: true
    }
  },
  {
    scheme: 'app',
    privileges: {
      secure: true,
      standard: true,
      supportFetchAPI: true
    }
  }
])

app.whenReady().then(async () => {
  electronApp.setAppUserModelId('com.electron.cleanse')

  // userData is only reliable once the app is ready; the music folder picked
  // in an earlier session becomes a readable root from the start of this one.
  fileAccess.setRoot('music', getSettings().musicFolder)

  // Register custom protocol to serve local audio files to the renderer
  // Supports HTTP Range requests so <audio> elements can seek
  protocol.handle('media', async (request) => {
    const filePath = await fileAccess.allow(mediaUrlToPath(request.url))
    if (!filePath) {
      refused('a file to play')
      return new Response('Forbidden', { status: 403 })
    }

    try {
      const fileStat = await stat(filePath)
      const fileSize = fileStat.size
      const mimeType = getAudioMimeType(filePath)
      const rangeHeader = request.headers.get('Range')

      if (rangeHeader) {
        const match = rangeHeader.match(/bytes=(\d+)-(\d*)/)
        if (!match) {
          return new Response('Invalid range', {
            status: 416,
            headers: { 'Content-Range': `bytes */${fileSize}` }
          })
        }

        const start = parseInt(match[1], 10)
        const end = match[2] ? parseInt(match[2], 10) : fileSize - 1

        if (start >= fileSize || end >= fileSize || start > end) {
          return new Response('Range not satisfiable', {
            status: 416,
            headers: { 'Content-Range': `bytes */${fileSize}` }
          })
        }

        const chunkSize = end - start + 1
        const nodeStream = createReadStream(filePath, { start, end })
        const webStream = Readable.toWeb(nodeStream) as ReadableStream

        return new Response(webStream, {
          status: 206,
          headers: {
            'Content-Range': `bytes ${start}-${end}/${fileSize}`,
            'Accept-Ranges': 'bytes',
            'Content-Length': String(chunkSize),
            'Content-Type': mimeType,
            'Access-Control-Allow-Origin': '*'
          }
        })
      }

      // No Range header — serve full file with Accept-Ranges so browser knows seeking is available
      const nodeStream = createReadStream(filePath)
      const webStream = Readable.toWeb(nodeStream) as ReadableStream

      return new Response(webStream, {
        status: 200,
        headers: {
          'Accept-Ranges': 'bytes',
          'Content-Length': String(fileSize),
          'Content-Type': mimeType,
          'Access-Control-Allow-Origin': '*'
        }
      })
    } catch (err) {
      console.error('[media protocol] Failed to load:', filePath, err)
      return new Response('File not found', { status: 404 })
    }
  })

  // Serve renderer files via app:// protocol so the origin is treated as secure
  // (required for Firebase Analytics / gtag.js which refuses file:// origins)
  const rendererDir = join(__dirname, '../renderer')

  protocol.handle('app', async (request) => {
    const url = new URL(request.url)
    let filePath = decodeURIComponent(url.pathname)

    if (filePath === '/' || filePath === '') {
      filePath = '/index.html'
    }

    const resolvedPath = join(rendererDir, filePath)

    // Prevent directory traversal
    if (!resolvedPath.startsWith(rendererDir)) {
      return new Response('Forbidden', { status: 403 })
    }

    try {
      const fileStat = await stat(resolvedPath)
      if (!fileStat.isFile()) {
        return new Response('Not found', { status: 404 })
      }

      const mimeType = getMimeType(resolvedPath)
      const nodeStream = createReadStream(resolvedPath)
      const webStream = Readable.toWeb(nodeStream) as ReadableStream

      return new Response(webStream, {
        status: 200,
        headers: {
          'Content-Type': mimeType,
          'Content-Length': String(fileStat.size)
        }
      })
    } catch {
      return new Response('Not found', { status: 404 })
    }
  })

  app.on('browser-window-created', (_, window) => {
    optimizer.watchWindowShortcuts(window)
  })

  createWindow()

  // Set up auto-updater and check for updates
  setupAutoUpdater()
  autoUpdater.checkForUpdates().catch((err) => {
    log.error('[AutoUpdater] Failed to check for updates:', err)
  })

  // Start Python backend after window is created
  try {
    await startPythonBackend()
    sendToMain('backend-status', { ready: true })

    // Fetch and send device info to renderer
    try {
      const deviceInfo = await getDeviceInfo()
      sendToMain('device-info', deviceInfo)
    } catch (err) {
      console.error('[Main] Failed to fetch device info:', err)
    }
  } catch (err) {
    Sentry.captureException(err)
    console.error('Failed to start Python backend:', err)
    sendToMain('backend-status', { ready: false, error: (err as Error).message })
  }

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('before-quit', () => {
  stopPythonBackend()

  // Clean up preview directory
  if (existsSync(PREVIEW_DIR)) {
    try {
      rmSync(PREVIEW_DIR, { recursive: true, force: true })
    } catch (err) {
      console.error('[Main] Failed to cleanup preview directory:', err)
    }
  }
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit()
  }
})
