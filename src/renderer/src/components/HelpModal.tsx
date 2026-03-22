interface HelpModalProps {
  isOpen: boolean
  onClose: () => void
}

export default function HelpModal({ isOpen, onClose }: HelpModalProps): React.JSX.Element | null {
  if (!isOpen) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-overlay backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Modal */}
      <div className="relative bg-surface rounded-xl border border-border p-6 max-w-lg w-full mx-4 shadow-2xl max-h-[85vh] overflow-y-auto">
        {/* Close button */}
        <button
          onClick={onClose}
          className="absolute top-4 right-4 text-text-tertiary hover:text-text-primary text-lg"
        >
          ✕
        </button>

        <h2 className="text-xl font-bold text-text-primary mb-1">Quick Reference</h2>
        <p className="text-text-tertiary text-sm mb-5">How to use Cleanse</p>

        {/* Workflow */}
        <Section title="Workflow">
          <Step n={1}>Drop audio files to import them into the queue</Step>
          <Step n={2}>Songs are automatically processed (separated + transcribed)</Step>
          <Step n={3}>Review flagged words in the transcript editor</Step>
          <Step n={4}>Export clean versions individually or in bulk</Step>
        </Section>

        {/* Transcript editing */}
        <Section title="Transcript Editing">
          <Row label="Click a word" desc="Toggle its profanity flag on/off" />
          <Row label="Right-click a flagged word" desc="Cycle censor type (mute, beep, reverse, tape stop)" />
          <Row label="+ Add Censor" desc="Manually flag a word the detector missed" />
          <Row
            label={<span className="inline-flex items-center gap-1">&times; on <Badge color="purple">MN</Badge> words</span>}
            desc="Remove a manually added censor"
          />
        </Section>

        {/* Badges */}
        <Section title="Detection Badges">
          <Row label={<Badge color="red">M / B / R / T</Badge>} desc="Censor type (Mute, Beep, Reverse, Tape stop)" />
          <Row label={<Badge color="amber">AD</Badge>} desc="Found by ad-lib detection (dual-pass)" />
          <Row label={<Badge color="cyan">LY</Badge>} desc="Matched from fetched lyrics" />
          <Row label={<Badge color="teal">LG</Badge>} desc="Found in a lyrics gap (missing from transcript)" />
          <Row label={<Badge color="orange">LC</Badge>} desc="Lyrics-corrected transcription" />
          <Row label={<Badge color="purple">MN</Badge>} desc="Manually added by you" />
        </Section>

        {/* Settings */}
        <Section title="Settings">
          <Row label="Dual-Pass" desc="Runs a second transcription pass on isolated vocals to catch ad-libs" />
          <Row label="Turbo" desc="Uses a faster (but slightly less accurate) transcription model" />
          <Row label="Crossfade" desc="Smooths the transition in/out of each censor so it sounds natural" />
          <Row label="Censor Range" desc="Extends the censor before and after each word (higher = more aggressive, catches bleed)" />
        </Section>

        <button
          onClick={onClose}
          className="w-full mt-4 py-2.5 rounded-lg font-medium text-sm bg-elevated text-text-secondary hover:bg-muted transition-colors"
        >
          Got it
        </button>
      </div>
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }): React.JSX.Element {
  return (
    <div className="mb-5">
      <h3 className="text-xs font-semibold text-text-secondary uppercase tracking-wider mb-2">{title}</h3>
      <div className="space-y-1.5">{children}</div>
    </div>
  )
}

function Step({ n, children }: { n: number; children: React.ReactNode }): React.JSX.Element {
  return (
    <div className="flex items-start gap-2.5 text-sm">
      <span className="flex-shrink-0 w-5 h-5 rounded-full bg-elevated text-text-secondary text-xs flex items-center justify-center font-medium">
        {n}
      </span>
      <span className="text-text-secondary">{children}</span>
    </div>
  )
}

function Row({ label, desc }: { label: React.ReactNode; desc: string }): React.JSX.Element {
  return (
    <div className="flex items-start gap-2 text-sm">
      <span className="text-text-primary font-medium min-w-[140px] flex-shrink-0">{label}</span>
      <span className="text-text-tertiary">{desc}</span>
    </div>
  )
}

const BADGE_COLORS: Record<string, string> = {
  red: 'text-red-400',
  amber: 'text-amber-400',
  cyan: 'text-cyan-400',
  teal: 'text-teal-400',
  orange: 'text-orange-400',
  purple: 'text-purple-400'
}

function Badge({ color, children }: { color: string; children: React.ReactNode }): React.JSX.Element {
  return (
    <span className={`text-[10px] font-bold font-mono ${BADGE_COLORS[color] ?? 'text-text-secondary'}`}>
      {children}
    </span>
  )
}
