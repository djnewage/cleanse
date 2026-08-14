import { SUPPORT_EMAIL } from '../types'

interface SupportLinkProps {
  className?: string
  label?: string
}

/**
 * The only channel users have to reach us.
 *
 * Goes through shell.openExternal rather than an <a href="mailto:">: the
 * renderer is served from a custom app:// origin, where a raw mailto
 * navigation is swallowed instead of being handed to the OS mail client.
 */
export default function SupportLink({
  className = '',
  label = SUPPORT_EMAIL
}: SupportLinkProps): React.JSX.Element {
  return (
    <button
      type="button"
      onClick={() => window.electronAPI?.openExternal?.(`mailto:${SUPPORT_EMAIL}`)}
      className={`text-blue-400 hover:text-blue-300 underline underline-offset-2 transition-colors ${className}`}
    >
      {label}
    </button>
  )
}
