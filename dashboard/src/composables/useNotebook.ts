import { ref, computed, watch } from 'vue'
import { useDashboardStore } from '../stores/dashboard'
import { useMqtt } from './useMqtt'
import { useAuth } from './useAuth'
import type {
  NotebookEntry,
  Experiment,
  DataSnapshot,
  Amendment,
  NotebookTemplate
} from '../types/notebook'
import {
  DEFAULT_TEMPLATES,
  NOTEBOOK_STORAGE_KEY,
  EXPERIMENTS_STORAGE_KEY,
  NOTEBOOK_ARCHIVE_KEY,
  EXPERIMENTS_ARCHIVE_KEY,
} from '../types/notebook'

// Singleton state — persists across component mount/unmount.
const entries = ref<NotebookEntry[]>([])
const experiments = ref<Experiment[]>([])
const templates = ref<NotebookTemplate[]>([...DEFAULT_TEMPLATES])
const activeExperimentId = ref<string | null>(null)
const searchQuery = ref('')
const filterTags = ref<string[]>([])
const filterType = ref<NotebookEntry['type'] | 'all'>('all')

// Surface persistence state to the UI so failures aren't silent.
// Previously localStorage quota errors and MQTT save failures only logged
// to console, so Mike thought his notes saved when they didn't.
const lastSaveError = ref<string | null>(null)
const savePending = ref(false)
const lastSavedAt = ref<string | null>(null)

let initialized = false
// Module-level so it survives individual component unmounts. Per-component
// cleanup was wrong here: this is a singleton and the timer must outlive
// any one consumer.
let saveTimeout: number | null = null
let saveAckTimeout: number | null = null
let listenersRegistered = false
// Monotonic counter to defeat same-millisecond ID collisions when crypto
// randomUUID isn't available (older browsers / non-secure contexts).
let idCounter = 0

