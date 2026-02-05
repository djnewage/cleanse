import { app, shell, BrowserWindow, ipcMain, dialog, protocol, net } from 'electron'
import { join } from 'path'
import { electronApp, optimizer, is } from '@electron-toolkit/utils'
import {
  startPythonBackend,
  stopPythonBackend,
  isBackendReady,
  fetchBackend
} from './python-bridge'

let mainWindow: BrowserWindow | null = null

function createWindow(): void {
  mainWindow = new BrowserWindow({
    width: 1100,
    height: 750,
    minWidth: 800,
    minHeight: 600,
    show: false,
    autoHideMenuBar: true,
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

ipcMain.handle('transcribe-file', async (_event, filePath: string) => {
  try {
    console.log('[IPC] transcribe-file called with:', filePath)
    const resp = await fetchBackend('/transcribe', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: filePath })
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

ipcMain.handle('separate-audio', async (_event, filePath: string) => {
  try {
    console.log('[IPC] separate-audio called with:', filePath)
    const resp = await fetchBackend('/separate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: filePath })
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

// --- App Lifecycle ---

app.whenReady().then(async () => {
  electronApp.setAppUserModelId('com.electron.clean-song-editor')

  // Register custom protocol to serve local audio files to the renderer
  protocol.handle('media', (request) => {
    const filePath = decodeURIComponent(request.url.slice('media://'.length))
    return net.fetch(`file://${filePath}`)
  })

  app.on('browser-window-created', (_, window) => {
    optimizer.watchWindowShortcuts(window)
  })

  createWindow()

  // Start Python backend after window is created
  try {
    await startPythonBackend()
    mainWindow?.webContents.send('backend-status', { ready: true })
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
