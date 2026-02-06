import { ChildProcess, spawn } from 'child_process'
import { app } from 'electron'
import * as path from 'path'
import * as net from 'net'

let pythonProcess: ChildProcess | null = null
let backendPort: number = 8765
let isReady = false

export type ProgressCallback = (data: {
  step: string
  progress: number
  message: string
}) => void

let progressCallback: ProgressCallback | null = null

export function setProgressCallback(cb: ProgressCallback | null): void {
  progressCallback = cb
}

function findFreePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const server = net.createServer()
    server.listen(0, '127.0.0.1', () => {
      const addr = server.address()
      if (addr && typeof addr !== 'string') {
        const port = addr.port
        server.close(() => resolve(port))
      } else {
        reject(new Error('Could not find free port'))
      }
    })
    server.on('error', reject)
  })
}

function getBackendPath(): string {
  if (app.isPackaged) {
    return path.join(process.resourcesPath, 'backend')
  }
  return path.join(app.getAppPath(), 'backend')
}

function getPythonPath(): string {
  const backendDir = getBackendPath()
  const venvPython = path.join(backendDir, 'venv', 'bin', 'python3')
  return venvPython
}

async function pollHealth(port: number, timeoutMs: number = 30000): Promise<boolean> {
  const start = Date.now()
  const interval = 500

  while (Date.now() - start < timeoutMs) {
    try {
      const response = await fetch(`http://127.0.0.1:${port}/health`)
      if (response.ok) {
        return true
      }
    } catch {
      // Server not ready yet
    }
    await new Promise((resolve) => setTimeout(resolve, interval))
  }
  return false
}

export async function startPythonBackend(): Promise<number> {
  backendPort = await findFreePort()
  const backendDir = getBackendPath()
  const pythonPath = getPythonPath()

  console.log(`[Python] Starting backend on port ${backendPort}`)
  console.log(`[Python] Backend dir: ${backendDir}`)
  console.log(`[Python] Python path: ${pythonPath}`)

  pythonProcess = spawn(pythonPath, ['main.py', '--port', String(backendPort)], {
    cwd: backendDir,
    stdio: ['pipe', 'pipe', 'pipe'],
    env: {
      ...process.env,
      PYTHONUNBUFFERED: '1'
    }
  })

  pythonProcess.stdout?.on('data', (data: Buffer) => {
    const lines = data.toString().split('\n')
    for (const line of lines) {
      const trimmed = line.trim()
      if (!trimmed) continue
      try {
        const parsed = JSON.parse(trimmed)
        if (parsed.type === 'separation-progress' && progressCallback) {
          progressCallback({
            step: parsed.step,
            progress: parsed.progress,
            message: parsed.message
          })
          continue
        }
      } catch {
        // Not JSON, fall through to normal logging
      }
      console.log(`[Python] ${trimmed}`)
    }
  })

  pythonProcess.stderr?.on('data', (data: Buffer) => {
    console.log(`[Python] ${data.toString().trim()}`)
  })

  pythonProcess.on('error', (err) => {
    console.error('[Python] Failed to start:', err.message)
    isReady = false
  })

  pythonProcess.on('exit', (code) => {
    console.log(`[Python] Process exited with code ${code}`)
    isReady = false
    pythonProcess = null
  })

  // Wait for backend to be ready
  console.log('[Python] Waiting for backend to be ready...')
  const ready = await pollHealth(backendPort, 30000)

  if (ready) {
    isReady = true
    console.log('[Python] Backend is ready!')
  } else {
    console.error('[Python] Backend failed to start within timeout')
    stopPythonBackend()
    throw new Error('Python backend failed to start')
  }

  return backendPort
}

export function stopPythonBackend(): void {
  if (pythonProcess) {
    // Remove all listeners BEFORE killing to prevent EIO crashes
    // during shutdown (handlers firing console.log after Electron's stdout closes)
    pythonProcess.stdout?.removeAllListeners()
    pythonProcess.stderr?.removeAllListeners()
    pythonProcess.removeAllListeners()

    pythonProcess.kill('SIGTERM')

    // Capture reference for the timeout since we null pythonProcess immediately
    const proc = pythonProcess
    setTimeout(() => {
      try {
        if (!proc.killed) proc.kill('SIGKILL')
      } catch {
        /* process already gone */
      }
    }, 5000)

    pythonProcess = null
    isReady = false
  }
}

export interface DeviceInfo {
  gpu_available: boolean
  device_type: string
  device_name: string
  turbo_supported: boolean
}

export async function getDeviceInfo(): Promise<DeviceInfo> {
  const resp = await fetchBackend('/device-info')
  if (!resp.ok) {
    throw new Error('Failed to fetch device info')
  }
  return resp.json()
}

export function getBackendPort(): number {
  return backendPort
}

export function isBackendReady(): boolean {
  return isReady
}

export async function fetchBackend(
  endpoint: string,
  options?: RequestInit
): Promise<Response> {
  const url = `http://127.0.0.1:${backendPort}${endpoint}`
  return fetch(url, options)
}
