const DOT_COLOR: Record<string, string> = {
  active:     'rgb(var(--color-status-active))',
  suspended:  'rgb(var(--color-status-suspended))',
  terminated: 'rgb(var(--color-status-terminated))',
  inactive:   'rgb(var(--color-status-inactive))',
  running:    'rgb(var(--color-status-running))',
  queued:     'rgb(var(--color-status-inactive))',
  completed:  'rgb(var(--color-status-active))',
  failed:     'rgb(var(--color-status-terminated))',
}

const LABEL: Record<string, string> = {
  active: 'Active', suspended: 'Suspended', terminated: 'Terminated',
  inactive: 'Inactive', running: 'Running', queued: 'Queued',
  completed: 'Completed', failed: 'Failed',
}

export default function StatusBadge({ status }: { status: string }) {
  const color = DOT_COLOR[status] ?? 'rgb(var(--color-status-inactive))'
  const label = LABEL[status] ?? status
  return (
    <span className="inline-flex items-center gap-1.5">
      <span
        className={`w-2 h-2 rounded-full shrink-0 ${status === 'running' ? 'animate-pulse' : ''}`}
        style={{ backgroundColor: color }}
      />
      <span className="text-sm text-[rgb(var(--color-text))]">{label}</span>
    </span>
  )
}
