import * as Sentry from '@sentry/electron/main'

Sentry.init({
  dsn: 'https://c27473b596f92b07557b89836e8e0941@o4510700679593984.ingest.us.sentry.io/4510875528921088',
  release: 'cleanse@1.5.2',
  integrations: (defaults) => defaults.filter((i) => i.name !== 'PreloadInjection')
})

import { app, shell, BrowserWindow, ipcMain, dialog, protocol } from 'electron'
import { join, extname } from 'path'
import { createReadStream } from 'fs'
import { stat } from 'fs/promises'
import { Readable } from 'stream'
import { existsSync, rmSync } from 'fs'
import { tmpdir } from 'os'
import { electronApp, optimizer, is } from '@electron-toolkit/utils'
import { autoUpdater } from 'electron-updater'
import log from 'electron-log'
import {
  startPythonBackend,
  stopPythonBackend,
  isBackendReady,
  isBackendAlive,
  getBackendLogPath,
  fetchBackend,
  fetchBackendStreaming,
  setProgressCallback,
  setTranscriptionProgressCallback,
  getDeviceInfo
} from './python-bridge'
import { getHistory, addHistoryEntry, deleteHistoryEntry } from './history-store'

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

ipcMain.handle('select-audio-file', async () => {
  if (!mainWindow) return null
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ['openFile'],
    filters: [
      { name: 'Audio Files', extensions: ['mp3', 'wav', 'ogg', 'm4a', 'flac', 'aac', 'wma'] }
    ]
  })
  if (result.canceled || result.filePaths.length === 0) return null
  return result.filePaths[0]
})

ipcMain.handle('select-audio-files', async () => {
  if (!mainWindow) return []
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ['openFile', 'multiSelections'],
    filters: [
      { name: 'Audio Files', extensions: ['mp3', 'wav', 'ogg', 'm4a', 'flac', 'aac', 'wma'] }
    ]
  })
  if (result.canceled || result.filePaths.length === 0) return []
  return result.filePaths
})

ipcMain.handle('select-output-directory', async () => {
  if (!mainWindow) return null
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ['openDirectory', 'createDirectory']
  })
  if (result.canceled || result.filePaths.length === 0) return null
  return result.filePaths[0]
})

ipcMain.handle('select-output-path', async (_event, defaultName: string) => {
  if (!mainWindow) return null
  const result = await dialog.showSaveDialog(mainWindow, {
    defaultPath: defaultName,
    filters: [
      { name: 'Audio Files', extensions: ['mp3', 'wav', 'ogg', 'm4a', 'flac'] }
    ]
  })
  if (result.canceled || !result.filePath) return null
  return result.filePath
})

ipcMain.handle('get-backend-status', () => {
  return { ready: isBackendReady() }
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

ipcMain.handle('fetch-lyrics', async (_event, artist: string, title: string, duration?: number) => {
  try {
    console.log(`[Lyrics] Fetching for: "${artist}" - "${title}"`)
    const resp = await fetchBackend('/fetch-lyrics', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ artist, title, duration })
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

ipcMain.handle('transcribe-file', async (_event, filePath: string, turbo: boolean = false, vocalsPath?: string, lyrics?: string, syncedLyrics?: string) => {
  try {
    console.log('[IPC] transcribe-file called with:', filePath, 'turbo:', turbo, 'vocalsPath:', vocalsPath, 'hasLyrics:', !!lyrics)
    setTranscriptionProgressCallback((data) => {
      mainWindow?.webContents.send('transcription-progress', data)
    })

    const body: Record<string, unknown> = { path: filePath, turbo }
    if (vocalsPath) {
      body.vocals_path = vocalsPath
    }
    if (lyrics) {
      body.lyrics = lyrics
    }
    if (syncedLyrics) {
      body.synced_lyrics = syncedLyrics
    }

    const result = await fetchBackendStreaming<{
      words: Array<Record<string, unknown>>
      duration: number
      language: string
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
  try {
    console.log('[IPC] separate-audio called with:', filePath, 'turbo:', turbo)
    setProgressCallback((data) => {
      mainWindow?.webContents.send('separation-progress', data)
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
    }
  ) => {
    try {
      const body: Record<string, unknown> = {
        path: args.filePath,
        words: args.censorWords,
        crossfade_ms: args.crossfadeMs
      }
      if (args.vocalsPath && args.accompanimentPath) {
        body.vocals_path = args.vocalsPath
        body.accompaniment_path = args.accompanimentPath
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
    crossfadeMs?: number
  ) => {
    try {
      const body: Record<string, unknown> = { path: filePath, words, output_path: outputPath }
      if (vocalsPath && accompanimentPath) {
        body.vocals_path = vocalsPath
        body.accompaniment_path = accompanimentPath
      }
      if (crossfadeMs !== undefined) {
        body.crossfade_ms = crossfadeMs
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

      return await resp.json()
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      throw new Error(`Censor error: ${await describeBackendError(msg)}`)
    }
  }
)

// --- History IPC Handlers ---

ipcMain.handle('get-history', () => {
  return getHistory()
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
    mainWindow?.webContents.send('update-available', {
      version: info.version,
      releaseNotes: info.releaseNotes
    })
  })

  autoUpdater.on('download-progress', (progress) => {
    mainWindow?.webContents.send('download-progress', {
      percent: progress.percent
    })
  })

  autoUpdater.on('update-downloaded', (info) => {
    log.info('[AutoUpdater] Update downloaded:', info.version)
    mainWindow?.webContents.send('update-downloaded', {
      version: info.version
    })
  })

  autoUpdater.on('error', (err) => {
    log.error('[AutoUpdater] Error:', err)
  })
}

ipcMain.handle('download-update', () => {
  return autoUpdater.downloadUpdate()
})

ipcMain.handle('install-update', () => {
  autoUpdater.quitAndInstall()
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
    '.wma': 'audio/x-ms-wma'
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

  // Register custom protocol to serve local audio files to the renderer
  // Supports HTTP Range requests so <audio> elements can seek
  protocol.handle('media', async (request) => {
    const raw = request.url.slice('media://'.length)
    const filePath = decodeURIComponent(raw)

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
            'Content-Type': mimeType
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
          'Content-Type': mimeType
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
    mainWindow?.webContents.send('backend-status', { ready: true })

    // Fetch and send device info to renderer
    try {
      const deviceInfo = await getDeviceInfo()
      mainWindow?.webContents.send('device-info', deviceInfo)
    } catch (err) {
      console.error('[Main] Failed to fetch device info:', err)
    }
  } catch (err) {
    Sentry.captureException(err)
    console.error('Failed to start Python backend:', err)
    mainWindow?.webContents.send('backend-status', { ready: false, error: (err as Error).message })
  }

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('before-quit', () => {
  stopPythonBackend()

  // Clean up preview directory
  const previewDir = join(tmpdir(), 'cleanse-preview')
  if (existsSync(previewDir)) {
    try {
      rmSync(previewDir, { recursive: true, force: true })
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