// Escape HTML so untrusted user input (note titles, content, tags, channel
// names) cannot inject script tags or onerror handlers in the PDF export.
function escapeHtml(s: string): string {
  if (s == null) return ''
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

// Escape pipe + backslash + newlines in markdown table cells so a channel
// name or unit containing `|` doesn't break the rendered table.
function escapeMarkdownCell(s: string): string {
  if (s == null) return ''
  return String(s)
    .replace(/\\/g, '\\\\')
    .replace(/\|/g, '\\|')
    .replace(/\r?\n/g, ' ')
}

export function useNotebook() {
  const store = useDashboardStore()
  const auth = useAuth()

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
        (e.title && e.title.toLowerCase().includes(q)) ||
        (e.content && e.content.toLowerCase().includes(q)) ||
        (e.tags && e.tags.some(t => t && t.toLowerCase().includes(q)))
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
    // crypto.randomUUID() when available (collision-impossible), with a
    // fallback that includes a counter to defeat same-millisecond collisions
    // even when Math.random gives the same value.
    if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
      return crypto.randomUUID()
    }
    idCounter++
    return `${Date.now()}-${idCounter}-${Math.random().toString(36).slice(2, 11)}`
  }

  function captureDataSnapshot(): DataSnapshot {
    const channels: DataSnapshot['channels'] = {}
    Object.entries(store.values).forEach(([channel, data]) => {
      // Only include real numeric values. Number.isFinite excludes NaN and
      // ±Infinity; previously NaN slipped through and exported as "NaN units"
      // in markdown/PDF, polluting Mike's audit log.
      if (data && Number.isFinite(data.value)) {
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
      operator: entry.operator || auth.currentUser.value?.displayName || auth.currentUser.value?.username || undefined,
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
    // Use the first non-empty line of content as the title so search-by-title
    // is meaningful (previously every quick note had `Note - HH:MM:SS`,
    // making search useless when Mike accumulates dozens of them).
    const firstLine = (content || '').split(/\r?\n/).map(s => s.trim()).find(s => s.length > 0) || ''
    const title = firstLine
      ? (firstLine.length > 60 ? firstLine.slice(0, 57) + '…' : firstLine)
      : `Note - ${new Date().toLocaleTimeString()}`
    return addEntry({
      type: 'note',
      title,
      content,
      tags,
      dataSnapshot: captureDataSnapshot()
    })
  }

  // Replace placeholders like {experiment} in template strings.
  function applyTemplatePlaceholders(s: string): string {
    if (!s) return s
    const expName = activeExperiment.value?.name || ''
    const operator = auth.currentUser.value?.displayName || auth.currentUser.value?.username || ''
    return s
      .replace(/\{experiment\}/g, expName)
      .replace(/\{operator\}/g, operator)
      .replace(/\{date\}/g, new Date().toLocaleDateString())
      .replace(/\{time\}/g, new Date().toLocaleTimeString())
  }

  function addFromTemplate(template: NotebookTemplate, overrides: Partial<NotebookEntry> = {}) {
    return addEntry({
      type: template.type,
      title: overrides.title || applyTemplatePlaceholders(template.titleTemplate),
      content: overrides.content || applyTemplatePlaceholders(template.contentTemplate),
      tags: [...template.defaultTags, ...(overrides.tags || [])],
      dataSnapshot: captureDataSnapshot(),
      ...overrides
    })
  }

  // Soft-delete an entry. We append a final "deleted" amendment to the
  // archive entry so the audit trail isn't lost, but the entry itself is
  // removed from active state. ALCOA+ compliance: the amendment record on
  // the deleted entry preserves who/when/why before it leaves the live list.
  // A separate `deletedEntries` archive keeps the full record in case it's
  // ever needed for a regulatory retrieval.
  function deleteEntry(id: string, reason: string): boolean {
    const idx = entries.value.findIndex(e => e.id === id)
    if (idx < 0) return false
    const entry = entries.value[idx]
    const tombstone: Amendment = {
      timestamp: new Date().toISOString(),
      field: '__deleted__',
      oldValue: JSON.stringify({ title: entry.title, content: entry.content }),
      newValue: '',
      reason: reason || 'Deleted',
    }
    if (!entry.amendments) entry.amendments = []
    entry.amendments.push(tombstone)
    archiveDeletedEntry(entry)
    entries.value.splice(idx, 1)
    saveEntries()
    return true
  }

  function deleteExperiment(id: string, reason: string): boolean {
    const idx = experiments.value.findIndex(e => e.id === id)
    if (idx < 0) return false
    const exp = experiments.value[idx]
    archiveDeletedExperiment({ ...exp, _deletedAt: new Date().toISOString(), _deleteReason: reason } as any)
    experiments.value.splice(idx, 1)
    if (activeExperimentId.value === id) {
      activeExperimentId.value = null
    }
    saveExperiments()
    return true
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
      operator: auth.currentUser.value?.displayName || auth.currentUser.value?.username || undefined,
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

  function buildExportHtml(): string {
    // ALL user-derived strings (title, content, tags, channel names, units)
    // go through escapeHtml so a note containing `<script>` or
    // `<img onerror>` cannot execute when the export is opened in a
    // browser. Previously these were inserted raw — a stored-XSS hole.
    return `<!DOCTYPE html>
      <html>
      <head>
        <title>Lab Notebook Export - ${escapeHtml(new Date().toLocaleDateString())}</title>
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
        <p>Exported: ${escapeHtml(new Date().toLocaleString())}</p>
        ${filteredEntries.value.map(e => `
          <div class="entry">
            <div class="entry-header">
              <span class="entry-title">${escapeHtml(e.title)}</span>
              <span class="entry-time">${escapeHtml(new Date(e.timestamp).toLocaleString())}</span>
            </div>
            <div class="entry-content">${escapeHtml(e.content)}</div>
            ${e.tags.length ? `<div class="entry-tags">${e.tags.map(t => `<span class="tag">${escapeHtml(t)}</span>`).join('')}</div>` : ''}
            ${e.dataSnapshot ? `
              <div class="data-snapshot">
                <strong>Data Snapshot:</strong><br>
                ${Object.entries(e.dataSnapshot.channels).map(([ch, v]) =>
                  `${escapeHtml(ch)}: ${escapeHtml(String(v.value))} ${escapeHtml(v.unit)}`
                ).join(', ')}
              </div>
            ` : ''}
          </div>
        `).join('')}
      </body>
      </html>`
  }

  function exportToPdf() {
    // Flush pending edits before exporting so the file matches what's on screen.
    flushPendingSave()
    const html = buildExportHtml()
    let printWindow: Window | null = null
    try {
      printWindow = window.open('', '_blank')
    } catch (e) {
      printWindow = null
    }
    if (!printWindow) {
      // Pop-up blocked. Fall back to downloading the HTML file so the user
      // can open it manually and print from there. Previously this just
      // silently failed — Mike clicked Export and nothing happened.
      const filename = `lab_notebook_${new Date().toISOString().split('T')[0]}.html`
      downloadFile(filename, html, 'text/html')
      lastSaveError.value = 'Pop-up blocked — downloaded HTML file instead. Open it and use Print to PDF.'
      return
    }
    try {
      printWindow.document.write(html)
      printWindow.document.close()
      printWindow.print()
    } catch (e: any) {
      lastSaveError.value = `PDF export failed: ${e?.message || e}`
      try { printWindow.close() } catch { /* ignore */ }
    }
  }

  function exportToMarkdown(experimentId?: string | null) {
    flushPendingSave()
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
          // Escape pipes so a channel name like "Pump|Tank" or a unit
          // containing `|` doesn't break the rendered table.
          const cell = `${v.value.toFixed(2)} ${v.unit}`
          md += `| ${escapeMarkdownCell(ch)} | ${escapeMarkdownCell(cell)} |\n`
        })
        md += '\n'
      }

      md += '---\n\n'
    })

    downloadFile(`${title.replace(/[^a-z0-9]/gi, '_')}_${new Date().toISOString().split('T')[0]}.md`, md, 'text/markdown')
  }

  function exportToText(experimentId?: string | null) {
    flushPendingSave()
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

  function saveEntries() {
    // Save to localStorage immediately. Surface the failure to the UI so
    // Mike sees a banner instead of silently losing data when quota fills.
    try {
      localStorage.setItem(NOTEBOOK_STORAGE_KEY, JSON.stringify(entries.value))
      lastSaveError.value = null
    } catch (e: any) {
      lastSaveError.value = `Local save failed: ${e?.message || e}`
      console.error('Failed to save notebook entries:', e)
    }
    // Debounce file save
    scheduleSaveToFile()
  }

  function saveExperiments() {
    try {
      localStorage.setItem(EXPERIMENTS_STORAGE_KEY, JSON.stringify(experiments.value))
      lastSaveError.value = null
    } catch (e: any) {
      lastSaveError.value = `Local save failed: ${e?.message || e}`
      console.error('Failed to save experiments:', e)
    }
    scheduleSaveToFile()
  }

  // Append-only archive for soft-deleted entries / experiments. We never
  // overwrite this; it grows monotonically and is the only way to retrieve
  // a deleted record. Failures here are non-fatal but surfaced.
  function archiveDeletedEntry(entry: NotebookEntry) {
    try {
      const raw = localStorage.getItem(NOTEBOOK_ARCHIVE_KEY)
      const arr: NotebookEntry[] = raw ? JSON.parse(raw) : []
      arr.push(entry)
      localStorage.setItem(NOTEBOOK_ARCHIVE_KEY, JSON.stringify(arr))
    } catch (e: any) {
      lastSaveError.value = `Archive save failed: ${e?.message || e}`
      console.error('Failed to archive deleted entry:', e)
    }
  }

  function archiveDeletedExperiment(exp: Experiment) {
    try {
      const raw = localStorage.getItem(EXPERIMENTS_ARCHIVE_KEY)
      const arr: Experiment[] = raw ? JSON.parse(raw) : []
      arr.push(exp)
      localStorage.setItem(EXPERIMENTS_ARCHIVE_KEY, JSON.stringify(arr))
    } catch (e: any) {
      lastSaveError.value = `Archive save failed: ${e?.message || e}`
      console.error('Failed to archive deleted experiment:', e)
    }
  }

  function scheduleSaveToFile() {
    if (saveTimeout) {
      clearTimeout(saveTimeout)
    }
    savePending.value = true
    // Debounce: save to file after 2 seconds of inactivity
    saveTimeout = window.setTimeout(() => {
      saveToFile()
      saveTimeout = null
    }, 2000)
  }

  // Force-flush any pending save synchronously. Called on tab close, tab
  // hide, and before manual export. Closes the 2s window where Mike could
  // type a note, hit Cmd+W, and lose the local-only edit.
  function flushPendingSave() {
    if (saveTimeout !== null) {
      clearTimeout(saveTimeout)
      saveTimeout = null
      saveToFile()
    }
  }

  function saveToFile() {
    if (!mqtt.connected.value) {
      // Local save still happened; the file sync is best-effort. Surface
      // the deferred state to the UI so the operator knows it'll retry on
      // reconnect rather than thinking it saved.
      lastSaveError.value = 'Offline — file sync deferred until MQTT reconnects'
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
    // savePending stays true until we receive the 'saved' response.
    // If the response never comes, the flag eventually clears via the
    // ack timeout below.
    if (saveAckTimeout !== null) clearTimeout(saveAckTimeout)
    saveAckTimeout = window.setTimeout(() => {
      if (savePending.value) {
        lastSaveError.value = 'Save acknowledgement timed out (file may not be persisted to disk)'
        savePending.value = false
      }
      saveAckTimeout = null
    }, 8000)
  }

  function handleNotebookSaved(payload: any) {
    if (saveAckTimeout !== null) {
      clearTimeout(saveAckTimeout)
      saveAckTimeout = null
    }
    if (payload && payload.success) {
      lastSavedAt.value = new Date().toISOString()
      lastSaveError.value = null
    } else {
      lastSaveError.value = `File save failed: ${payload?.error || 'unknown error'}`
    }
    savePending.value = false
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

  // Effective "last modified" timestamp = the most recent of (creation,
  // last amendment). This is what merge conflict resolution uses to pick
  // the winner instead of blindly preferring the file version, which used
  // to clobber unsaved local edits.
  function entryLastModified(e: NotebookEntry): number {
    let t = new Date(e.timestamp).getTime() || 0
    if (e.amendments && e.amendments.length > 0) {
      const last = e.amendments[e.amendments.length - 1]
      const at = new Date(last.timestamp).getTime() || 0
      if (at > t) t = at
    }
    return t
  }

  function experimentLastModified(e: Experiment): number {
    let t = new Date(e.startedAt).getTime() || 0
    if (e.endedAt) {
      const et = new Date(e.endedAt).getTime() || 0
      if (et > t) t = et
    }
    return t
  }

  // Merge two collections by ID, picking the entry with the newer effective
  // timestamp on conflict. Order-independent — won't lose data regardless
  // of which side is "first" in the spread.
  function mergeById<T>(local: T[], file: T[], lastModified: (x: T) => number, getId: (x: T) => string): T[] {
    const merged = new Map<string, T>()
    for (const x of local) merged.set(getId(x), x)
    for (const x of file) {
      const id = getId(x)
      const existing = merged.get(id)
      if (!existing || lastModified(x) >= lastModified(existing)) {
        merged.set(id, x)
      }
    }
    return Array.from(merged.values())
  }

  function handleNotebookLoaded(payload: any) {
    if (!payload || !payload.success || !payload.data) return

    const data = payload.data
    if (data.entries && Array.isArray(data.entries)) {
      entries.value = mergeById<NotebookEntry>(
        entries.value,
        data.entries,
        entryLastModified,
        e => e.id,
      )
      try {
        localStorage.setItem(NOTEBOOK_STORAGE_KEY, JSON.stringify(entries.value))
      } catch (e: any) {
        lastSaveError.value = `Local save failed after merge: ${e?.message || e}`
      }
    }

    if (data.experiments && Array.isArray(data.experiments)) {
      experiments.value = mergeById<Experiment>(
        experiments.value,
        data.experiments,
        experimentLastModified,
        e => e.id,
      )
      try {
        localStorage.setItem(EXPERIMENTS_STORAGE_KEY, JSON.stringify(experiments.value))
      } catch (e: any) {
        lastSaveError.value = `Local save failed after merge: ${e?.message || e}`
      }
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
    initialized = true

    // Load from localStorage first (instant) — gives the UI something to
    // render even before MQTT connects.
    loadFromStorage()

    // Subscribe to load + save responses BEFORE issuing the load request,
    // so we can't miss a fast response on the wire. Previously a 500ms
    // setTimeout was used as a hack; that races on slow links.
    mqtt.subscribe('nisystem/notebook/loaded', handleNotebookLoaded)
    mqtt.subscribe('nisystem/notebook/saved', handleNotebookSaved)

    // When MQTT is/becomes connected, request the file. The watcher fires
    // immediately if already connected, removing the need for any delay.
    watch(() => mqtt.connected.value, (connected) => {
      if (connected) loadFromFile()
    }, { immediate: true })

    // Register global page-lifecycle listeners ONCE so we don't lose the
    // last 2s of edits when the user navigates away. Module-singleton
    // pattern means we should not bind to component lifecycle.
    if (!listenersRegistered && typeof window !== 'undefined') {
      listenersRegistered = true
      window.addEventListener('beforeunload', flushPendingSave)
      // visibilitychange fires when the user switches tabs or minimizes.
      // hidden → flush; we don't wait until full unload because mobile
      // browsers may not fire beforeunload reliably.
      document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'hidden') flushPendingSave()
      })
    }
  }

  initialize()

  // NOTE: deliberately no per-component unmount cleanup of saveTimeout.
  // The state is a module-level singleton; clearing the timer when ANY
  // consumer's component unmounts would cancel pending writes for OTHER
  // live consumers. Flush is handled at page lifecycle events
  // (beforeunload, visibilitychange) instead.

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
    // Persistence status — bind to UI for save indicator + error toast.
    lastSaveError,
    savePending,
    lastSavedAt,

    // Computed
    activeExperiment,
    filteredEntries,
    allTags,
    entriesByExperiment,

    // Entry actions
    addEntry,
    amendEntry,
    deleteEntry,
    addQuickNote,
    addFromTemplate,
    captureDataSnapshot,

    // Experiment actions
    startExperiment,
    endExperiment,
    deleteExperiment,
    setActiveExperiment,

    // Search & filter
    setSearchQuery,
    toggleFilterTag,
    clearFilters,

    // Persistence helpers
    flushPendingSave,

    // Export
    exportToPdf,
    exportToMarkdown,
    exportToText,
  }
}
