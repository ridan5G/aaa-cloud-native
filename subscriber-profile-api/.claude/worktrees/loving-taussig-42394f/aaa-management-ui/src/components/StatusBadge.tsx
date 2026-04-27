const DOT_COLOR: Record<string, string> = {
  active:     '#38A169',
  suspended:  '#F5A623',
  terminated: '#E53E3E',
  inactive:   '#A0AEC0',
  running:    '#3182CE',
  queued:     '#A0AEC0',
  completed:  '#38A169',
  failed:     '#E53E3E',
}

const LABEL: Record<string, string> = {
  active: 'Active', suspended: 'Suspended', terminated: 'Terminated',
  inactive: 'Inactive', running: 'Running', queued: 'Queued',
  completed: 'Completed', failed: 'Failed',
}

export default function StatusBadge({ status }: { status: string }) {
  const color = DOT_COLOR[status] ?? '#A0AEC0'
  const label = LABEL[status] ?? status
  return (
    <span className="inline-flex items-center gap-1.5">
      <span
        className={`w-2 h-2 rounded-full shrink-0 ${status === 'running' ? 'animate-pulse' : ''}`}
        style={{ backgroundColor: color }}
      />
      <span className="text-sm text-gray-700">{label}</span>
    </span>
  )
}
