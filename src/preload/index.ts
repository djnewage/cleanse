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

export interface UpdateInfo {
  version: string
  releaseNotes: string | { version: string; note: string }[] | undefined
}

export interface DownloadProgress {
  percent: number
}

export interface AudioMetadata {
  artist: string | null
  title: string | null
  album: string | null
  duration: number | null
}

export interface ElectronAPI {
  selectAudioFile: () => Promise<string | null>
  selectAudioFiles: () => Promise<string[]>
  selectOutputPath: (defaultName: string) => Promise<string | null>
  selectOutputDirectory: () => Promise<string | null>
  getAudioMetadata: (path: string) => Promise<AudioMetadata>
  fetchLyrics: (artist: string, title: string, duration?: number) => Promise<{ plain_lyrics: string | null; synced_lyrics: string | null }>
  transcribeFile: (path: string, turbo?: boolean, vocalsPath?: string, lyrics?: string, syncedLyrics?: string) => Promise<TranscriptionResult>
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
  onTranscriptionProgress: (callback: (progress: SeparationProgress) => void) => () => void
  onSeparationProgress: (callback: (progress: SeparationProgress) => void) => () => void
  onUpdateAvailable: (callback: (info: UpdateInfo) => void) => () => void
  onDownloadProgress: (callback: (progress: DownloadProgress) => void) => () => void
  onUpdateDownloaded: (callback: (info: { version: string }) => void) => () => void
  downloadUpdate: () => Promise<void>
  installUpdate: () => Promise<void>
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
  detection_source?: 'primary' | 'vocals' | 'adlib'
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

  getAudioMetadata: (path: string) => ipcRenderer.invoke('get-audio-metadata', path),

  fetchLyrics: (artist: string, title: string, duration?: number) =>
    ipcRenderer.invoke('fetch-lyrics', artist, title, duration),

  transcribeFile: (path: string, turbo?: boolean, vocalsPath?: string, lyrics?: string, syncedLyrics?: string) =>
    ipcRenderer.invoke('transcribe-file', path, turbo ?? false, vocalsPath, lyrics, syncedLyrics),

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

  onTranscriptionProgress: (callback: (progress: SeparationProgress) => void) => {
    const handler = (_event: Electron.IpcRendererEvent, progress: SeparationProgress): void => {
      callback(progress)
    }
    ipcRenderer.on('transcription-progress', handler)
    return () => {
      ipcRenderer.removeListener('transcription-progress', handler)
    }
  },

  onSeparationProgress: (callback: (progress: SeparationProgress) => void) => {
    const handler = (_event: Electron.IpcRendererEvent, progress: SeparationProgress): void => {
      callback(progress)
    }
    ipcRenderer.on('separation-progress', handler)
    return () => {
      ipcRenderer.removeListener('separation-progress', handler)
    }
  },

  onUpdateAvailable: (callback: (info: UpdateInfo) => void) => {
    const handler = (_event: Electron.IpcRendererEvent, info: UpdateInfo): void => {
      callback(info)
    }
    ipcRenderer.on('update-available', handler)
    return () => {
      ipcRenderer.removeListener('update-available', handler)
    }
  },

  onDownloadProgress: (callback: (progress: DownloadProgress) => void) => {
    const handler = (_event: Electron.IpcRendererEvent, progress: DownloadProgress): void => {
      callback(progress)
    }
    ipcRenderer.on('download-progress', handler)
    return () => {
      ipcRenderer.removeListener('download-progress', handler)
    }
  },

  onUpdateDownloaded: (callback: (info: { version: string }) => void) => {
    const handler = (_event: Electron.IpcRendererEvent, info: { version: string }): void => {
      callback(info)
    }
    ipcRenderer.on('update-downloaded', handler)
    return () => {
      ipcRenderer.removeListener('update-downloaded', handler)
    }
  },

  downloadUpdate: () => ipcRenderer.invoke('download-update'),

  installUpdate: () => ipcRenderer.invoke('install-update'),

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
