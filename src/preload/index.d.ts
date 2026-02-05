import type {
  ElectronAPI,
  TranscriptionResult,
  TranscribedWord,
  CensorWord,
  BackendStatus,
  SeparationResult
} from './index'

declare global {
  interface Window {
    electronAPI: ElectronAPI
  }
}

export type { ElectronAPI, TranscriptionResult, TranscribedWord, CensorWord, BackendStatus, SeparationResult }
