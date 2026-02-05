export interface TranscribedWord {
  word: string
  start: number
  end: number
  confidence: number
  is_profanity: boolean
  censor_type?: CensorType
}

export interface CensorWord {
  word: string
  start: number
  end: number
  censor_type: CensorType
}

export type CensorType = 'mute' | 'beep' | 'reverse'

export type AppStatus = 'idle' | 'loading-backend' | 'ready' | 'transcribing' | 'separating' | 'censoring' | 'error'

export interface AppState {
  status: AppStatus
  backendReady: boolean
  filePath: string | null
  fileName: string | null
  words: TranscribedWord[]
  duration: number
  language: string
  defaultCensorType: CensorType
  censoredFilePath: string | null
  errorMessage: string | null
  vocalsPath: string | null
  accompanimentPath: string | null
}

export type AppAction =
  | { type: 'SET_BACKEND_STATUS'; ready: boolean; error?: string }
  | { type: 'SET_FILE'; path: string; name: string }
  | { type: 'CLEAR_FILE' }
  | { type: 'START_TRANSCRIPTION' }
  | { type: 'TRANSCRIPTION_COMPLETE'; words: TranscribedWord[]; duration: number; language: string }
  | { type: 'TOGGLE_PROFANITY'; index: number }
  | { type: 'SET_CENSOR_TYPE'; index: number; censorType: CensorType }
  | { type: 'SET_DEFAULT_CENSOR_TYPE'; censorType: CensorType }
  | { type: 'START_SEPARATING' }
  | { type: 'SEPARATION_COMPLETE'; vocalsPath: string; accompanimentPath: string }
  | { type: 'START_CENSORING' }
  | { type: 'CENSORING_COMPLETE'; outputPath: string }
  | { type: 'SET_ERROR'; message: string }
  | { type: 'CLEAR_ERROR' }
