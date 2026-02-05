import { ChildProcess, spawn } from 'child_process'
import { app } from 'electron'
import * as path from 'path'
import * as net from 'net'

let pythonProcess: ChildProcess | null = null
let backendPort: number = 8765
let isReady = false

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
    console.log(`[Python] ${data.toString().trim()}`)
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
    console.log('[Python] Stopping backend...')
    pythonProcess.kill('SIGTERM')

    // Force kill after 5 seconds
    setTimeout(() => {
      if (pythonProcess && !pythonProcess.killed) {
        console.log('[Python] Force killing backend...')
        pythonProcess.kill('SIGKILL')
      }
    }, 5000)

    pythonProcess = null
    isReady = false
  }
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
