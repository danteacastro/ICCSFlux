import { ref, computed, watch } from 'vue'
import { useDashboardStore } from '../stores/dashboard'
import { useMqtt } from './useMqtt'
import type {
  NotebookEntry,
  Experiment,
  DataSnapshot,
  Amendment,
  NotebookTemplate
} from '../types/notebook'
import { DEFAULT_TEMPLATES, NOTEBOOK_STORAGE_KEY, EXPERIMENTS_STORAGE_KEY } from '../types/notebook'

// Singleton state
const entries = ref<NotebookEntry[]>([])
const experiments = ref<Experiment[]>([])
const templates = ref<NotebookTemplate[]>([...DEFAULT_TEMPLATES])
const activeExperimentId = ref<string | null>(null)
const searchQuery = ref('')
const filterTags = ref<string[]>([])
const filterType = ref<NotebookEntry['type'] | 'all'>('all')

let initialized = false

export function useNotebook() {
  const store = useDashboardStore()

  // ============================================
  // Computed
  // ============================================

  const activeExperiment = computed(() =>
    experiments.value.find(e => e.id === activeExperimentId.value) || null
  )

  const filteredEntries = computed(() => {
    let result = [...entries.value]

    // Filter by search query
    if (searchQuery.value) {
      const q = searchQuery.value.toLowerCase()
      result = result.filter(e =>
        e.title.toLowerCase().includes(q) ||
        e.content.toLowerCase().includes(q) ||
        e.tags.some(t => t.toLowerCase().includes(q))
      )
    }

    // Filter by tags
    if (filterTags.value.length > 0) {
      result = result.filter(e =>
        filterTags.value.some(tag => e.tags.includes(tag))
      )
    }

    // Filter by type
    if (filterType.value !== 'all') {
      result = result.filter(e => e.type === filterType.value)
    }

    // Sort by timestamp descending (newest first)
    return result.sort((a, b) =>
      new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime()
    )
  })

  const allTags = computed(() => {
    const tagSet = new Set<string>()
    entries.value.forEach(e => e.tags.forEach(t => tagSet.add(t)))
    return Array.from(tagSet).sort()
  })

  const entriesByExperiment = computed(() => {
    const map: Record<string, NotebookEntry[]> = {}
    entries.value.forEach(e => {
      const expId = e.experimentId || 'unassigned'
      if (!map[expId]) map[expId] = []
      map[expId].push(e)
    })
    return map
  })

  // ============================================
  // Entry Actions
  // ============================================

  function generateId(): string {
    return `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`
  }

  function captureDataSnapshot(): DataSnapshot {
    const channels: DataSnapshot['channels'] = {}
    Object.entries(store.values).forEach(([channel, data]) => {
      if (data && typeof data.value === 'number') {
        const config = store.channels[channel]
        channels[channel] = {
          value: data.value,
          unit: config?.unit || ''
        }
      }
    })
    return {
      capturedAt: new Date().toISOString(),
      channels
    }
  }

  function addEntry(entry: Omit<NotebookEntry, 'id' | 'timestamp' | 'amendments'>): NotebookEntry {
    const newEntry: NotebookEntry = {
      ...entry,
      id: generateId(),
      timestamp: new Date().toISOString(),
      amendments: []
    }

    // Auto-link to active experiment if none specified
    if (!newEntry.experimentId && activeExperimentId.value) {
      newEntry.experimentId = activeExperimentId.value
    }

    entries.value.unshift(newEntry)
    saveEntries()
    return newEntry
  }

  function amendEntry(id: string, field: keyof NotebookEntry, newValue: any, reason?: string) {
    const entry = entries.value.find(e => e.id === id)
    if (!entry) return

    const amendment: Amendment = {
      timestamp: new Date().toISOString(),
      field,
      oldValue: JSON.stringify(entry[field]),
      newValue: JSON.stringify(newValue),
      reason
    }

    if (!entry.amendments) entry.amendments = []
    entry.amendments.push(amendment)
    Object.assign(entry, { [field]: newValue })

    saveEntries()
  }

  function addQuickNote(content: string, tags: string[] = []) {
    return addEntry({
      type: 'note',
      title: `Note - ${new Date().toLocaleTimeString()}`,
      content,
      tags,
      dataSnapshot: captureDataSnapshot()
    })
  }

  function addFromTemplate(template: NotebookTemplate, overrides: Partial<NotebookEntry> = {}) {
    return addEntry({
      type: template.type,
      title: overrides.title || template.titleTemplate,
      content: overrides.content || template.contentTemplate,
      tags: [...template.defaultTags, ...(overrides.tags || [])],
      dataSnapshot: captureDataSnapshot(),
      ...overrides
    })
  }

  // ============================================
  // Experiment Actions
  // ============================================

  function startExperiment(name: string, description?: string): Experiment {
    const experiment: Experiment = {
      id: generateId(),
      name,
      description,
      startedAt: new Date().toISOString(),
      status: 'active',
      tags: []
    }

    experiments.value.unshift(experiment)
    activeExperimentId.value = experiment.id
    saveExperiments()

    // Auto-create start entry
    addEntry({
      type: 'procedure',
      title: `Started: ${name}`,
      content: description || '',
      tags: ['start'],
      experimentId: experiment.id,
      dataSnapshot: captureDataSnapshot()
    })

    return experiment
  }

  function endExperiment(id: string, summary?: string) {
    const experiment = experiments.value.find(e => e.id === id)
    if (!experiment) return

    experiment.endedAt = new Date().toISOString()
    experiment.status = 'completed'

    if (activeExperimentId.value === id) {
      activeExperimentId.value = null
    }

    saveExperiments()

    // Auto-create end entry
    addEntry({
      type: 'result',
      title: `Completed: ${experiment.name}`,
      content: summary || '',
      tags: ['end', 'result'],
      experimentId: id,
      dataSnapshot: captureDataSnapshot()
    })
  }

  function setActiveExperiment(id: string | null) {
    activeExperimentId.value = id
  }

  // ============================================
  // Search & Filter
  // ============================================

  function setSearchQuery(query: string) {
    searchQuery.value = query
  }

  function toggleFilterTag(tag: string) {
    const idx = filterTags.value.indexOf(tag)
    if (idx >= 0) {
      filterTags.value.splice(idx, 1)
    } else {
      filterTags.value.push(tag)
    }
  }

  function clearFilters() {
    searchQuery.value = ''
    filterTags.value = []
    filterType.value = 'all'
  }

  // ============================================
  // Export
  // ============================================

  function exportToPdf() {
    // Simple print-to-PDF approach
    const printWindow = window.open('', '_blank')
    if (!printWindow) return

    const html = `
      <!DOCTYPE html>
      <html>
      <head>
        <title>Lab Notebook Export - ${new Date().toLocaleDateString()}</title>
        <style>
          body { font-family: system-ui, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; }
          .entry { border-bottom: 1px solid #ccc; padding: 16px 0; }
          .entry-header { display: flex; justify-content: space-between; margin-bottom: 8px; }
          .entry-title { font-weight: bold; font-size: 1.1em; }
          .entry-time { color: #666; font-size: 0.9em; }
          .entry-tags { margin-top: 8px; }
          .tag { background: #e0e0e0; padding: 2px 8px; border-radius: 4px; font-size: 0.8em; margin-right: 4px; }
          .entry-content { white-space: pre-wrap; margin-top: 8px; }
          .data-snapshot { background: #f5f5f5; padding: 8px; margin-top: 8px; font-size: 0.85em; }
          h1 { border-bottom: 2px solid #333; padding-bottom: 8px; }
        </style>
      </head>
      <body>
        <h1>Lab Notebook</h1>
        <p>Exported: ${new Date().toLocaleString()}</p>
        ${filteredEntries.value.map(e => `
          <div class="entry">
            <div class="entry-header">
              <span class="entry-title">${e.title}</span>
              <span class="entry-time">${new Date(e.timestamp).toLocaleString()}</span>
            </div>
            <div class="entry-content">${e.content}</div>
            ${e.tags.length ? `<div class="entry-tags">${e.tags.map(t => `<span class="tag">${t}</span>`).join('')}</div>` : ''}
            ${e.dataSnapshot ? `
              <div class="data-snapshot">
                <strong>Data Snapshot:</strong><br>
                ${Object.entries(e.dataSnapshot.channels).map(([ch, v]) => `${ch}: ${v.value} ${v.unit}`).join(', ')}
              </div>
            ` : ''}
          </div>
        `).join('')}
      </body>
      </html>
    `

    printWindow.document.write(html)
    printWindow.document.close()
    printWindow.print()
  }

  function exportToMarkdown(experimentId?: string | null) {
    const entriesToExport = experimentId === undefined
      ? entries.value
      : entries.value.filter(e => (e.experimentId || null) === experimentId)

    const exp = experimentId ? experiments.value.find(e => e.id === experimentId) : null
    const title = exp?.name || 'Lab Notebook'

    let md = `# ${title}\n\n`
    md += `**Exported:** ${new Date().toLocaleString()}\n\n`

    if (exp) {
      md += `**Started:** ${new Date(exp.startedAt).toLocaleString()}\n`
      if (exp.endedAt) md += `**Ended:** ${new Date(exp.endedAt).toLocaleString()}\n`
      if (exp.description) md += `\n${exp.description}\n`
      md += '\n---\n\n'
    }

    const sorted = [...entriesToExport].sort((a, b) =>
      new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()
    )

    sorted.forEach(e => {
      md += `## ${e.title}\n\n`
      md += `**${new Date(e.timestamp).toLocaleString()}** | ${e.type}`
      if (e.tags.length) md += ` | Tags: ${e.tags.join(', ')}`
      md += '\n\n'

      if (e.content) md += `${e.content}\n\n`

      if (e.dataSnapshot && Object.keys(e.dataSnapshot.channels).length > 0) {
        md += `### Data Snapshot\n\n`
        md += `| Channel | Value |\n|---------|-------|\n`
        Object.entries(e.dataSnapshot.channels).forEach(([ch, v]) => {
          md += `| ${ch} | ${v.value.toFixed(2)} ${v.unit} |\n`
        })
        md += '\n'
      }

      md += '---\n\n'
    })

    downloadFile(`${title.replace(/[^a-z0-9]/gi, '_')}_${new Date().toISOString().split('T')[0]}.md`, md, 'text/markdown')
  }

  function exportToText(experimentId?: string | null) {
    const entriesToExport = experimentId === undefined
      ? entries.value
      : entries.value.filter(e => (e.experimentId || null) === experimentId)

    const exp = experimentId ? experiments.value.find(e => e.id === experimentId) : null
    const title = exp?.name || 'Lab Notebook'

    let txt = `${title.toUpperCase()}\n${'='.repeat(title.length)}\n\n`
    txt += `Exported: ${new Date().toLocaleString()}\n\n`

    if (exp) {
      txt += `Started: ${new Date(exp.startedAt).toLocaleString()}\n`
      if (exp.endedAt) txt += `Ended: ${new Date(exp.endedAt).toLocaleString()}\n`
      if (exp.description) txt += `\n${exp.description}\n`
      txt += '\n' + '-'.repeat(60) + '\n\n'
    }

    const sorted = [...entriesToExport].sort((a, b) =>
      new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()
    )

    sorted.forEach(e => {
      txt += `${e.title}\n`
      txt += `${new Date(e.timestamp).toLocaleString()} | ${e.type}`
      if (e.tags.length) txt += ` | Tags: ${e.tags.join(', ')}`
      txt += '\n\n'

      if (e.content) txt += `${e.content}\n\n`

      if (e.dataSnapshot && Object.keys(e.dataSnapshot.channels).length > 0) {
        txt += `Data Snapshot:\n`
        Object.entries(e.dataSnapshot.channels).forEach(([ch, v]) => {
          txt += `  ${ch}: ${v.value.toFixed(2)} ${v.unit}\n`
        })
        txt += '\n'
      }

      txt += '-'.repeat(60) + '\n\n'
    })

    downloadFile(`${title.replace(/[^a-z0-9]/gi, '_')}_${new Date().toISOString().split('T')[0]}.txt`, txt, 'text/plain')
  }

  function downloadFile(filename: string, content: string, mimeType: string) {
    const blob = new Blob([content], { type: mimeType })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }

  // ============================================
  // Persistence (localStorage + MQTT file sync)
  // ============================================

  const mqtt = useMqtt()
  let saveTimeout: number | null = null

  function saveEntries() {
    // Save to localStorage immediately
    try {
      localStorage.setItem(NOTEBOOK_STORAGE_KEY, JSON.stringify(entries.value))
    } catch (e) {
      console.error('Failed to save notebook entries:', e)
    }
    // Debounce file save
    scheduleSaveToFile()
  }

  function saveExperiments() {
    // Save to localStorage immediately
    try {
      localStorage.setItem(EXPERIMENTS_STORAGE_KEY, JSON.stringify(experiments.value))
    } catch (e) {
      console.error('Failed to save experiments:', e)
    }
    // Debounce file save
    scheduleSaveToFile()
  }

  function scheduleSaveToFile() {
    if (saveTimeout) {
      clearTimeout(saveTimeout)
    }
    // Debounce: save to file after 2 seconds of inactivity
    saveTimeout = window.setTimeout(() => {
      saveToFile()
      saveTimeout = null
    }, 2000)
  }

  function saveToFile() {
    if (!mqtt.connected.value) {
      console.warn('MQTT not connected, skipping file save')
      return
    }

    const notebookData = {
      version: '1.0',
      savedAt: new Date().toISOString(),
      entries: entries.value,
      experiments: experiments.value
    }

    mqtt.sendCommand('notebook/save', {
      filename: 'notebook.json',
      data: notebookData
    })
  }

  function loadFromStorage() {
    // First load from localStorage (fast)
    try {
      const storedEntries = localStorage.getItem(NOTEBOOK_STORAGE_KEY)
      if (storedEntries) {
        entries.value = JSON.parse(storedEntries)
      }

      const storedExperiments = localStorage.getItem(EXPERIMENTS_STORAGE_KEY)
      if (storedExperiments) {
        experiments.value = JSON.parse(storedExperiments)
        // Re-activate any active experiment
        const active = experiments.value.find(e => e.status === 'active')
        if (active) activeExperimentId.value = active.id
      }
    } catch (e) {
      console.error('Failed to load notebook data:', e)
    }
  }

  function loadFromFile() {
    if (!mqtt.connected.value) return

    mqtt.sendCommand('notebook/load', { filename: 'notebook.json' })
  }

  function handleNotebookLoaded(payload: any) {
    if (!payload.success || !payload.data) return

    const data = payload.data
    if (data.entries && Array.isArray(data.entries)) {
      // Merge: file data takes precedence for newer entries
      const fileEntriesMap = new Map<string, NotebookEntry>(
        data.entries.map((e: NotebookEntry) => [e.id, e])
      )
      const localEntriesMap = new Map<string, NotebookEntry>(
        entries.value.map(e => [e.id, e])
      )

      // Combine both, preferring file version for conflicts
      const mergedEntries = new Map<string, NotebookEntry>([...localEntriesMap, ...fileEntriesMap])
      entries.value = Array.from(mergedEntries.values())

      localStorage.setItem(NOTEBOOK_STORAGE_KEY, JSON.stringify(entries.value))
    }

    if (data.experiments && Array.isArray(data.experiments)) {
      const fileExpsMap = new Map<string, Experiment>(
        data.experiments.map((e: Experiment) => [e.id, e])
      )
      const localExpsMap = new Map<string, Experiment>(
        experiments.value.map(e => [e.id, e])
      )

      const mergedExps = new Map<string, Experiment>([...localExpsMap, ...fileExpsMap])
      experiments.value = Array.from(mergedExps.values())

      localStorage.setItem(EXPERIMENTS_STORAGE_KEY, JSON.stringify(experiments.value))

      // Re-activate any active experiment
      const active = experiments.value.find(e => e.status === 'active')
      if (active) activeExperimentId.value = active.id
    }
  }

  // ============================================
  // Initialize
  // ============================================

  function initialize() {
    if (initialized) return

    // Load from localStorage first (instant)
    loadFromStorage()

    // Subscribe to notebook load response
    mqtt.subscribe('nisystem/notebook/loaded', handleNotebookLoaded)

    // When MQTT connects, try to load from file
    watch(() => mqtt.connected.value, (connected) => {
      if (connected) {
        // Small delay to let other subscriptions settle
        setTimeout(loadFromFile, 500)
      }
    }, { immediate: true })

    initialized = true
  }

  initialize()

  // ============================================
  // Return
  // ============================================

  return {
    // State
    entries,
    experiments,
    templates,
    activeExperimentId,
    searchQuery,
    filterTags,
    filterType,

    // Computed
    activeExperiment,
    filteredEntries,
    allTags,
    entriesByExperiment,

    // Entry actions
    addEntry,
    amendEntry,
    addQuickNote,
    addFromTemplate,
    captureDataSnapshot,

    // Experiment actions
    startExperiment,
    endExperiment,
    setActiveExperiment,

    // Search & filter
    setSearchQuery,
    toggleFilterTag,
    clearFilters,

    // Export
    exportToPdf,
    exportToMarkdown,
    exportToText
  }
}
