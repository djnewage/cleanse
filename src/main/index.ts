import { app, shell, BrowserWindow, ipcMain, dialog, protocol } from 'electron'
import { join, extname } from 'path'
import { createReadStream } from 'fs'
import { stat } from 'fs/promises'
import { Readable } from 'stream'
import { electronApp, optimizer, is } from '@electron-toolkit/utils'
import { autoUpdater } from 'electron-updater'
import log from 'electron-log'
import {
  startPythonBackend,
  stopPythonBackend,
  isBackendReady,
  fetchBackend,
  setProgressCallback,
  getDeviceInfo
} from './python-bridge'
import { getHistory, addHistoryEntry, deleteHistoryEntry } from './history-store'

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
    mainWindow.loadFile(join(__dirname, '../renderer/index.html'))
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

ipcMain.handle('transcribe-file', async (_event, filePath: string, turbo: boolean = false) => {
  try {
    console.log('[IPC] transcribe-file called with:', filePath, 'turbo:', turbo)
    const resp = await fetchBackend('/transcribe', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: filePath, turbo })
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
      throw new Error(message || 'Transcription failed')
    }

    return await resp.json()
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err)
    throw new Error(`Transcription error: ${msg}`)
  }
})

ipcMain.handle('separate-audio', async (_event, filePath: string, turbo: boolean = false) => {
  try {
    console.log('[IPC] separate-audio called with:', filePath, 'turbo:', turbo)
    setProgressCallback((data) => {
      mainWindow?.webContents.send('separation-progress', data)
    })

    const resp = await fetchBackend('/separate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: filePath, turbo })
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
      throw new Error(message || 'Separation failed')
    }

    return await resp.json()
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err)
    throw new Error(`Separation error: ${msg}`)
  } finally {
    setProgressCallback(null)
  }
})

ipcMain.handle(
  'censor-audio',
  async (
    _event,
    filePath: string,
    words: Array<{ word: string; start: number; end: number; censor_type: string }>,
    outputPath?: string,
    vocalsPath?: string,
    accompanimentPath?: string
  ) => {
    try {
      const body: Record<string, unknown> = { path: filePath, words, output_path: outputPath }
      if (vocalsPath && accompanimentPath) {
        body.vocals_path = vocalsPath
        body.accompaniment_path = accompanimentPath
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
      throw new Error(`Censor error: ${msg}`)
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

protocol.registerSchemesAsPrivileged([
  {
    scheme: 'media',
    privileges: {
      secure: true,
      standard: false,
      supportFetchAPI: true,
      stream: true
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
    console.error('Failed to start Python backend:', err)
    mainWindow?.webContents.send('backend-status', { ready: false, error: (err as Error).message })
  }

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('before-quit', () => {
  stopPythonBackend()
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit()
  }
})
