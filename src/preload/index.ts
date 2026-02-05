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

export interface ElectronAPI {
  selectAudioFile: () => Promise<string | null>
  selectAudioFiles: () => Promise<string[]>
  selectOutputPath: (defaultName: string) => Promise<string | null>
  selectOutputDirectory: () => Promise<string | null>
  transcribeFile: (path: string) => Promise<TranscriptionResult>
  separateAudio: (path: string) => Promise<SeparationResult>
  censorAudio: (
    path: string,
    words: CensorWord[],
    outputPath?: string,
    vocalsPath?: string,
    accompanimentPath?: string
  ) => Promise<{ output_path: string }>
  getBackendStatus: () => Promise<{ ready: boolean }>
  onBackendStatus: (callback: (status: BackendStatus) => void) => () => void
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

  transcribeFile: (path: string) => ipcRenderer.invoke('transcribe-file', path),

  separateAudio: (path: string) => ipcRenderer.invoke('separate-audio', path),

  censorAudio: (path: string, words: CensorWord[], outputPath?: string, vocalsPath?: string, accompanimentPath?: string) =>
    ipcRenderer.invoke('censor-audio', path, words, outputPath, vocalsPath, accompanimentPath),

  getBackendStatus: () => ipcRenderer.invoke('get-backend-status'),

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
