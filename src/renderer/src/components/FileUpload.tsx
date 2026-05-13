import { useCallback, useState } from 'react'

interface FileUploadProps {
  onFilesSelected: (files: Array<{ path: string; name: string }>) => void
  disabled: boolean
}

const AUDIO_EXTENSIONS = ['.mp3', '.wav', '.ogg', '.m4a', '.flac', '.aac', '.wma']

export default function FileUpload({ onFilesSelected, disabled }: FileUploadProps): React.JSX.Element {
  const [isDragging, setIsDragging] = useState(false)

  const handleClick = useCallback(async () => {
    const filePaths = await window.electronAPI.selectAudioFiles()
    if (filePaths.length > 0) {
      const files = filePaths.map((path) => ({
        path,
        name: path.split(/[\\/]/).pop() || path
      }))
      onFilesSelected(files)
    }
  }, [onFilesSelected])

  const handleDragOver = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault()
      if (!disabled) setIsDragging(true)
    },
    [disabled]
  )

  const handleDragLeave = useCallback(() => {
    setIsDragging(false)
  }, [])

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault()
      setIsDragging(false)
      if (disabled) return

      const droppedFiles = e.dataTransfer.files
      const validFiles: Array<{ path: string; name: string }> = []

      for (let i = 0; i < droppedFiles.length; i++) {
        const file = droppedFiles[i]
        const ext = file.name.substring(file.name.lastIndexOf('.')).toLowerCase()
        if (AUDIO_EXTENSIONS.includes(ext)) {
          const filePath = window.electronAPI.getPathForFile(file)
          if (filePath) {
            validFiles.push({ path: filePath, name: file.name })
          }
        }
      }

      if (validFiles.length > 0) {
        onFilesSelected(validFiles)
      }
    },
    [disabled, onFilesSelected]
  )

  return (
    <div
      onClick={disabled ? undefined : handleClick}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      className={`
        border-2 border-dashed rounded-xl p-10 text-center transition-all
        ${disabled ? 'border-border-strong bg-surface/50 text-text-disabled cursor-not-allowed' : 'cursor-pointer'}
        ${isDragging ? 'border-blue-400 bg-blue-950/30 text-blue-300' : ''}
        ${!disabled && !isDragging ? 'border-border-strong bg-surface/30 text-text-secondary hover:border-border-strong hover:text-text-secondary' : ''}
      `}
    >
      <div className="text-4xl mb-3">🎵</div>
      <p className="text-lg font-medium mb-1">
        {disabled ? 'Waiting for backend...' : 'Drop audio files here'}
      </p>
      <p className="text-sm opacity-60">
        {disabled ? 'The Python backend is starting up' : 'or click to browse • Select multiple files'}
      </p>
      <p className="text-xs opacity-40 mt-2">
        MP3, WAV, OGG, M4A, FLAC, AAC, WMA
      </p>
    </div>
  )
}
