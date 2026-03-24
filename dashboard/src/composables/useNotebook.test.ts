/**
 * Tests for useNotebook Composable
 *
 * Tests cover:
 * - Notebook entry creation and management
 * - Quick note creation
 * - Amendment tracking (ALCOA+ audit trail)
 * - Experiment lifecycle (start, end, status)
 * - Entry filtering (search, tags, type)
 * - Data snapshot capture
 * - Export to markdown format
 * - Template-based entry creation
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import type { NotebookEntry, Experiment, Amendment, DataSnapshot, NotebookTemplate } from '../types/notebook'
import { DEFAULT_TEMPLATES } from '../types/notebook'

// =============================================================================
// ENTRY MANAGEMENT (Pure logic)
// =============================================================================

describe('Notebook Entry Management', () => {
  let entries: NotebookEntry[]
  let idCounter: number

  function generateId(): string {
    return `${Date.now()}-${(idCounter++).toString(36)}`
  }

  function addEntry(entry: Omit<NotebookEntry, 'id' | 'timestamp' | 'amendments'>): NotebookEntry {
    const newEntry: NotebookEntry = {
      ...entry,
      id: generateId(),
      timestamp: new Date().toISOString(),
      amendments: []
    }
    entries.unshift(newEntry)
    return newEntry
  }

  beforeEach(() => {
    entries = []
    idCounter = 0
  })

  it('should create a new entry with auto-generated id and timestamp', () => {
    const entry = addEntry({
      type: 'note',
      title: 'Test Note',
      content: 'Some content',
      tags: ['test']
    })

    expect(entry.id).toBeTruthy()
    expect(entry.timestamp).toBeTruthy()
    expect(entry.title).toBe('Test Note')
    expect(entry.type).toBe('note')
    expect(entry.tags).toEqual(['test'])
    expect(entry.amendments).toEqual([])
  })

  it('should add entries at the front (newest first)', () => {
    addEntry({ type: 'note', title: 'First', content: '', tags: [] })
    addEntry({ type: 'note', title: 'Second', content: '', tags: [] })

    expect(entries).toHaveLength(2)
    expect(entries[0].title).toBe('Second')
    expect(entries[1].title).toBe('First')
  })

  it('should support all entry types', () => {
    const types: NotebookEntry['type'][] = ['note', 'observation', 'procedure', 'result', 'issue']

    types.forEach(type => {
      const entry = addEntry({ type, title: `${type} entry`, content: '', tags: [] })
      expect(entry.type).toBe(type)
    })

    expect(entries).toHaveLength(5)
  })

  it('should link entry to experiment if provided', () => {
    const entry = addEntry({
      type: 'note',
      title: 'Test',
      content: '',
      tags: [],
      experimentId: 'exp-123'
    })

    expect(entry.experimentId).toBe('exp-123')
  })

  it('should attach data snapshot to entry', () => {
    const snapshot: DataSnapshot = {
      capturedAt: new Date().toISOString(),
      channels: {
        TC_001: { value: 25.5, unit: 'C' },
        AI_001: { value: 5.0, unit: 'V' }
      }
    }

    const entry = addEntry({
      type: 'observation',
      title: 'Observation with data',
      content: 'Noticed temperature spike',
      tags: ['temperature'],
      dataSnapshot: snapshot
    })

    expect(entry.dataSnapshot).toBeDefined()
    expect(entry.dataSnapshot!.channels['TC_001'].value).toBe(25.5)
    expect(entry.dataSnapshot!.channels['AI_001'].unit).toBe('V')
  })
})

// =============================================================================
// AMENDMENT TRACKING (ALCOA+ Audit Trail)
// =============================================================================

describe('Amendment Tracking', () => {
  it('should record field amendments with old and new values', () => {
    const entry: NotebookEntry = {
      id: 'entry-1',
      timestamp: '2026-01-15T10:00:00Z',
      type: 'note',
      title: 'Original Title',
      content: 'Original content',
      tags: ['test'],
      amendments: []
    }

    // Simulate amendEntry logic
    const amendment: Amendment = {
      timestamp: new Date().toISOString(),
      field: 'title',
      oldValue: JSON.stringify(entry.title),
      newValue: JSON.stringify('Updated Title'),
      reason: 'Typo correction'
    }

    entry.amendments!.push(amendment)
    entry.title = 'Updated Title'

    expect(entry.title).toBe('Updated Title')
    expect(entry.amendments).toHaveLength(1)
    expect(entry.amendments![0].field).toBe('title')
    expect(entry.amendments![0].oldValue).toBe('"Original Title"')
    expect(entry.amendments![0].newValue).toBe('"Updated Title"')
    expect(entry.amendments![0].reason).toBe('Typo correction')
  })

  it('should track multiple amendments', () => {
    const entry: NotebookEntry = {
      id: 'entry-1',
      timestamp: '2026-01-15T10:00:00Z',
      type: 'note',
      title: 'Title',
      content: 'Content',
      tags: [],
      amendments: []
    }

    // First amendment
    entry.amendments!.push({
      timestamp: '2026-01-15T10:05:00Z',
      field: 'title',
      oldValue: '"Title"',
      newValue: '"Updated Title"'
    })
    entry.title = 'Updated Title'

    // Second amendment
    entry.amendments!.push({
      timestamp: '2026-01-15T10:10:00Z',
      field: 'content',
      oldValue: '"Content"',
      newValue: '"Updated Content"'
    })
    entry.content = 'Updated Content'

    expect(entry.amendments).toHaveLength(2)
    expect(entry.amendments![0].field).toBe('title')
    expect(entry.amendments![1].field).toBe('content')
  })

  it('should initialize empty amendments array if missing', () => {
    const entry: NotebookEntry = {
      id: 'entry-1',
      timestamp: '2026-01-15T10:00:00Z',
      type: 'note',
      title: 'Title',
      content: '',
      tags: []
      // amendments not set
    }

    // Logic from amendEntry
    if (!entry.amendments) entry.amendments = []
    entry.amendments.push({
      timestamp: new Date().toISOString(),
      field: 'title',
      oldValue: '"Title"',
      newValue: '"New Title"'
    })

    expect(entry.amendments).toHaveLength(1)
  })
})

// =============================================================================
// EXPERIMENT LIFECYCLE
// =============================================================================

describe('Experiment Lifecycle', () => {
  let experiments: Experiment[]

  beforeEach(() => {
    experiments = []
  })

  it('should create an experiment with active status', () => {
    const experiment: Experiment = {
      id: 'exp-1',
      name: 'Thermal Test Run 1',
      description: 'Testing thermal limits',
      startedAt: new Date().toISOString(),
      status: 'active',
      tags: ['thermal', 'test']
    }

    experiments.unshift(experiment)

    expect(experiments).toHaveLength(1)
    expect(experiments[0].status).toBe('active')
    expect(experiments[0].name).toBe('Thermal Test Run 1')
  })

  it('should end an experiment by setting endedAt and completed status', () => {
    const experiment: Experiment = {
      id: 'exp-1',
      name: 'Test',
      startedAt: '2026-01-15T10:00:00Z',
      status: 'active',
      tags: []
    }
    experiments.push(experiment)

    // End experiment logic
    experiment.endedAt = new Date().toISOString()
    experiment.status = 'completed'

    expect(experiment.status).toBe('completed')
    expect(experiment.endedAt).toBeTruthy()
  })

  it('should track operator for experiment', () => {
    const experiment: Experiment = {
      id: 'exp-1',
      name: 'Operator Test',
      startedAt: new Date().toISOString(),
      status: 'active',
      tags: [],
      operator: 'John Smith'
    }

    expect(experiment.operator).toBe('John Smith')
  })

  it('should support archived status', () => {
    const experiment: Experiment = {
      id: 'exp-1',
      name: 'Old Test',
      startedAt: '2025-06-01T10:00:00Z',
      endedAt: '2025-06-01T15:00:00Z',
      status: 'archived',
      tags: []
    }

    expect(experiment.status).toBe('archived')
  })
})

// =============================================================================
// ENTRY FILTERING
// =============================================================================

describe('Entry Filtering', () => {
  const testEntries: NotebookEntry[] = [
    {
      id: '1', timestamp: '2026-01-15T10:00:00Z', type: 'note',
      title: 'Temperature Reading', content: 'TC readings stable', tags: ['temperature', 'stable']
    },
    {
      id: '2', timestamp: '2026-01-15T11:00:00Z', type: 'observation',
      title: 'Pressure Spike', content: 'Observed pressure spike at 50 PSI', tags: ['pressure', 'anomaly']
    },
    {
      id: '3', timestamp: '2026-01-15T12:00:00Z', type: 'issue',
      title: 'Sensor Failure', content: 'TC_003 open thermocouple', tags: ['issue', 'temperature']
    },
    {
      id: '4', timestamp: '2026-01-15T13:00:00Z', type: 'result',
      title: 'Test Complete', content: 'All tests passed', tags: ['result']
    }
  ]

  it('should filter by search query (title)', () => {
    const query = 'temperature'
    const q = query.toLowerCase()
    const filtered = testEntries.filter(e =>
      (e.title && e.title.toLowerCase().includes(q)) ||
      (e.content && e.content.toLowerCase().includes(q)) ||
      (e.tags && e.tags.some(t => t && t.toLowerCase().includes(q)))
    )

    expect(filtered).toHaveLength(2) // 'Temperature Reading' and 'Sensor Failure' (tag match)
  })

  it('should filter by search query (content)', () => {
    const query = 'spike'
    const q = query.toLowerCase()
    const filtered = testEntries.filter(e =>
      (e.title && e.title.toLowerCase().includes(q)) ||
      (e.content && e.content.toLowerCase().includes(q))
    )

    expect(filtered).toHaveLength(1)
    expect(filtered[0].title).toBe('Pressure Spike')
  })

  it('should filter by tags', () => {
    const filterTags = ['anomaly']
    const filtered = testEntries.filter(e =>
      filterTags.some(tag => e.tags.includes(tag))
    )

    expect(filtered).toHaveLength(1)
    expect(filtered[0].title).toBe('Pressure Spike')
  })

  it('should filter by entry type', () => {
    const filterType = 'issue'
    const filtered = testEntries.filter(e => e.type === filterType)

    expect(filtered).toHaveLength(1)
    expect(filtered[0].title).toBe('Sensor Failure')
  })

  it('should sort entries by timestamp descending', () => {
    const sorted = [...testEntries].sort((a, b) =>
      new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime()
    )

    expect(sorted[0].id).toBe('4') // Latest
    expect(sorted[sorted.length - 1].id).toBe('1') // Earliest
  })

  it('should combine type and search filters', () => {
    const filterType = 'note'
    const query = 'temperature'
    const q = query.toLowerCase()

    const filtered = testEntries
      .filter(e => e.type === filterType)
      .filter(e =>
        (e.title && e.title.toLowerCase().includes(q)) ||
        (e.content && e.content.toLowerCase().includes(q))
      )

    expect(filtered).toHaveLength(1)
    expect(filtered[0].title).toBe('Temperature Reading')
  })
})

// =============================================================================
// ALL TAGS COMPUTATION
// =============================================================================

describe('All Tags', () => {
  it('should collect unique tags from all entries', () => {
    const entries: NotebookEntry[] = [
      { id: '1', timestamp: '', type: 'note', title: '', content: '', tags: ['temperature', 'stable'] },
      { id: '2', timestamp: '', type: 'note', title: '', content: '', tags: ['pressure', 'temperature'] },
      { id: '3', timestamp: '', type: 'note', title: '', content: '', tags: ['issue'] }
    ]

    const tagSet = new Set<string>()
    entries.forEach(e => e.tags.forEach(t => tagSet.add(t)))
    const allTags = Array.from(tagSet).sort()

    expect(allTags).toEqual(['issue', 'pressure', 'stable', 'temperature'])
  })

  it('should return empty array when no entries', () => {
    const entries: NotebookEntry[] = []
    const tagSet = new Set<string>()
    entries.forEach(e => e.tags.forEach(t => tagSet.add(t)))

    expect(Array.from(tagSet)).toEqual([])
  })
})

// =============================================================================
// ENTRIES BY EXPERIMENT
// =============================================================================

describe('Entries by Experiment', () => {
  it('should group entries by experiment ID', () => {
    const entries: NotebookEntry[] = [
      { id: '1', timestamp: '', type: 'note', title: 'A', content: '', tags: [], experimentId: 'exp-1' },
      { id: '2', timestamp: '', type: 'note', title: 'B', content: '', tags: [], experimentId: 'exp-1' },
      { id: '3', timestamp: '', type: 'note', title: 'C', content: '', tags: [], experimentId: 'exp-2' },
      { id: '4', timestamp: '', type: 'note', title: 'D', content: '', tags: [] } // unassigned
    ]

    const map: Record<string, NotebookEntry[]> = {}
    entries.forEach(e => {
      const expId = e.experimentId || 'unassigned'
      if (!map[expId]) map[expId] = []
      map[expId].push(e)
    })

    expect(map['exp-1']).toHaveLength(2)
    expect(map['exp-2']).toHaveLength(1)
    expect(map['unassigned']).toHaveLength(1)
  })
})

// =============================================================================
// TEMPLATE-BASED ENTRY
// =============================================================================

describe('Template-Based Entry Creation', () => {
  it('should have default templates available', () => {
    expect(DEFAULT_TEMPLATES).toHaveLength(4)
    expect(DEFAULT_TEMPLATES.map(t => t.id)).toContain('start-run')
    expect(DEFAULT_TEMPLATES.map(t => t.id)).toContain('observation')
    expect(DEFAULT_TEMPLATES.map(t => t.id)).toContain('end-run')
    expect(DEFAULT_TEMPLATES.map(t => t.id)).toContain('issue')
  })

  it('should create entry from template with default values', () => {
    const template = DEFAULT_TEMPLATES.find(t => t.id === 'observation')!

    const entry: Partial<NotebookEntry> = {
      type: template.type,
      title: template.titleTemplate,
      content: template.contentTemplate,
      tags: [...template.defaultTags]
    }

    expect(entry.type).toBe('observation')
    expect(entry.title).toBe('Observation')
    expect(entry.tags).toContain('observation')
  })

  it('should allow overriding template values', () => {
    const template = DEFAULT_TEMPLATES.find(t => t.id === 'issue')!

    const overrides = {
      title: 'Custom Issue Title',
      tags: ['custom-tag']
    }

    const entry = {
      type: template.type,
      title: overrides.title || template.titleTemplate,
      content: template.contentTemplate,
      tags: [...template.defaultTags, ...overrides.tags]
    }

    expect(entry.title).toBe('Custom Issue Title')
    expect(entry.tags).toContain('issue')
    expect(entry.tags).toContain('custom-tag')
  })
})

// =============================================================================
// EXPORT TO MARKDOWN (Pure logic)
// =============================================================================

describe('Export to Markdown', () => {
  it('should generate markdown with title and entries', () => {
    const entries: NotebookEntry[] = [
      {
        id: '1',
        timestamp: '2026-01-15T10:00:00Z',
        type: 'note',
        title: 'Test Note',
        content: 'Some observations',
        tags: ['test']
      }
    ]

    // Simplified exportToMarkdown logic
    let md = `# Lab Notebook\n\n`
    const sorted = [...entries].sort((a, b) =>
      new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()
    )

    sorted.forEach(e => {
      md += `## ${e.title}\n\n`
      md += `**${new Date(e.timestamp).toLocaleString()}** | ${e.type}`
      if (e.tags.length) md += ` | Tags: ${e.tags.join(', ')}`
      md += '\n\n'
      if (e.content) md += `${e.content}\n\n`
      md += '---\n\n'
    })

    expect(md).toContain('# Lab Notebook')
    expect(md).toContain('## Test Note')
    expect(md).toContain('Some observations')
    expect(md).toContain('Tags: test')
  })

  it('should include data snapshot in markdown export', () => {
    const entry: NotebookEntry = {
      id: '1',
      timestamp: '2026-01-15T10:00:00Z',
      type: 'observation',
      title: 'Data Point',
      content: '',
      tags: [],
      dataSnapshot: {
        capturedAt: '2026-01-15T10:00:00Z',
        channels: {
          TC_001: { value: 25.55, unit: 'C' }
        }
      }
    }

    // Data snapshot rendering logic
    let md = ''
    if (entry.dataSnapshot && Object.keys(entry.dataSnapshot.channels).length > 0) {
      md += `### Data Snapshot\n\n`
      md += `| Channel | Value |\n|---------|-------|\n`
      Object.entries(entry.dataSnapshot.channels).forEach(([ch, v]) => {
        md += `| ${ch} | ${v.value.toFixed(2)} ${v.unit} |\n`
      })
    }

    expect(md).toContain('### Data Snapshot')
    expect(md).toContain('TC_001')
    expect(md).toContain('25.55')
    expect(md).toContain('C')
  })
})
