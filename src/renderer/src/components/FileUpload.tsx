import { useCallback, useState } from 'react'

interface FileUploadProps {
  onFileSelected: (path: string, name: string) => void
  disabled: boolean
}

export default function FileUpload({ onFileSelected, disabled }: FileUploadProps): React.JSX.Element {
  const [isDragging, setIsDragging] = useState(false)

  const handleClick = useCallback(async () => {
    const filePath = await window.electronAPI.selectAudioFile()
    if (filePath) {
      const name = filePath.split('/').pop() || filePath
      onFileSelected(filePath, name)
    }
  }, [onFileSelected])

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

      const files = e.dataTransfer.files
      if (files.length > 0) {
        const file = files[0]
        const audioExts = ['.mp3', '.wav', '.ogg', '.m4a', '.flac', '.aac', '.wma']
        const ext = file.name.substring(file.name.lastIndexOf('.')).toLowerCase()
        if (audioExts.includes(ext)) {
          const filePath = window.electronAPI.getPathForFile(file)
          if (filePath) {
            onFileSelected(filePath, file.name)
          }
        }
      }
    },
    [disabled, onFileSelected]
  )

  return (
    <div
      onClick={disabled ? undefined : handleClick}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      className={`
        border-2 border-dashed rounded-xl p-10 text-center transition-all
        ${disabled ? 'border-zinc-700 bg-zinc-900/50 text-zinc-600 cursor-not-allowed' : 'cursor-pointer'}
        ${isDragging ? 'border-blue-400 bg-blue-950/30 text-blue-300' : ''}
        ${!disabled && !isDragging ? 'border-zinc-600 bg-zinc-900/30 text-zinc-400 hover:border-zinc-400 hover:text-zinc-300' : ''}
      `}
    >
      <div className="text-4xl mb-3">🎵</div>
      <p className="text-lg font-medium mb-1">
        {disabled ? 'Waiting for backend...' : 'Drop an audio file here'}
      </p>
      <p className="text-sm opacity-60">
        {disabled ? 'The Python backend is starting up' : 'or click to browse • MP3, WAV, OGG, M4A, FLAC'}
      </p>
    </div>
  )
}
