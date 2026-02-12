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
      const errCause =
        err instanceof Error && err.cause ? ` (cause: ${JSON.stringify(err.cause)})` : ''
      if (attempt < maxRetries && isBackendAlive()) {
        writeLog(
          `[fetch] ${endpoint} attempt ${attempt + 1} failed (${errMsg}${errCause}), retrying in 2s...`
        )
        await new Promise((r) => setTimeout(r, 2000))
        continue
      }
      writeLog(`[fetch] ${endpoint} failed after ${attempt + 1} attempts: ${errMsg}${errCause}`)
      throw err
    }
  }
  // Unreachable — loop always returns or throws — but satisfies TypeScript
  throw new Error(`fetchBackend: exhausted retries for ${endpoint}`)
}

/**
 * Fetch a streaming NDJSON endpoint (for long-running operations like /separate
 * and /transcribe). Reads the response body line-by-line, ignores heartbeat
 * lines, and returns the parsed result. No retries — restarting a multi-minute
 * operation from scratch would be counterproductive.
 */
export async function fetchBackendStreaming<T = unknown>(
  endpoint: string,
  options?: RequestInit & { timeoutMs?: number }
): Promise<T> {
  const { timeoutMs = 600_000, ...fetchOptions } = options ?? {}
  const url = `http://127.0.0.1:${backendPort}${endpoint}`
  const controller = new AbortController()

  // Idle timeout: resets each time a heartbeat arrives.
  // timeoutMs = max silence before aborting (not total operation time).
  let timer = setTimeout(() => controller.abort(), timeoutMs)
  const resetTimer = (): void => {
    clearTimeout(timer)
    timer = setTimeout(() => controller.abort(), timeoutMs)
  }

  let resp: Response
  try {
    resp = await fetch(url, { ...fetchOptions, signal: controller.signal })
  } catch (err) {
    clearTimeout(timer)
    const errMsg = err instanceof Error ? err.message : String(err)
    const errCause =
      err instanceof Error && err.cause ? ` (cause: ${JSON.stringify(err.cause)})` : ''
    writeLog(`[fetch-streaming] ${endpoint} connection failed: ${errMsg}${errCause}`)
    throw err
  }

  if (!resp.ok) {
    clearTimeout(timer)
    const text = await resp.text()
    throw new Error(`Backend returned ${resp.status}: ${text}`)
  }

  if (!resp.body) {
    clearTimeout(timer)
    throw new Error('Backend returned empty body for streaming endpoint')
  }

  try {
    const reader = resp.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })

      const lines = buffer.split('\n')
      buffer = lines.pop()! // keep incomplete line in buffer

      for (const line of lines) {
        if (!line.trim()) continue

        let parsed: { type: string; data?: T; detail?: string }
        try {
          parsed = JSON.parse(line)
        } catch {
          writeLog(`[fetch-streaming] ${endpoint} unparseable line: ${line}`)
          continue
        }

        if (parsed.type === 'heartbeat') {
          resetTimer() // Backend is alive — reset idle timeout
          continue
        }

        if (parsed.type === 'error') {
          throw new Error(parsed.detail || 'Backend streaming error')
        }

        if (parsed.type === 'result') {
          clearTimeout(timer)
          return parsed.data as T
        }
      }
    }
  } catch (err) {
    clearTimeout(timer)
    throw err
  }

  clearTimeout(timer)
  throw new Error(`Backend stream ended without a result for ${endpoint}`)
}
