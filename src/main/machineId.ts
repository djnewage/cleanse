import { createHash } from 'crypto'
import { machineIdSync } from 'node-machine-id'

let cachedMachineId: string | null = null

export function getHashedMachineId(): string {
  if (cachedMachineId) return cachedMachineId
  const rawId = machineIdSync()
  cachedMachineId = createHash('sha256').update(`cleanse-v1-${rawId}`).digest('hex')
  return cachedMachineId
}

/** Reset the cached machine ID — only for testing */
export function _resetCache(): void {
  cachedMachineId = null
}
