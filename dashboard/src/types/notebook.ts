// Lab Notebook Types - Simple, append-only scientific notebook

export interface NotebookEntry {
  id: string
  timestamp: string           // ISO string, immutable once created
  type: 'note' | 'observation' | 'procedure' | 'result' | 'issue'
  title: string
  content: string             // Markdown supported
  tags: string[]
  operator?: string
  experimentId?: string       // Link to experiment
  dataSnapshot?: DataSnapshot // Channel values at time of entry
  attachments?: Attachment[]
  // Audit trail
  amendments?: Amendment[]    // Edits are tracked, not replaced
}

export interface DataSnapshot {
  capturedAt: string
  channels: Record<string, {
    value: number
    unit: string
  }>
}

export interface Attachment {
  id: string
  name: string
  type: 'image' | 'file' | 'chart'
  data?: string              // Base64 for images, or reference
}

export interface Amendment {
  timestamp: string
  field: string
  oldValue: string
  newValue: string
  reason?: string
}

export interface Experiment {
  id: string
  name: string
  description?: string
  startedAt: string
  endedAt?: string
  status: 'active' | 'completed' | 'archived'
  tags: string[]
  operator?: string
}

export interface NotebookTemplate {
  id: string
  name: string
  type: NotebookEntry['type']
  titleTemplate: string
  contentTemplate: string
  defaultTags: string[]
}

// Default templates
export const DEFAULT_TEMPLATES: NotebookTemplate[] = [
  {
    id: 'start-run',
    name: 'Start Experiment',
    type: 'procedure',
    titleTemplate: 'Started: {experiment}',
    contentTemplate: '## Objective\n\n## Initial Conditions\n\n## Notes\n',
    defaultTags: ['start']
  },
  {
    id: 'observation',
    name: 'Observation',
    type: 'observation',
    titleTemplate: 'Observation',
    contentTemplate: '## Observed\n\n## Interpretation\n',
    defaultTags: ['observation']
  },
  {
    id: 'end-run',
    name: 'End Experiment',
    type: 'result',
    titleTemplate: 'Completed: {experiment}',
    contentTemplate: '## Summary\n\n## Results\n\n## Next Steps\n',
    defaultTags: ['end', 'result']
  },
  {
    id: 'issue',
    name: 'Issue/Anomaly',
    type: 'issue',
    titleTemplate: 'Issue: ',
    contentTemplate: '## Description\n\n## Impact\n\n## Resolution\n',
    defaultTags: ['issue']
  }
]

export const NOTEBOOK_STORAGE_KEY = 'nisystem_notebook'
export const EXPERIMENTS_STORAGE_KEY = 'nisystem_experiments'
// Deleted entries / experiments are kept in archive for ALCOA+ traceability.
export const NOTEBOOK_ARCHIVE_KEY = 'nisystem_notebook_archive'
export const EXPERIMENTS_ARCHIVE_KEY = 'nisystem_experiments_archive'
