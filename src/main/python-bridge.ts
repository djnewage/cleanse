import { ChildProcess, spawn } from 'child_process'
import { app } from 'electron'
import * as path from 'path'
import * as fs from 'fs'
import * as net from 'net'

let pythonProcess: ChildProcess | null = null
let backendPort: number = 8765
let isReady = false
let logFilePath: string | null = null
let logStream: fs.WriteStream | null = null

export type ProgressCallback = (data: {
  step: string
  progress: number
  message: string
}) => void

let progressCallback: ProgressCallback | null = null
let transcriptionProgressCallback: ProgressCallback | null = null

export function setProgressCallback(cb: ProgressCallback | null): void {
  progressCallback = cb
}

export function setTranscriptionProgressCallback(cb: ProgressCallback | null): void {
  transcriptionProgressCallback = cb
}

function initLogFile(): void {
  const logDir = app.getPath('logs')
  logFilePath = path.join(logDir, 'backend.log')
  // Truncate on each app launch so the file stays manageable
  logStream = fs.createWriteStream(logFilePath, { flags: 'w' })
}

function writeLog(line: string): void {
  logStream?.write(`${new Date().toISOString()} ${line}\n`)
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

function getBackendCommand(): { command: string; args: string[] } {
  if (app.isPackaged) {
    // PyInstaller binary — standalone executable, no Python needed
    const binary = path.join(process.resourcesPath, 'backend', 'cleanse-backend')
    return { command: binary, args: ['--port', String(backendPort)] }
  }
  // Dev mode — use venv python + main.py
  const pythonPath = path.join(getBackendPath(), 'venv', 'bin', 'python3')
  return { command: pythonPath, args: ['main.py', '--port', String(backendPort)] }
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
  initLogFile()
  backendPort = await findFreePort()
  const { command, args } = getBackendCommand()

  console.log(`[Python] Starting backend on port ${backendPort}`)
  console.log(`[Python] Command: ${command} ${args.join(' ')}`)
  console.log(`[Python] Packaged: ${app.isPackaged}`)
  console.log(`[Python] Log file: ${logFilePath}`)
  writeLog(`[startup] Command: ${command} ${args.join(' ')}`)
  writeLog(`[startup] Packaged: ${app.isPackaged}`)

  pythonProcess = spawn(command, args, {
    // PyInstaller binary doesn't need cwd; dev mode needs backend dir
    cwd: app.isPackaged ? undefined : getBackendPath(),
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
        if (parsed.type === 'transcription-progress' && transcriptionProgressCallback) {
          transcriptionProgressCallback({
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
      writeLog(`[stdout] ${trimmed}`)
    }
  })

  pythonProcess.stderr?.on('data', (data: Buffer) => {
    const text = data.toString().trim()
    console.log(`[Python] ${text}`)
    writeLog(`[stderr] ${text}`)
  })

  pythonProcess.on('error', (err) => {
    console.error('[Python] Failed to start:', err.message)
    writeLog(`[error] Failed to start: ${err.message}`)
    isReady = false
  })

  pythonProcess.on('exit', (code, signal) => {
    console.log(`[Python] Process exited with code ${code} signal ${signal}`)
    writeLog(`[exit] code=${code} signal=${signal}`)
    isReady = false
    pythonProcess = null
  })

  // Wait for backend to be ready
  console.log('[Python] Waiting for backend to be ready...')
  const ready = await pollHealth(backendPort, 30000)

  if (ready) {
    isReady = true
    console.log('[Python] Backend is ready!')
    writeLog('[startup] Backend is ready')
  } else {
    console.error('[Python] Backend failed to start within timeout')
    writeLog('[startup] Backend failed to start within timeout')
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
  logStream?.end()
  logStream = null
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

export function isBackendAlive(): boolean {
  if (pythonProcess === null) return false
  if (pythonProcess.exitCode !== null || pythonProcess.signalCode !== null) return false
  try {
    process.kill(pythonProcess.pid!, 0)
    return true
  } catch {
    return false
  }
}

export function getBackendLogPath(): string | null {
  return logFilePath
}

export async function fetchBackend(
  endpoint: string,
  options?: RequestInit & { timeoutMs?: number }
): Promise<Response> {
  const { timeoutMs = 600_000, ...fetchOptions } = options ?? {}
  const url = `http://127.0.0.1:${backendPort}${endpoint}`
  const maxRetries = 2

  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), timeoutMs)
    try {
      const resp = await fetch(url, { ...fetchOptions, signal: controller.signal })
      clearTimeout(timer)
      return resp
    } catch (err) {
      clearTimeout(timer)
      const errMsg = err instanceof Error ? err.message : String(err)
      if (attempt < maxRetries && isBackendAlive()) {
        writeLog(`[fetch] ${endpoint} attempt ${attempt + 1} failed (${errMsg}), retrying in 2s...`)
        await new Promise((r) => setTimeout(r, 2000))
        continue
      }
      throw err
    }
  }
  // Unreachable — loop always returns or throws — but satisfies TypeScript
  throw new Error(`fetchBackend: exhausted retries for ${endpoint}`)
}
