import { contextBridge, ipcRenderer, webUtils } from 'electron'

export interface SeparationResult {
  vocals_path: string
  accompaniment_path: string
}

export interface SeparationProgress {
  step: string
  progress: number
  message: string
}

export interface DeviceInfo {
  gpu_available: boolean
  device_type: string
  device_name: string
  turbo_supported: boolean
}

export interface ElectronAPI {
  selectAudioFile: () => Promise<string | null>
  selectAudioFiles: () => Promise<string[]>
  selectOutputPath: (defaultName: string) => Promise<string | null>
  selectOutputDirectory: () => Promise<string | null>
  transcribeFile: (path: string, turbo?: boolean) => Promise<TranscriptionResult>
  separateAudio: (path: string, turbo?: boolean) => Promise<SeparationResult>
  censorAudio: (
    path: string,
    words: CensorWord[],
    outputPath?: string,
    vocalsPath?: string,
    accompanimentPath?: string
  ) => Promise<{ output_path: string }>
  getBackendStatus: () => Promise<{ ready: boolean }>
  getDeviceInfo: () => Promise<DeviceInfo>
  onBackendStatus: (callback: (status: BackendStatus) => void) => () => void
  onDeviceInfo: (callback: (info: DeviceInfo) => void) => () => void
  onSeparationProgress: (callback: (progress: SeparationProgress) => void) => () => void
  getPathForFile: (file: File) => string
  getHistory: () => Promise<HistoryEntry[]>
  addHistoryEntry: (entry: Omit<HistoryEntry, 'id'>) => Promise<HistoryEntry>
  deleteHistoryEntry: (id: string) => Promise<void>
  openExternal: (url: string) => Promise<void>
}

export interface TranscriptionResult {
  words: TranscribedWord[]
  duration: number
  language: string
}

export interface TranscribedWord {
  word: string
  start: number
  end: number
  confidence: number
  is_profanity: boolean
}

export interface CensorWord {
  word: string
  start: number
  end: number
  censor_type: string
}

export interface BackendStatus {
  ready: boolean
  error?: string
}

export interface HistoryEntry {
  id: string
  originalFileName: string
  originalFilePath: string
  censoredFilePath: string
  dateCreated: number
  wordCount: number
  profanityCount: number
  duration: number
  language: string
}

const electronAPI: ElectronAPI = {
  selectAudioFile: () => ipcRenderer.invoke('select-audio-file'),

  selectAudioFiles: () => ipcRenderer.invoke('select-audio-files'),

  selectOutputPath: (defaultName: string) =>
    ipcRenderer.invoke('select-output-path', defaultName),

  selectOutputDirectory: () => ipcRenderer.invoke('select-output-directory'),

  transcribeFile: (path: string, turbo?: boolean) =>
    ipcRenderer.invoke('transcribe-file', path, turbo ?? false),

  separateAudio: (path: string, turbo?: boolean) =>
    ipcRenderer.invoke('separate-audio', path, turbo ?? false),

  censorAudio: (path: string, words: CensorWord[], outputPath?: string, vocalsPath?: string, accompanimentPath?: string) =>
    ipcRenderer.invoke('censor-audio', path, words, outputPath, vocalsPath, accompanimentPath),

  getBackendStatus: () => ipcRenderer.invoke('get-backend-status'),

  getDeviceInfo: () => ipcRenderer.invoke('get-device-info'),

  onDeviceInfo: (callback: (info: DeviceInfo) => void) => {
    const handler = (_event: Electron.IpcRendererEvent, info: DeviceInfo): void => {
      callback(info)
    }
    ipcRenderer.on('device-info', handler)
    return () => {
      ipcRenderer.removeListener('device-info', handler)
    }
  },

  getPathForFile: (file: File) => webUtils.getPathForFile(file),

  onBackendStatus: (callback: (status: BackendStatus) => void) => {
    const handler = (_event: Electron.IpcRendererEvent, status: BackendStatus): void => {
      callback(status)
    }
    ipcRenderer.on('backend-status', handler)
    return () => {
      ipcRenderer.removeListener('backend-status', handler)
    }
  },

  getHistory: () => ipcRenderer.invoke('get-history'),

  addHistoryEntry: (entry: Omit<HistoryEntry, 'id'>) =>
    ipcRenderer.invoke('add-history-entry', entry),

  deleteHistoryEntry: (id: string) => ipcRenderer.invoke('delete-history-entry', id),

  onSeparationProgress: (callback: (progress: SeparationProgress) => void) => {
    const handler = (_event: Electron.IpcRendererEvent, progress: SeparationProgress): void => {
      callback(progress)
    }
    ipcRenderer.on('separation-progress', handler)
    return () => {
      ipcRenderer.removeListener('separation-progress', handler)
    }
  },

  openExternal: (url: string) => ipcRenderer.invoke('open-external', url)
}

if (process.contextIsolated) {
  try {
    contextBridge.exposeInMainWorld('electronAPI', electronAPI)
  } catch (error) {
    console.error(error)
  }
} else {
  // @ts-ignore
  window.electronAPI = electronAPI
}
