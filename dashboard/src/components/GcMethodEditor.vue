<script setup lang="ts">
/**
 * GcMethodEditor - Gas Chromatograph Method Editor
 *
 * A tab-level component for creating, editing, importing/exporting, and pushing
 * GC analysis methods to gc_node instances over MQTT.
 *
 * Methods define peak detection parameters, component identification windows,
 * calibration curves, SST (System Suitability Test) criteria, and valve/port
 * configuration. Methods are persisted in localStorage and can be pushed to
 * remote GC nodes via MQTT commands.
 *
 * MQTT command used:
 *   sendNodeCommand('commands/gc', { command: 'push_method', method: methodObj }, nodeId)
 *
 * Data structure matches gc_analysis.py AnalysisMethod.
 */

import { ref, reactive, computed, watch, onMounted, nextTick } from 'vue'
import { useDashboardStore } from '../stores/dashboard'
import { useMqtt } from '../composables/useMqtt'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface CalibrationPoint {
  area: number
  concentration: number
}

interface CalibrationCurve {
  points: CalibrationPoint[]
  fit_type: 'linear' | 'quadratic' | 'power'
}

interface GCComponent {
  name: string
  expected_rt: number
  rt_tolerance: number
  response_factor: number
  unit: string
  calibration?: CalibrationCurve
}

interface SSTCriteria {
  min_plates: number
  min_resolution: number
  max_tailing: number
  min_replicates: number
}

interface GCPort {
  number: number
  label: string
  sample_type: 'sample' | 'calibration' | 'blank' | 'check_standard'
}

interface GCMethod {
  name: string
  description: string
  // Peak detection
  min_peak_height: number
  min_peak_width_s: number
  min_peak_distance_s: number
  baseline_window_s: number
  noise_threshold: number
  // Component identification windows
  components: GCComponent[]
  // SST criteria
  sst: SSTCriteria
  // Valve/port config
  ports: GCPort[]
}

interface MethodListEntry {
  name: string
  modified: string  // ISO date string
}

type PushStatus = 'idle' | 'sending' | 'success' | 'error'

// ---------------------------------------------------------------------------
// Composables & Store
// ---------------------------------------------------------------------------

const store = useDashboardStore()
const mqtt = useMqtt('nisystem')

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const STORAGE_KEY = 'gc-methods'
const SAMPLE_TYPES: { value: GCPort['sample_type']; label: string }[] = [
  { value: 'sample', label: 'Sample' },
  { value: 'calibration', label: 'Calibration' },
  { value: 'blank', label: 'Blank' },
  { value: 'check_standard', label: 'Check Standard' }
]

const FIT_TYPES: { value: CalibrationCurve['fit_type']; label: string }[] = [
  { value: 'linear', label: 'Linear' },
  { value: 'quadratic', label: 'Quadratic' },
  { value: 'power', label: 'Power' }
]

const COMMON_UNITS: string[] = ['mol%', 'ppm', 'ppb', 'vol%', 'wt%', 'mg/L', 'ug/L']

// ---------------------------------------------------------------------------
// Default Method Factory
// ---------------------------------------------------------------------------

function createDefaultMethod(name: string = 'New Method'): GCMethod {
  return {
    name,
    description: '',
    min_peak_height: 0.01,
    min_peak_width_s: 1.0,
    min_peak_distance_s: 2.0,
    baseline_window_s: 30.0,
    noise_threshold: 3.0,
    components: [],
    sst: {
      min_plates: 2000,
      min_resolution: 1.5,
      max_tailing: 2.0,
      min_replicates: 5
    },
    ports: []
  }
}

function createDefaultComponent(): GCComponent {
  return {
    name: '',
    expected_rt: 60.0,
    rt_tolerance: 5.0,
    response_factor: 1.0,
    unit: 'mol%'
  }
}

function createDefaultPort(portNumber: number): GCPort {
  return {
    number: portNumber,
    label: `Port ${portNumber}`,
    sample_type: 'sample'
  }
}

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

// Method list
const methods = ref<GCMethod[]>([])
const selectedMethodIndex = ref<number>(-1)
const methodListEntries = ref<MethodListEntry[]>([])

// Current method being edited (deep clone of the selected method)
const currentMethod = ref<GCMethod>(createDefaultMethod())

// Track dirty state
const isDirty = ref(false)

// Collapsible section states
const sectionCollapsed = reactive<Record<string, boolean>>({
  peakDetection: false,
  components: false,
  sst: false,
  ports: true
})

// Expanded calibration rows (component index -> expanded)
const expandedCalibration = reactive<Record<number, boolean>>({})

// GC node ID for push
const gcNodeId = ref('gc-001')

// Push status
const pushStatus = ref<PushStatus>('idle')
const pushMessage = ref('')
let pushStatusTimeout: ReturnType<typeof setTimeout> | null = null

// Search filter for method list
const methodSearchFilter = ref('')

// Feedback
const feedbackMessage = ref<{ type: 'success' | 'error' | 'info' | 'warning'; text: string } | null>(null)
let feedbackTimeoutId: ReturnType<typeof setTimeout> | null = null

// File input ref
const fileInputRef = ref<HTMLInputElement | null>(null)

// ---------------------------------------------------------------------------
// Computed
// ---------------------------------------------------------------------------

const filteredMethods = computed(() => {
  const filter = methodSearchFilter.value.toLowerCase().trim()
  if (!filter) return methods.value
  return methods.value.filter(m =>
    m.name.toLowerCase().includes(filter) ||
    m.description.toLowerCase().includes(filter)
  )
})

const hasSelectedMethod = computed(() => selectedMethodIndex.value >= 0 && selectedMethodIndex.value < methods.value.length)

const componentCount = computed(() => currentMethod.value.components.length)

const portCount = computed(() => currentMethod.value.ports.length)

const totalCalibrationPoints = computed(() => {
  return currentMethod.value.components.reduce((sum, comp) => {
    return sum + (comp.calibration?.points.length || 0)
  }, 0)
})

/** Available GC node IDs from project channels */
const availableGcNodeIds = computed<string[]>(() => {
  const nodeIds = new Set<string>()
  for (const ch of Object.values(store.channels)) {
    if ((ch as any).source_type === 'gc' && (ch as any).node_id) {
      nodeIds.add((ch as any).node_id)
    }
  }
  return Array.from(nodeIds)
})

// Validation
const validationErrors = computed<string[]>(() => {
  const errors: string[] = []
  if (!currentMethod.value.name.trim()) {
    errors.push('Method name is required')
  }
  if (currentMethod.value.min_peak_height <= 0) {
    errors.push('Min peak height must be positive')
  }
  if (currentMethod.value.min_peak_width_s <= 0) {
    errors.push('Min peak width must be positive')
  }
  if (currentMethod.value.min_peak_distance_s <= 0) {
    errors.push('Min peak distance must be positive')
  }
  if (currentMethod.value.baseline_window_s <= 0) {
    errors.push('Baseline window must be positive')
  }
  if (currentMethod.value.noise_threshold <= 0) {
    errors.push('Noise threshold must be positive')
  }
  // Component validation
  currentMethod.value.components.forEach((comp, i) => {
    if (!comp.name.trim()) {
      errors.push(`Component ${i + 1}: name is required`)
    }
    if (comp.expected_rt <= 0) {
      errors.push(`Component ${i + 1} (${comp.name || 'unnamed'}): expected RT must be positive`)
    }
    if (comp.rt_tolerance <= 0) {
      errors.push(`Component ${i + 1} (${comp.name || 'unnamed'}): RT tolerance must be positive`)
    }
    if (comp.response_factor <= 0) {
      errors.push(`Component ${i + 1} (${comp.name || 'unnamed'}): response factor must be positive`)
    }
    // Calibration validation
    if (comp.calibration) {
      if (comp.calibration.points.length < 2) {
        errors.push(`Component ${comp.name || i + 1}: calibration needs at least 2 points`)
      }
      comp.calibration.points.forEach((pt, j) => {
        if (pt.area < 0) {
          errors.push(`Component ${comp.name || i + 1}: calibration point ${j + 1} area must be non-negative`)
        }
      })
    }
  })
  // Check for duplicate component names
  const compNames = currentMethod.value.components.map(c => c.name.trim().toLowerCase()).filter(n => n)
  const dupes = compNames.filter((n, i) => compNames.indexOf(n) !== i)
  if (dupes.length > 0) {
    errors.push(`Duplicate component names: ${[...new Set(dupes)].join(', ')}`)
  }
  // SST validation
  if (currentMethod.value.sst.min_plates < 0) {
    errors.push('SST min plates must be non-negative')
  }
  if (currentMethod.value.sst.min_resolution < 0) {
    errors.push('SST min resolution must be non-negative')
  }
  if (currentMethod.value.sst.max_tailing <= 0) {
    errors.push('SST max tailing must be positive')
  }
  if (currentMethod.value.sst.min_replicates < 1) {
    errors.push('SST min replicates must be at least 1')
  }
  // Port validation
  const portNumbers = currentMethod.value.ports.map(p => p.number)
  const dupePorts = portNumbers.filter((n, i) => portNumbers.indexOf(n) !== i)
  if (dupePorts.length > 0) {
    errors.push(`Duplicate port numbers: ${[...new Set(dupePorts)].join(', ')}`)
  }
  return errors
})

const isValid = computed(() => validationErrors.value.length === 0)

// ---------------------------------------------------------------------------
// Persistence (localStorage)
// ---------------------------------------------------------------------------

function loadMethodsFromStorage(): void {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) {
      const parsed = JSON.parse(raw)
      if (Array.isArray(parsed)) {
        methods.value = parsed
      }
    }
  } catch (err) {
    console.error('[GcMethodEditor] Failed to load methods from localStorage:', err)
    methods.value = []
  }
}

function saveMethodsToStorage(): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(methods.value))
  } catch (err) {
    console.error('[GcMethodEditor] Failed to save methods to localStorage:', err)
    showFeedback('error', 'Failed to save methods to local storage')
  }
}

function saveCurrentMethod(): void {
  if (selectedMethodIndex.value < 0) {
    // No method selected, create a new one
    methods.value.push(deepClone(currentMethod.value))
    selectedMethodIndex.value = methods.value.length - 1
  } else {
    // Update existing method
    methods.value[selectedMethodIndex.value] = deepClone(currentMethod.value)
  }
  saveMethodsToStorage()
  isDirty.value = false
  showFeedback('success', `Method "${currentMethod.value.name}" saved`)
}

// ---------------------------------------------------------------------------
// Method Management
// ---------------------------------------------------------------------------

function selectMethod(index: number): void {
  if (isDirty.value && hasSelectedMethod.value) {
    const proceed = confirm('You have unsaved changes. Discard and switch method?')
    if (!proceed) return
  }
  selectedMethodIndex.value = index
  currentMethod.value = deepClone(methods.value[index]!)
  isDirty.value = false
  // Collapse all calibration expansions
  Object.keys(expandedCalibration).forEach(k => delete expandedCalibration[Number(k)])
}

function createNewMethod(): void {
  if (isDirty.value && hasSelectedMethod.value) {
    const proceed = confirm('You have unsaved changes. Discard and create new method?')
    if (!proceed) return
  }

  // Generate unique name
  let baseName = 'New Method'
  let counter = 1
  const existingNames = methods.value.map(m => m.name)
  let newName = baseName
  while (existingNames.includes(newName)) {
    counter++
    newName = `${baseName} ${counter}`
  }

  const newMethod = createDefaultMethod(newName)
  methods.value.push(newMethod)
  selectedMethodIndex.value = methods.value.length - 1
  currentMethod.value = deepClone(newMethod)
  isDirty.value = false
  saveMethodsToStorage()
  showFeedback('info', `Created new method "${newName}"`)
}

function duplicateMethod(): void {
  if (!hasSelectedMethod.value) return

  const source = currentMethod.value
  const baseName = `${source.name} (Copy)`
  let counter = 0
  const existingNames = methods.value.map(m => m.name)
  let newName = baseName
  while (existingNames.includes(newName)) {
    counter++
    newName = `${source.name} (Copy ${counter})`
  }

  const duplicate = deepClone(source)
  duplicate.name = newName
  methods.value.push(duplicate)
  selectedMethodIndex.value = methods.value.length - 1
  currentMethod.value = deepClone(duplicate)
  isDirty.value = false
  saveMethodsToStorage()
  showFeedback('info', `Duplicated as "${newName}"`)
}

function deleteMethod(): void {
  if (!hasSelectedMethod.value) return

  const methodName = methods.value[selectedMethodIndex.value]!.name
  const proceed = confirm(`Delete method "${methodName}"? This cannot be undone.`)
  if (!proceed) return

  methods.value.splice(selectedMethodIndex.value, 1)
  saveMethodsToStorage()

  if (methods.value.length === 0) {
    selectedMethodIndex.value = -1
    currentMethod.value = createDefaultMethod()
  } else {
    const newIndex = Math.min(selectedMethodIndex.value, methods.value.length - 1)
    selectedMethodIndex.value = newIndex
    currentMethod.value = deepClone(methods.value[newIndex]!)
  }
  isDirty.value = false
  showFeedback('info', `Deleted method "${methodName}"`)
}

// ---------------------------------------------------------------------------
// Component Management
// ---------------------------------------------------------------------------

function addComponent(): void {
  const comp = createDefaultComponent()
  // Auto-increment name
  const existingCount = currentMethod.value.components.length
  comp.name = `Component_${existingCount + 1}`
  // Space out expected RTs
  if (existingCount > 0) {
    const lastRt = currentMethod.value.components[existingCount - 1]!.expected_rt
    comp.expected_rt = lastRt + 30
  }
  currentMethod.value.components.push(comp)
  isDirty.value = true
}

function removeComponent(index: number): void {
  currentMethod.value.components.splice(index, 1)
  delete expandedCalibration[index]
  // Re-index expanded states
  const newExpanded: Record<number, boolean> = {}
  Object.entries(expandedCalibration).forEach(([k, v]) => {
    const ki = Number(k)
    if (ki > index) {
      newExpanded[ki - 1] = v
    } else if (ki < index) {
      newExpanded[ki] = v
    }
  })
  Object.keys(expandedCalibration).forEach(k => delete expandedCalibration[Number(k)])
  Object.entries(newExpanded).forEach(([k, v]) => { expandedCalibration[Number(k)] = v })
  isDirty.value = true
}

function moveComponentUp(index: number): void {
  if (index <= 0) return
  const comps = currentMethod.value.components
  const temp = comps[index]!
  comps[index] = comps[index - 1]!
  comps[index - 1] = temp
  isDirty.value = true
}

function moveComponentDown(index: number): void {
  const comps = currentMethod.value.components
  if (index >= comps.length - 1) return
  const temp = comps[index]!
  comps[index] = comps[index + 1]!
  comps[index + 1] = temp
  isDirty.value = true
}

function sortComponentsByRT(): void {
  currentMethod.value.components.sort((a, b) => a.expected_rt - b.expected_rt)
  isDirty.value = true
  showFeedback('info', 'Components sorted by retention time')
}

// ---------------------------------------------------------------------------
// Calibration Management
// ---------------------------------------------------------------------------

function toggleCalibration(compIndex: number): void {
  expandedCalibration[compIndex] = !expandedCalibration[compIndex]
}

function enableCalibration(compIndex: number): void {
  const comp = currentMethod.value.components[compIndex]!
  if (!comp.calibration) {
    comp.calibration = {
      points: [
        { area: 0, concentration: 0 },
        { area: 1000, concentration: 1.0 }
      ],
      fit_type: 'linear'
    }
    isDirty.value = true
  }
}

function disableCalibration(compIndex: number): void {
  const comp = currentMethod.value.components[compIndex]!
  if (comp.calibration) {
    const proceed = confirm('Remove calibration data for this component?')
    if (!proceed) return
    delete comp.calibration
    isDirty.value = true
  }
}

function addCalibrationPoint(compIndex: number): void {
  const comp = currentMethod.value.components[compIndex]!
  if (!comp.calibration) return
  const pts = comp.calibration.points
  // Auto-increment area/concentration from last point
  const lastPt = pts.length > 0 ? pts[pts.length - 1] ?? { area: 0, concentration: 0 } : { area: 0, concentration: 0 }
  pts.push({
    area: lastPt.area + 1000,
    concentration: lastPt.concentration + 1.0
  })
  isDirty.value = true
}

function removeCalibrationPoint(compIndex: number, pointIndex: number): void {
  const comp = currentMethod.value.components[compIndex]!
  if (!comp.calibration) return
  comp.calibration.points.splice(pointIndex, 1)
  isDirty.value = true
}

function sortCalibrationByArea(compIndex: number): void {
  const comp = currentMethod.value.components[compIndex]!
  if (!comp.calibration) return
  comp.calibration.points.sort((a, b) => a.area - b.area)
  isDirty.value = true
}

// ---------------------------------------------------------------------------
// Port Management
// ---------------------------------------------------------------------------

function addPort(): void {
  const existingNumbers = currentMethod.value.ports.map(p => p.number)
  let nextNumber = 1
  while (existingNumbers.includes(nextNumber)) nextNumber++
  currentMethod.value.ports.push(createDefaultPort(nextNumber))
  isDirty.value = true
}

function removePort(index: number): void {
  currentMethod.value.ports.splice(index, 1)
  isDirty.value = true
}

// ---------------------------------------------------------------------------
// Import / Export
// ---------------------------------------------------------------------------

function exportMethod(): void {
  if (!hasSelectedMethod.value) {
    showFeedback('error', 'No method selected to export')
    return
  }

  const methodData = deepClone(currentMethod.value)
  const jsonStr = JSON.stringify(methodData, null, 2)
  const blob = new Blob([jsonStr], { type: 'application/json' })
  const url = URL.createObjectURL(blob)

  const filename = `${methodData.name.replace(/[^a-zA-Z0-9_-]/g, '_')}_method.json`
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)

  showFeedback('success', `Exported "${methodData.name}" as ${filename}`)
}

function triggerImport(): void {
  fileInputRef.value?.click()
}

function handleImportFile(event: Event): void {
  const input = event.target as HTMLInputElement
  if (!input.files || input.files.length === 0) return

  const file = input.files[0]
  if (!file) return
  const reader = new FileReader()

  reader.onload = (e) => {
    try {
      const text = e.target?.result as string
      const imported = JSON.parse(text) as Partial<GCMethod>

      // Validate required fields
      if (!imported.name || typeof imported.name !== 'string') {
        showFeedback('error', 'Invalid method file: missing or invalid "name" field')
        return
      }

      // Merge with defaults for any missing fields
      const method = mergeWithDefaults(imported)

      // Check for duplicate name
      const existingNames = methods.value.map(m => m.name)
      if (existingNames.includes(method.name)) {
        method.name = `${method.name} (Imported)`
      }

      methods.value.push(method)
      selectedMethodIndex.value = methods.value.length - 1
      currentMethod.value = deepClone(method)
      isDirty.value = false
      saveMethodsToStorage()

      showFeedback('success', `Imported method "${method.name}"`)
    } catch (err) {
      console.error('[GcMethodEditor] Import error:', err)
      showFeedback('error', `Failed to import: ${err instanceof Error ? err.message : 'Invalid JSON'}`)
    }

    // Reset file input
    input.value = ''
  }

  reader.onerror = () => {
    showFeedback('error', 'Failed to read file')
    input.value = ''
  }

  reader.readAsText(file)
}

function mergeWithDefaults(partial: Partial<GCMethod>): GCMethod {
  const defaults = createDefaultMethod(partial.name || 'Imported Method')
  return {
    ...defaults,
    ...partial,
    sst: {
      ...defaults.sst,
      ...(partial.sst || {})
    },
    components: (partial.components || []).map(c => ({
      ...createDefaultComponent(),
      ...c,
      calibration: c.calibration ? {
        points: c.calibration.points || [],
        fit_type: c.calibration.fit_type || 'linear'
      } : undefined
    })),
    ports: (partial.ports || []).map((p, i) => ({
      ...createDefaultPort(i + 1),
      ...p
    }))
  }
}

// ---------------------------------------------------------------------------
// Push Method to GC Node
// ---------------------------------------------------------------------------

function pushMethodToNode(): void {
  if (!isValid.value) {
    showFeedback('error', 'Fix validation errors before pushing')
    return
  }

  const nodeId = gcNodeId.value.trim()
  if (!nodeId) {
    showFeedback('error', 'Enter a GC node ID')
    return
  }

  if (!mqtt.connected.value) {
    showFeedback('error', 'MQTT not connected')
    return
  }

  pushStatus.value = 'sending'
  pushMessage.value = `Pushing to ${nodeId}...`

  try {
    const methodObj = deepClone(currentMethod.value)
    mqtt.sendNodeCommand('commands/gc', { command: 'push_method', method: methodObj }, nodeId)

    // Since MQTT publish is fire-and-forget, assume success after a brief delay
    if (pushStatusTimeout) clearTimeout(pushStatusTimeout)
    pushStatusTimeout = setTimeout(() => {
      pushStatus.value = 'success'
      pushMessage.value = `Method pushed to ${nodeId}`
      showFeedback('success', `Method "${methodObj.name}" pushed to node ${nodeId}`)

      // Reset status after a few seconds
      pushStatusTimeout = setTimeout(() => {
        pushStatus.value = 'idle'
        pushMessage.value = ''
      }, 4000)
    }, 500)
  } catch (err) {
    pushStatus.value = 'error'
    pushMessage.value = `Push failed: ${err instanceof Error ? err.message : 'Unknown error'}`
    showFeedback('error', pushMessage.value)
  }
}

// ---------------------------------------------------------------------------
// Section Toggle
// ---------------------------------------------------------------------------

function toggleSection(section: string): void {
  sectionCollapsed[section] = !sectionCollapsed[section]
}

// ---------------------------------------------------------------------------
// Dirty Tracking
// ---------------------------------------------------------------------------

watch(currentMethod, () => {
  if (hasSelectedMethod.value) {
    isDirty.value = true
  }
}, { deep: true })

// ---------------------------------------------------------------------------
// Feedback
// ---------------------------------------------------------------------------

function showFeedback(type: 'success' | 'error' | 'info' | 'warning', text: string, duration = 4000): void {
  if (feedbackTimeoutId) clearTimeout(feedbackTimeoutId)
  feedbackMessage.value = { type, text }
  feedbackTimeoutId = setTimeout(() => {
    feedbackMessage.value = null
    feedbackTimeoutId = null
  }, duration)
}

// ---------------------------------------------------------------------------
// Utility
// ---------------------------------------------------------------------------

function deepClone<T>(obj: T): T {
  return JSON.parse(JSON.stringify(obj))
}

function formatRT(seconds: number): string {
  const mins = Math.floor(seconds / 60)
  const secs = (seconds % 60).toFixed(1)
  return `${mins}:${secs.padStart(4, '0')}`
}

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

onMounted(() => {
  loadMethodsFromStorage()
  if (methods.value.length > 0) {
    selectMethod(0)
  }
  // Set default GC node if available
  if (availableGcNodeIds.value.length > 0) {
    gcNodeId.value = availableGcNodeIds.value[0] ?? ''
  }
})
</script>

<template>
  <div class="gc-method-editor">
    <!-- Hidden file input for import -->
    <input
      ref="fileInputRef"
      type="file"
      accept=".json"
      style="display: none"
      @change="handleImportFile"
    />

    <!-- Feedback toast -->
    <Transition name="gc-toast">
      <div
        v-if="feedbackMessage"
        class="gc-feedback-toast"
        :class="feedbackMessage.type"
      >
        <span class="gc-toast-icon">
          <template v-if="feedbackMessage.type === 'success'">&#10003;</template>
          <template v-else-if="feedbackMessage.type === 'error'">&#10007;</template>
          <template v-else-if="feedbackMessage.type === 'warning'">&#9888;</template>
          <template v-else>&#8505;</template>
        </span>
        <span class="gc-toast-text">{{ feedbackMessage.text }}</span>
      </div>
    </Transition>

    <!-- ============================== -->
    <!-- Left Sidebar: Method List      -->
    <!-- ============================== -->
    <aside class="gc-sidebar">
      <div class="gc-sidebar-header">
        <h3 class="gc-sidebar-title">GC Methods</h3>
        <span class="gc-method-count">{{ methods.length }}</span>
      </div>

      <!-- Search filter -->
      <div class="gc-sidebar-search">
        <input
          v-model="methodSearchFilter"
          type="text"
          placeholder="Filter methods..."
          class="gc-search-input"
        />
      </div>

      <!-- Method list -->
      <div class="gc-method-list">
        <div
          v-for="(method, idx) in filteredMethods"
          :key="idx"
          class="gc-method-item"
          :class="{ active: idx === selectedMethodIndex, dirty: idx === selectedMethodIndex && isDirty }"
          @click="selectMethod(methods.indexOf(method))"
        >
          <div class="gc-method-item-name">
            <span class="gc-method-dot" :class="{ 'active-dot': idx === selectedMethodIndex }"></span>
            {{ method.name }}
          </div>
          <div class="gc-method-item-meta">
            {{ method.components.length }} comp{{ method.components.length !== 1 ? 's' : '' }}
          </div>
        </div>

        <div v-if="filteredMethods.length === 0 && methods.length > 0" class="gc-method-empty">
          No methods match filter
        </div>
        <div v-if="methods.length === 0" class="gc-method-empty">
          No methods defined.<br/>Click "New" to create one.
        </div>
      </div>

      <!-- Sidebar actions -->
      <div class="gc-sidebar-actions">
        <button class="gc-btn gc-btn-primary gc-btn-sm gc-btn-full" @click="createNewMethod" title="Create new method">
          + New
        </button>
        <div class="gc-btn-row">
          <button
            class="gc-btn gc-btn-secondary gc-btn-sm"
            :disabled="!hasSelectedMethod"
            @click="duplicateMethod"
            title="Duplicate selected method"
          >
            Duplicate
          </button>
          <button
            class="gc-btn gc-btn-danger gc-btn-sm"
            :disabled="!hasSelectedMethod"
            @click="deleteMethod"
            title="Delete selected method"
          >
            Delete
          </button>
        </div>
        <div class="gc-btn-row">
          <button class="gc-btn gc-btn-secondary gc-btn-sm" @click="triggerImport" title="Import method from JSON file">
            Import
          </button>
          <button
            class="gc-btn gc-btn-secondary gc-btn-sm"
            :disabled="!hasSelectedMethod"
            @click="exportMethod"
            title="Export selected method as JSON"
          >
            Export
          </button>
        </div>
      </div>
    </aside>

    <!-- ============================== -->
    <!-- Main Editor Panel              -->
    <!-- ============================== -->
    <main class="gc-editor-main">
      <!-- No method selected state -->
      <div v-if="!hasSelectedMethod && methods.length > 0" class="gc-empty-state">
        <div class="gc-empty-icon">&#9881;</div>
        <div class="gc-empty-text">Select a method from the sidebar to edit</div>
      </div>

      <div v-else-if="!hasSelectedMethod && methods.length === 0" class="gc-empty-state">
        <div class="gc-empty-icon">&#9881;</div>
        <div class="gc-empty-text">Create a new GC method to get started</div>
        <button class="gc-btn gc-btn-primary" @click="createNewMethod">+ New Method</button>
      </div>

      <!-- Editor content -->
      <div v-else class="gc-editor-content">
        <!-- ============================================ -->
        <!-- Header: Method Name & Description            -->
        <!-- ============================================ -->
        <div class="gc-editor-header">
          <div class="gc-header-fields">
            <div class="gc-form-group gc-form-group-name">
              <label class="gc-label">Method Name</label>
              <input
                v-model="currentMethod.name"
                type="text"
                class="gc-input gc-input-name"
                placeholder="Enter method name"
                maxlength="128"
              />
            </div>
            <div class="gc-form-group gc-form-group-desc">
              <label class="gc-label">Description</label>
              <textarea
                v-model="currentMethod.description"
                class="gc-textarea"
                placeholder="Method description (optional)"
                rows="2"
                maxlength="512"
              ></textarea>
            </div>
          </div>
          <div class="gc-header-badges">
            <span class="gc-badge" title="Components">{{ componentCount }} comp{{ componentCount !== 1 ? 's' : '' }}</span>
            <span class="gc-badge" title="Calibration points">{{ totalCalibrationPoints }} cal pts</span>
            <span class="gc-badge" title="Ports">{{ portCount }} port{{ portCount !== 1 ? 's' : '' }}</span>
            <span v-if="isDirty" class="gc-badge gc-badge-dirty" title="Unsaved changes">Modified</span>
          </div>
        </div>

        <!-- Validation errors banner -->
        <div v-if="validationErrors.length > 0" class="gc-validation-banner">
          <div class="gc-validation-header">
            <span class="gc-validation-icon">&#9888;</span>
            <span>{{ validationErrors.length }} validation error{{ validationErrors.length !== 1 ? 's' : '' }}</span>
          </div>
          <ul class="gc-validation-list">
            <li v-for="(err, i) in validationErrors" :key="i">{{ err }}</li>
          </ul>
        </div>

        <!-- ============================================ -->
        <!-- Section: Peak Detection                      -->
        <!-- ============================================ -->
        <div class="gc-section">
          <div class="gc-section-header" @click="toggleSection('peakDetection')">
            <span class="gc-collapse-icon" :class="{ collapsed: sectionCollapsed.peakDetection }">&#9660;</span>
            <h4 class="gc-section-title">Peak Detection Parameters</h4>
            <span class="gc-section-badge">5 params</span>
          </div>

          <Transition name="gc-collapse">
            <div v-show="!sectionCollapsed.peakDetection" class="gc-section-body">
              <div class="gc-param-grid">
                <div class="gc-form-group">
                  <label class="gc-label">Min Peak Height</label>
                  <div class="gc-input-with-unit">
                    <input
                      v-model.number="currentMethod.min_peak_height"
                      type="number"
                      class="gc-input gc-input-num"
                      step="0.001"
                      min="0"
                    />
                    <span class="gc-input-unit">AU</span>
                  </div>
                  <span class="gc-hint">Minimum signal amplitude to qualify as a peak</span>
                </div>

                <div class="gc-form-group">
                  <label class="gc-label">Min Peak Width</label>
                  <div class="gc-input-with-unit">
                    <input
                      v-model.number="currentMethod.min_peak_width_s"
                      type="number"
                      class="gc-input gc-input-num"
                      step="0.1"
                      min="0"
                    />
                    <span class="gc-input-unit">s</span>
                  </div>
                  <span class="gc-hint">Minimum peak width at half-height</span>
                </div>

                <div class="gc-form-group">
                  <label class="gc-label">Min Peak Distance</label>
                  <div class="gc-input-with-unit">
                    <input
                      v-model.number="currentMethod.min_peak_distance_s"
                      type="number"
                      class="gc-input gc-input-num"
                      step="0.1"
                      min="0"
                    />
                    <span class="gc-input-unit">s</span>
                  </div>
                  <span class="gc-hint">Minimum separation between adjacent peaks</span>
                </div>

                <div class="gc-form-group">
                  <label class="gc-label">Baseline Window</label>
                  <div class="gc-input-with-unit">
                    <input
                      v-model.number="currentMethod.baseline_window_s"
                      type="number"
                      class="gc-input gc-input-num"
                      step="1"
                      min="1"
                    />
                    <span class="gc-input-unit">s</span>
                  </div>
                  <span class="gc-hint">Rolling window for baseline drift estimation</span>
                </div>

                <div class="gc-form-group">
                  <label class="gc-label">Noise Threshold</label>
                  <div class="gc-input-with-unit">
                    <input
                      v-model.number="currentMethod.noise_threshold"
                      type="number"
                      class="gc-input gc-input-num"
                      step="0.1"
                      min="0"
                    />
                    <span class="gc-input-unit">&times; &sigma;</span>
                  </div>
                  <span class="gc-hint">Signal-to-noise ratio multiplier for detection</span>
                </div>
              </div>
            </div>
          </Transition>
        </div>

        <!-- ============================================ -->
        <!-- Section: Component Windows                   -->
        <!-- ============================================ -->
        <div class="gc-section">
          <div class="gc-section-header" @click="toggleSection('components')">
            <span class="gc-collapse-icon" :class="{ collapsed: sectionCollapsed.components }">&#9660;</span>
            <h4 class="gc-section-title">Component Identification Windows</h4>
            <span class="gc-section-badge">{{ componentCount }} component{{ componentCount !== 1 ? 's' : '' }}</span>
          </div>

          <Transition name="gc-collapse">
            <div v-show="!sectionCollapsed.components" class="gc-section-body">
              <!-- Component toolbar -->
              <div class="gc-toolbar">
                <button class="gc-btn gc-btn-primary gc-btn-sm" @click="addComponent">
                  + Add Component
                </button>
                <button
                  class="gc-btn gc-btn-secondary gc-btn-sm"
                  :disabled="componentCount < 2"
                  @click="sortComponentsByRT"
                  title="Sort all components by expected retention time"
                >
                  Sort by RT
                </button>
              </div>

              <!-- Components table -->
              <div v-if="componentCount > 0" class="gc-table-container">
                <table class="gc-table">
                  <thead>
                    <tr>
                      <th class="gc-th gc-th-narrow">#</th>
                      <th class="gc-th gc-th-name">Name</th>
                      <th class="gc-th gc-th-num">Expected RT (s)</th>
                      <th class="gc-th gc-th-num">Tolerance (s)</th>
                      <th class="gc-th gc-th-num">RF</th>
                      <th class="gc-th gc-th-unit">Unit</th>
                      <th class="gc-th gc-th-cal">Calibration</th>
                      <th class="gc-th gc-th-actions">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    <template v-for="(comp, compIdx) in currentMethod.components" :key="compIdx">
                      <!-- Component row -->
                      <tr class="gc-tr" :class="{ 'gc-tr-expanded': expandedCalibration[compIdx] }">
                        <td class="gc-td gc-td-narrow">
                          <span class="gc-row-num">{{ compIdx + 1 }}</span>
                        </td>
                        <td class="gc-td gc-td-name">
                          <input
                            v-model="comp.name"
                            type="text"
                            class="gc-input gc-input-inline"
                            placeholder="Component name"
                            maxlength="64"
                          />
                        </td>
                        <td class="gc-td gc-td-num">
                          <input
                            v-model.number="comp.expected_rt"
                            type="number"
                            class="gc-input gc-input-inline gc-input-num"
                            step="0.1"
                            min="0"
                          />
                          <span class="gc-td-sub">{{ formatRT(comp.expected_rt) }}</span>
                        </td>
                        <td class="gc-td gc-td-num">
                          <input
                            v-model.number="comp.rt_tolerance"
                            type="number"
                            class="gc-input gc-input-inline gc-input-num"
                            step="0.1"
                            min="0.1"
                          />
                        </td>
                        <td class="gc-td gc-td-num">
                          <input
                            v-model.number="comp.response_factor"
                            type="number"
                            class="gc-input gc-input-inline gc-input-num"
                            step="0.01"
                            min="0.001"
                          />
                        </td>
                        <td class="gc-td gc-td-unit">
                          <select v-model="comp.unit" class="gc-select gc-select-inline">
                            <option v-for="u in COMMON_UNITS" :key="u" :value="u">{{ u }}</option>
                          </select>
                        </td>
                        <td class="gc-td gc-td-cal">
                          <button
                            v-if="comp.calibration"
                            class="gc-btn-link gc-cal-toggle"
                            :class="{ active: expandedCalibration[compIdx] }"
                            @click="toggleCalibration(compIdx)"
                            :title="expandedCalibration[compIdx] ? 'Collapse calibration' : 'Expand calibration'"
                          >
                            {{ comp.calibration.points.length }} pts ({{ comp.calibration.fit_type }})
                            <span class="gc-expand-arrow" :class="{ expanded: expandedCalibration[compIdx] }">&#9660;</span>
                          </button>
                          <button
                            v-else
                            class="gc-btn-link gc-btn-add-cal"
                            @click="enableCalibration(compIdx)"
                            title="Enable multi-point calibration"
                          >
                            + Add Cal
                          </button>
                        </td>
                        <td class="gc-td gc-td-actions">
                          <div class="gc-action-btns">
                            <button
                              class="gc-btn-icon"
                              :disabled="compIdx === 0"
                              @click="moveComponentUp(compIdx)"
                              title="Move up"
                            >&#9650;</button>
                            <button
                              class="gc-btn-icon"
                              :disabled="compIdx === currentMethod.components.length - 1"
                              @click="moveComponentDown(compIdx)"
                              title="Move down"
                            >&#9660;</button>
                            <button
                              class="gc-btn-icon gc-btn-icon-danger"
                              @click="removeComponent(compIdx)"
                              title="Remove component"
                            >&#10007;</button>
                          </div>
                        </td>
                      </tr>

                      <!-- Calibration expanded row -->
                      <tr v-if="comp.calibration && expandedCalibration[compIdx]" class="gc-tr-calibration">
                        <td colspan="8" class="gc-td-calibration-content">
                          <div class="gc-calibration-panel">
                            <div class="gc-calibration-header">
                              <h5 class="gc-calibration-title">Calibration Curve - {{ comp.name || 'Unnamed' }}</h5>
                              <div class="gc-calibration-controls">
                                <label class="gc-label gc-label-inline">Fit Type:</label>
                                <select v-model="comp.calibration.fit_type" class="gc-select gc-select-sm">
                                  <option v-for="ft in FIT_TYPES" :key="ft.value" :value="ft.value">{{ ft.label }}</option>
                                </select>
                                <button
                                  class="gc-btn gc-btn-secondary gc-btn-xs"
                                  :disabled="(comp.calibration?.points.length || 0) < 2"
                                  @click="sortCalibrationByArea(compIdx)"
                                  title="Sort calibration points by area"
                                >
                                  Sort
                                </button>
                                <button
                                  class="gc-btn gc-btn-danger gc-btn-xs"
                                  @click="disableCalibration(compIdx)"
                                  title="Remove calibration"
                                >
                                  Remove Cal
                                </button>
                              </div>
                            </div>

                            <!-- Calibration points table -->
                            <div class="gc-cal-table-wrap">
                              <table class="gc-table gc-table-cal">
                                <thead>
                                  <tr>
                                    <th class="gc-th gc-th-narrow">#</th>
                                    <th class="gc-th gc-th-num">Area</th>
                                    <th class="gc-th gc-th-num">Concentration ({{ comp.unit }})</th>
                                    <th class="gc-th gc-th-actions">Actions</th>
                                  </tr>
                                </thead>
                                <tbody>
                                  <tr v-for="(pt, ptIdx) in comp.calibration.points" :key="ptIdx" class="gc-tr">
                                    <td class="gc-td gc-td-narrow">
                                      <span class="gc-row-num">{{ ptIdx + 1 }}</span>
                                    </td>
                                    <td class="gc-td gc-td-num">
                                      <input
                                        v-model.number="pt.area"
                                        type="number"
                                        class="gc-input gc-input-inline gc-input-num"
                                        step="1"
                                        min="0"
                                      />
                                    </td>
                                    <td class="gc-td gc-td-num">
                                      <input
                                        v-model.number="pt.concentration"
                                        type="number"
                                        class="gc-input gc-input-inline gc-input-num"
                                        step="0.001"
                                      />
                                    </td>
                                    <td class="gc-td gc-td-actions">
                                      <button
                                        class="gc-btn-icon gc-btn-icon-danger"
                                        @click="removeCalibrationPoint(compIdx, ptIdx)"
                                        title="Remove calibration point"
                                      >&#10007;</button>
                                    </td>
                                  </tr>
                                </tbody>
                              </table>
                            </div>

                            <div class="gc-cal-footer">
                              <button class="gc-btn gc-btn-secondary gc-btn-xs" @click="addCalibrationPoint(compIdx)">
                                + Add Point
                              </button>
                              <span class="gc-cal-summary">
                                {{ comp.calibration.points.length }} point{{ comp.calibration.points.length !== 1 ? 's' : '' }},
                                {{ comp.calibration.fit_type }} fit
                              </span>
                            </div>
                          </div>
                        </td>
                      </tr>
                    </template>
                  </tbody>
                </table>
              </div>

              <!-- Empty state for components -->
              <div v-else class="gc-empty-section">
                No components defined. Click "Add Component" to add retention time windows.
              </div>
            </div>
          </Transition>
        </div>

        <!-- ============================================ -->
        <!-- Section: SST Criteria                        -->
        <!-- ============================================ -->
        <div class="gc-section">
          <div class="gc-section-header" @click="toggleSection('sst')">
            <span class="gc-collapse-icon" :class="{ collapsed: sectionCollapsed.sst }">&#9660;</span>
            <h4 class="gc-section-title">System Suitability Test (SST) Criteria</h4>
            <span class="gc-section-badge">4 params</span>
          </div>

          <Transition name="gc-collapse">
            <div v-show="!sectionCollapsed.sst" class="gc-section-body">
              <div class="gc-param-grid">
                <div class="gc-form-group">
                  <label class="gc-label">Min Theoretical Plates (N)</label>
                  <div class="gc-input-with-unit">
                    <input
                      v-model.number="currentMethod.sst.min_plates"
                      type="number"
                      class="gc-input gc-input-num"
                      step="100"
                      min="0"
                    />
                    <span class="gc-input-unit">plates</span>
                  </div>
                  <span class="gc-hint">Column efficiency metric. Typical: 2000+ for GC</span>
                </div>

                <div class="gc-form-group">
                  <label class="gc-label">Min Resolution (R<sub>s</sub>)</label>
                  <div class="gc-input-with-unit">
                    <input
                      v-model.number="currentMethod.sst.min_resolution"
                      type="number"
                      class="gc-input gc-input-num"
                      step="0.1"
                      min="0"
                    />
                    <span class="gc-input-unit">R<sub>s</sub></span>
                  </div>
                  <span class="gc-hint">Separation between adjacent peaks. 1.5 = baseline resolved</span>
                </div>

                <div class="gc-form-group">
                  <label class="gc-label">Max Tailing Factor (T)</label>
                  <div class="gc-input-with-unit">
                    <input
                      v-model.number="currentMethod.sst.max_tailing"
                      type="number"
                      class="gc-input gc-input-num"
                      step="0.1"
                      min="0.1"
                    />
                    <span class="gc-input-unit">T</span>
                  </div>
                  <span class="gc-hint">Peak symmetry. 1.0 = symmetric, &gt;2.0 = excessive tailing</span>
                </div>

                <div class="gc-form-group">
                  <label class="gc-label">Min Replicates</label>
                  <div class="gc-input-with-unit">
                    <input
                      v-model.number="currentMethod.sst.min_replicates"
                      type="number"
                      class="gc-input gc-input-num"
                      step="1"
                      min="1"
                      max="99"
                    />
                    <span class="gc-input-unit">runs</span>
                  </div>
                  <span class="gc-hint">Number of replicate injections required for SST pass</span>
                </div>
              </div>

              <!-- SST reference info -->
              <div class="gc-info-box">
                <strong>SST Reference:</strong> System suitability criteria are evaluated after the specified
                number of replicate injections. All criteria must pass for the system to be considered suitable.
                Values are compared against peaks identified in the chromatogram according to USP &lt;621&gt;
                / EP 2.2.46 guidelines.
              </div>
            </div>
          </Transition>
        </div>

        <!-- ============================================ -->
        <!-- Section: Port/Valve Configuration            -->
        <!-- ============================================ -->
        <div class="gc-section">
          <div class="gc-section-header" @click="toggleSection('ports')">
            <span class="gc-collapse-icon" :class="{ collapsed: sectionCollapsed.ports }">&#9660;</span>
            <h4 class="gc-section-title">Port / Valve Configuration</h4>
            <span class="gc-section-badge">{{ portCount }} port{{ portCount !== 1 ? 's' : '' }}</span>
          </div>

          <Transition name="gc-collapse">
            <div v-show="!sectionCollapsed.ports" class="gc-section-body">
              <!-- Port toolbar -->
              <div class="gc-toolbar">
                <button class="gc-btn gc-btn-primary gc-btn-sm" @click="addPort">
                  + Add Port
                </button>
              </div>

              <!-- Ports table -->
              <div v-if="portCount > 0" class="gc-table-container">
                <table class="gc-table">
                  <thead>
                    <tr>
                      <th class="gc-th gc-th-narrow">Port #</th>
                      <th class="gc-th gc-th-name">Label</th>
                      <th class="gc-th">Sample Type</th>
                      <th class="gc-th gc-th-actions">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="(port, portIdx) in currentMethod.ports" :key="portIdx" class="gc-tr">
                      <td class="gc-td gc-td-narrow">
                        <input
                          v-model.number="port.number"
                          type="number"
                          class="gc-input gc-input-inline gc-input-num"
                          step="1"
                          min="1"
                          max="64"
                        />
                      </td>
                      <td class="gc-td gc-td-name">
                        <input
                          v-model="port.label"
                          type="text"
                          class="gc-input gc-input-inline"
                          placeholder="Port label"
                          maxlength="64"
                        />
                      </td>
                      <td class="gc-td">
                        <select v-model="port.sample_type" class="gc-select gc-select-inline">
                          <option v-for="st in SAMPLE_TYPES" :key="st.value" :value="st.value">
                            {{ st.label }}
                          </option>
                        </select>
                      </td>
                      <td class="gc-td gc-td-actions">
                        <button
                          class="gc-btn-icon gc-btn-icon-danger"
                          @click="removePort(portIdx)"
                          title="Remove port"
                        >&#10007;</button>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>

              <div v-else class="gc-empty-section">
                No ports configured. Click "Add Port" to define valve/port assignments.
              </div>

              <!-- Port info -->
              <div class="gc-info-box">
                <strong>Port Configuration:</strong> Define multi-port valve positions for sample, calibration,
                blank, and check standard streams. Port numbers must be unique and correspond to the
                physical valve positions on the GC instrument.
              </div>
            </div>
          </Transition>
        </div>
      </div>

      <!-- ============================================ -->
      <!-- Action Bar (bottom)                          -->
      <!-- ============================================ -->
      <div v-if="hasSelectedMethod" class="gc-action-bar">
        <div class="gc-action-bar-left">
          <!-- Push to node -->
          <div class="gc-push-group">
            <label class="gc-label gc-label-inline">GC Node:</label>
            <div class="gc-node-input-group">
              <select
                v-if="availableGcNodeIds.length > 0"
                v-model="gcNodeId"
                class="gc-select gc-select-node"
              >
                <option v-for="nid in availableGcNodeIds" :key="nid" :value="nid">{{ nid }}</option>
              </select>
              <input
                v-else
                v-model="gcNodeId"
                type="text"
                class="gc-input gc-input-node"
                placeholder="gc-001"
                maxlength="64"
              />
              <!-- Always show text input for manual override when nodes exist -->
              <input
                v-if="availableGcNodeIds.length > 0"
                v-model="gcNodeId"
                type="text"
                class="gc-input gc-input-node-override"
                placeholder="Override node ID"
                maxlength="64"
                title="Override with custom node ID"
              />
            </div>
            <button
              class="gc-btn gc-btn-accent"
              :disabled="!isValid || pushStatus === 'sending' || !gcNodeId.trim()"
              @click="pushMethodToNode"
            >
              <span v-if="pushStatus === 'sending'" class="gc-spinner"></span>
              <template v-else>Push to Node</template>
            </button>
          </div>

          <!-- Push status -->
          <div v-if="pushMessage" class="gc-push-status" :class="pushStatus">
            {{ pushMessage }}
          </div>
        </div>

        <div class="gc-action-bar-right">
          <button
            class="gc-btn gc-btn-primary"
            :disabled="!isDirty && hasSelectedMethod"
            @click="saveCurrentMethod"
          >
            Save Method
          </button>
        </div>
      </div>
    </main>
  </div>
</template>

<style scoped>
/* ============================================================================
   GC Method Editor - Root Layout
   ============================================================================ */

.gc-method-editor {
  display: flex;
  height: 100%;
  min-height: 0;
  background: var(--bg-widget, #1a1a2e);
  color: var(--text-bright, #e2e8f0);
  font-family: 'Inter', 'Segoe UI', system-ui, -apple-system, sans-serif;
  font-size: 0.85rem;
  position: relative;
  overflow: hidden;
}

/* ============================================================================
   Feedback Toast
   ============================================================================ */

.gc-feedback-toast {
  position: absolute;
  top: 12px;
  right: 12px;
  z-index: 100;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 14px;
  border-radius: 6px;
  font-size: 0.8rem;
  font-weight: 500;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
  pointer-events: none;
}

.gc-feedback-toast.success {
  background: rgba(34, 197, 94, 0.15);
  border: 1px solid rgba(34, 197, 94, 0.4);
  color: var(--color-success, #22c55e);
}

.gc-feedback-toast.error {
  background: rgba(239, 68, 68, 0.15);
  border: 1px solid rgba(239, 68, 68, 0.4);
  color: var(--color-error, #ef4444);
}

.gc-feedback-toast.warning {
  background: rgba(245, 158, 11, 0.15);
  border: 1px solid rgba(245, 158, 11, 0.4);
  color: #f59e0b;
}

.gc-feedback-toast.info {
  background: rgba(59, 130, 246, 0.15);
  border: 1px solid rgba(59, 130, 246, 0.4);
  color: var(--color-accent, #3b82f6);
}

.gc-toast-icon {
  font-size: 1rem;
  line-height: 1;
}

.gc-toast-text {
  white-space: nowrap;
}

.gc-toast-enter-active,
.gc-toast-leave-active {
  transition: all 0.3s ease;
}

.gc-toast-enter-from,
.gc-toast-leave-to {
  opacity: 0;
  transform: translateY(-10px);
}

/* ============================================================================
   Left Sidebar
   ============================================================================ */

.gc-sidebar {
  width: 220px;
  min-width: 200px;
  max-width: 260px;
  display: flex;
  flex-direction: column;
  border-right: 1px solid var(--border-color, #2a2a4a);
  background: rgba(0, 0, 0, 0.15);
  overflow: hidden;
}

.gc-sidebar-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 14px 8px;
  border-bottom: 1px solid var(--border-color, #2a2a4a);
}

.gc-sidebar-title {
  font-size: 0.8rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: var(--text-secondary, #a0a0b0);
  margin: 0;
}

.gc-method-count {
  font-size: 0.7rem;
  font-weight: 600;
  background: rgba(59, 130, 246, 0.2);
  color: var(--color-accent, #3b82f6);
  padding: 1px 6px;
  border-radius: 8px;
  min-width: 18px;
  text-align: center;
}

.gc-sidebar-search {
  padding: 8px 10px;
}

.gc-search-input {
  width: 100%;
  padding: 5px 8px;
  background: rgba(0, 0, 0, 0.2);
  border: 1px solid var(--border-color, #2a2a4a);
  border-radius: 4px;
  color: var(--text-bright, #e2e8f0);
  font-size: 0.75rem;
  outline: none;
  box-sizing: border-box;
}

.gc-search-input::placeholder {
  color: var(--text-muted, #666680);
}

.gc-search-input:focus {
  border-color: var(--color-accent, #3b82f6);
}

.gc-method-list {
  flex: 1;
  overflow-y: auto;
  padding: 4px 0;
}

.gc-method-item {
  display: flex;
  flex-direction: column;
  padding: 8px 14px;
  cursor: pointer;
  border-left: 3px solid transparent;
  transition: all 0.15s ease;
}

.gc-method-item:hover {
  background: rgba(59, 130, 246, 0.08);
}

.gc-method-item.active {
  background: rgba(59, 130, 246, 0.12);
  border-left-color: var(--color-accent, #3b82f6);
}

.gc-method-item.dirty .gc-method-item-name::after {
  content: ' *';
  color: #f59e0b;
  font-weight: 700;
}

.gc-method-item-name {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.8rem;
  font-weight: 500;
  color: var(--text-bright, #e2e8f0);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.gc-method-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--text-muted, #666680);
  flex-shrink: 0;
}

.gc-method-dot.active-dot {
  background: var(--color-accent, #3b82f6);
  box-shadow: 0 0 4px rgba(59, 130, 246, 0.5);
}

.gc-method-item-meta {
  font-size: 0.65rem;
  color: var(--text-muted, #666680);
  margin-left: 12px;
  margin-top: 2px;
}

.gc-method-empty {
  padding: 20px 14px;
  text-align: center;
  font-size: 0.75rem;
  color: var(--text-muted, #666680);
  line-height: 1.5;
}

.gc-sidebar-actions {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 8px 10px;
  border-top: 1px solid var(--border-color, #2a2a4a);
}

.gc-btn-row {
  display: flex;
  gap: 4px;
}

.gc-btn-row .gc-btn {
  flex: 1;
}

/* ============================================================================
   Main Editor Panel
   ============================================================================ */

.gc-editor-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  overflow: hidden;
}

.gc-editor-content {
  flex: 1;
  overflow-y: auto;
  padding: 16px 20px;
  padding-bottom: 80px;
}

/* Empty state */
.gc-empty-state {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  color: var(--text-muted, #666680);
}

.gc-empty-icon {
  font-size: 2.5rem;
  opacity: 0.4;
}

.gc-empty-text {
  font-size: 0.9rem;
}

/* ============================================================================
   Editor Header
   ============================================================================ */

.gc-editor-header {
  display: flex;
  gap: 16px;
  align-items: flex-start;
  margin-bottom: 20px;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--border-color, #2a2a4a);
}

.gc-header-fields {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.gc-header-badges {
  display: flex;
  flex-direction: column;
  gap: 4px;
  align-items: flex-end;
  flex-shrink: 0;
}

.gc-badge {
  font-size: 0.65rem;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 10px;
  background: rgba(59, 130, 246, 0.1);
  color: var(--color-accent, #3b82f6);
  border: 1px solid rgba(59, 130, 246, 0.2);
  white-space: nowrap;
}

.gc-badge-dirty {
  background: rgba(245, 158, 11, 0.1);
  color: #f59e0b;
  border-color: rgba(245, 158, 11, 0.3);
}

/* ============================================================================
   Validation Banner
   ============================================================================ */

.gc-validation-banner {
  margin-bottom: 16px;
  padding: 10px 14px;
  background: rgba(239, 68, 68, 0.08);
  border: 1px solid rgba(239, 68, 68, 0.25);
  border-radius: 6px;
}

.gc-validation-header {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--color-error, #ef4444);
  margin-bottom: 6px;
}

.gc-validation-icon {
  font-size: 1rem;
}

.gc-validation-list {
  margin: 0;
  padding-left: 20px;
  font-size: 0.75rem;
  color: var(--color-error, #ef4444);
  opacity: 0.9;
  line-height: 1.6;
}

/* ============================================================================
   Sections (Collapsible)
   ============================================================================ */

.gc-section {
  margin-bottom: 16px;
  border: 1px solid var(--border-color, #2a2a4a);
  border-radius: 6px;
  overflow: hidden;
  background: rgba(0, 0, 0, 0.1);
}

.gc-section-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  cursor: pointer;
  background: rgba(0, 0, 0, 0.15);
  user-select: none;
  transition: background 0.15s;
}

.gc-section-header:hover {
  background: rgba(0, 0, 0, 0.25);
}

.gc-collapse-icon {
  font-size: 0.6rem;
  color: var(--text-muted, #666680);
  transition: transform 0.2s ease;
  line-height: 1;
}

.gc-collapse-icon.collapsed {
  transform: rotate(-90deg);
}

.gc-section-title {
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--text-bright, #e2e8f0);
  margin: 0;
  flex: 1;
}

.gc-section-badge {
  font-size: 0.65rem;
  color: var(--text-muted, #666680);
  background: rgba(255, 255, 255, 0.05);
  padding: 2px 8px;
  border-radius: 8px;
}

.gc-section-body {
  padding: 14px;
}

/* Collapse transition */
.gc-collapse-enter-active,
.gc-collapse-leave-active {
  transition: all 0.2s ease;
  overflow: hidden;
}

.gc-collapse-enter-from,
.gc-collapse-leave-to {
  opacity: 0;
  max-height: 0;
  padding-top: 0;
  padding-bottom: 0;
}

/* ============================================================================
   Form Controls
   ============================================================================ */

.gc-form-group {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.gc-form-group-name {
  max-width: 400px;
}

.gc-label {
  font-size: 0.7rem;
  font-weight: 600;
  color: var(--text-secondary, #a0a0b0);
  text-transform: uppercase;
  letter-spacing: 0.4px;
}

.gc-label-inline {
  text-transform: none;
  font-size: 0.75rem;
  white-space: nowrap;
}

.gc-input {
  padding: 6px 8px;
  background: rgba(0, 0, 0, 0.2);
  border: 1px solid var(--border-color, #2a2a4a);
  border-radius: 4px;
  color: var(--text-bright, #e2e8f0);
  font-size: 0.8rem;
  font-family: 'JetBrains Mono', 'Consolas', monospace;
  outline: none;
  transition: border-color 0.15s;
  box-sizing: border-box;
}

.gc-input:focus {
  border-color: var(--color-accent, #3b82f6);
}

.gc-input::placeholder {
  color: var(--text-muted, #666680);
}

.gc-input-name {
  font-size: 1rem;
  font-weight: 600;
  font-family: 'Inter', 'Segoe UI', system-ui, sans-serif;
}

.gc-input-num {
  width: 100px;
  text-align: right;
}

.gc-input-inline {
  padding: 3px 6px;
  font-size: 0.75rem;
}

.gc-input-inline.gc-input-num {
  width: 80px;
}

.gc-input-node {
  width: 120px;
}

.gc-input-node-override {
  width: 120px;
  font-size: 0.7rem;
  padding: 3px 6px;
  opacity: 0.7;
}

.gc-input-node-override:focus {
  opacity: 1;
}

.gc-textarea {
  padding: 6px 8px;
  background: rgba(0, 0, 0, 0.2);
  border: 1px solid var(--border-color, #2a2a4a);
  border-radius: 4px;
  color: var(--text-bright, #e2e8f0);
  font-size: 0.8rem;
  font-family: 'Inter', 'Segoe UI', system-ui, sans-serif;
  outline: none;
  resize: vertical;
  min-height: 40px;
  box-sizing: border-box;
}

.gc-textarea:focus {
  border-color: var(--color-accent, #3b82f6);
}

.gc-textarea::placeholder {
  color: var(--text-muted, #666680);
}

.gc-select {
  padding: 6px 8px;
  background: rgba(0, 0, 0, 0.2);
  border: 1px solid var(--border-color, #2a2a4a);
  border-radius: 4px;
  color: var(--text-bright, #e2e8f0);
  font-size: 0.8rem;
  outline: none;
  cursor: pointer;
  box-sizing: border-box;
}

.gc-select:focus {
  border-color: var(--color-accent, #3b82f6);
}

.gc-select-inline {
  padding: 3px 6px;
  font-size: 0.75rem;
}

.gc-select-sm {
  padding: 3px 6px;
  font-size: 0.75rem;
}

.gc-select-node {
  width: 120px;
  font-size: 0.75rem;
}

.gc-input-with-unit {
  display: flex;
  align-items: center;
  gap: 4px;
}

.gc-input-unit {
  font-size: 0.7rem;
  color: var(--text-muted, #666680);
  white-space: nowrap;
  min-width: 30px;
}

.gc-hint {
  font-size: 0.65rem;
  color: var(--text-muted, #666680);
  line-height: 1.3;
}

/* Parameter grid */
.gc-param-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 16px;
}

/* ============================================================================
   Buttons
   ============================================================================ */

.gc-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  padding: 6px 12px;
  border: 1px solid transparent;
  border-radius: 4px;
  font-size: 0.78rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s ease;
  white-space: nowrap;
  font-family: inherit;
}

.gc-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.gc-btn-primary {
  background: var(--color-accent, #3b82f6);
  color: #fff;
  border-color: var(--color-accent, #3b82f6);
}

.gc-btn-primary:hover:not(:disabled) {
  background: #2563eb;
}

.gc-btn-secondary {
  background: rgba(255, 255, 255, 0.06);
  color: var(--text-secondary, #a0a0b0);
  border-color: var(--border-color, #2a2a4a);
}

.gc-btn-secondary:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.12);
  color: var(--text-bright, #e2e8f0);
}

.gc-btn-danger {
  background: rgba(239, 68, 68, 0.1);
  color: var(--color-error, #ef4444);
  border-color: rgba(239, 68, 68, 0.3);
}

.gc-btn-danger:hover:not(:disabled) {
  background: rgba(239, 68, 68, 0.2);
}

.gc-btn-accent {
  background: rgba(34, 197, 94, 0.15);
  color: var(--color-success, #22c55e);
  border-color: rgba(34, 197, 94, 0.3);
}

.gc-btn-accent:hover:not(:disabled) {
  background: rgba(34, 197, 94, 0.25);
}

.gc-btn-sm {
  padding: 4px 8px;
  font-size: 0.72rem;
}

.gc-btn-xs {
  padding: 2px 6px;
  font-size: 0.68rem;
}

.gc-btn-full {
  width: 100%;
}

.gc-btn-link {
  background: none;
  border: none;
  color: var(--color-accent, #3b82f6);
  cursor: pointer;
  font-size: 0.72rem;
  padding: 2px 4px;
  border-radius: 3px;
  font-family: inherit;
  transition: background 0.15s;
}

.gc-btn-link:hover {
  background: rgba(59, 130, 246, 0.1);
}

.gc-btn-link.active {
  color: var(--color-success, #22c55e);
}

.gc-btn-add-cal {
  color: var(--text-muted, #666680);
  font-size: 0.68rem;
}

.gc-btn-add-cal:hover {
  color: var(--color-accent, #3b82f6);
}

.gc-btn-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: none;
  border: none;
  color: var(--text-muted, #666680);
  cursor: pointer;
  width: 22px;
  height: 22px;
  font-size: 0.65rem;
  border-radius: 3px;
  transition: all 0.15s;
  padding: 0;
  line-height: 1;
}

.gc-btn-icon:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.1);
  color: var(--text-bright, #e2e8f0);
}

.gc-btn-icon:disabled {
  opacity: 0.25;
  cursor: not-allowed;
}

.gc-btn-icon-danger:hover:not(:disabled) {
  background: rgba(239, 68, 68, 0.15);
  color: var(--color-error, #ef4444);
}

/* ============================================================================
   Toolbar
   ============================================================================ */

.gc-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}

/* ============================================================================
   Tables
   ============================================================================ */

.gc-table-container {
  overflow-x: auto;
}

.gc-table {
  width: 100%;
  border-collapse: collapse;
  border-spacing: 0;
  font-size: 0.78rem;
}

.gc-table-cal {
  font-size: 0.72rem;
}

.gc-th {
  padding: 6px 8px;
  text-align: left;
  font-size: 0.68rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.4px;
  color: var(--text-muted, #666680);
  border-bottom: 1px solid var(--border-color, #2a2a4a);
  white-space: nowrap;
}

.gc-th-narrow {
  width: 40px;
  text-align: center;
}

.gc-th-name {
  min-width: 120px;
}

.gc-th-num {
  width: 110px;
  text-align: right;
}

.gc-th-unit {
  width: 80px;
}

.gc-th-cal {
  width: 140px;
}

.gc-th-actions {
  width: 80px;
  text-align: center;
}

.gc-tr {
  border-bottom: 1px solid rgba(255, 255, 255, 0.04);
  transition: background 0.1s;
}

.gc-tr:hover {
  background: rgba(255, 255, 255, 0.03);
}

.gc-tr-expanded {
  background: rgba(59, 130, 246, 0.04);
}

.gc-td {
  padding: 4px 8px;
  vertical-align: middle;
}

.gc-td-narrow {
  text-align: center;
}

.gc-td-num {
  text-align: right;
}

.gc-td-actions {
  text-align: center;
}

.gc-td-sub {
  display: block;
  font-size: 0.6rem;
  color: var(--text-muted, #666680);
  text-align: right;
}

.gc-row-num {
  font-size: 0.65rem;
  color: var(--text-muted, #666680);
  font-weight: 600;
}

.gc-action-btns {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 2px;
}

/* ============================================================================
   Calibration Panel
   ============================================================================ */

.gc-tr-calibration {
  background: rgba(59, 130, 246, 0.03);
}

.gc-td-calibration-content {
  padding: 0 !important;
}

.gc-calibration-panel {
  margin: 0 12px 8px 30px;
  padding: 10px 14px;
  background: rgba(0, 0, 0, 0.12);
  border: 1px solid var(--border-color, #2a2a4a);
  border-radius: 4px;
}

.gc-calibration-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.gc-calibration-title {
  font-size: 0.72rem;
  font-weight: 600;
  color: var(--text-secondary, #a0a0b0);
  margin: 0;
}

.gc-calibration-controls {
  display: flex;
  align-items: center;
  gap: 6px;
}

.gc-cal-table-wrap {
  overflow-x: auto;
  margin-bottom: 8px;
}

.gc-cal-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.gc-cal-summary {
  font-size: 0.65rem;
  color: var(--text-muted, #666680);
}

.gc-cal-toggle {
  display: flex;
  align-items: center;
  gap: 4px;
}

.gc-expand-arrow {
  font-size: 0.5rem;
  transition: transform 0.2s ease;
}

.gc-expand-arrow.expanded {
  transform: rotate(180deg);
}

/* ============================================================================
   Info Box
   ============================================================================ */

.gc-info-box {
  margin-top: 12px;
  padding: 10px 12px;
  background: rgba(59, 130, 246, 0.06);
  border: 1px solid rgba(59, 130, 246, 0.15);
  border-radius: 4px;
  font-size: 0.7rem;
  color: var(--text-secondary, #a0a0b0);
  line-height: 1.5;
}

.gc-info-box strong {
  color: var(--text-bright, #e2e8f0);
}

/* ============================================================================
   Empty Section
   ============================================================================ */

.gc-empty-section {
  padding: 20px;
  text-align: center;
  font-size: 0.75rem;
  color: var(--text-muted, #666680);
  border: 1px dashed var(--border-color, #2a2a4a);
  border-radius: 4px;
}

/* ============================================================================
   Action Bar (bottom)
   ============================================================================ */

.gc-action-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 20px;
  border-top: 1px solid var(--border-color, #2a2a4a);
  background: rgba(0, 0, 0, 0.2);
  flex-shrink: 0;
}

.gc-action-bar-left {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.gc-action-bar-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.gc-push-group {
  display: flex;
  align-items: center;
  gap: 8px;
}

.gc-node-input-group {
  display: flex;
  align-items: center;
  gap: 4px;
}

.gc-push-status {
  font-size: 0.72rem;
  padding: 3px 8px;
  border-radius: 4px;
}

.gc-push-status.sending {
  color: var(--color-accent, #3b82f6);
  background: rgba(59, 130, 246, 0.1);
}

.gc-push-status.success {
  color: var(--color-success, #22c55e);
  background: rgba(34, 197, 94, 0.1);
}

.gc-push-status.error {
  color: var(--color-error, #ef4444);
  background: rgba(239, 68, 68, 0.1);
}

/* Spinner */
.gc-spinner {
  display: inline-block;
  width: 14px;
  height: 14px;
  border: 2px solid var(--color-success, #22c55e);
  border-top-color: transparent;
  border-radius: 50%;
  animation: gc-spin 0.6s linear infinite;
}

@keyframes gc-spin {
  to { transform: rotate(360deg); }
}

/* ============================================================================
   Light Mode Overrides
   ============================================================================ */

:root.light .gc-method-editor {
  background: #f8fafc;
  color: #1e293b;
}

:root.light .gc-sidebar {
  background: #f1f5f9;
  border-right-color: #e2e8f0;
}

:root.light .gc-sidebar-header {
  border-bottom-color: #e2e8f0;
}

:root.light .gc-sidebar-title {
  color: #64748b;
}

:root.light .gc-method-count {
  background: rgba(59, 130, 246, 0.1);
}

:root.light .gc-search-input {
  background: #fff;
  border-color: #d1d5db;
  color: #1e293b;
}

:root.light .gc-search-input::placeholder {
  color: #9ca3af;
}

:root.light .gc-method-item:hover {
  background: rgba(59, 130, 246, 0.06);
}

:root.light .gc-method-item.active {
  background: rgba(59, 130, 246, 0.08);
}

:root.light .gc-method-item-name {
  color: #1e293b;
}

:root.light .gc-method-dot {
  background: #9ca3af;
}

:root.light .gc-method-item-meta {
  color: #9ca3af;
}

:root.light .gc-sidebar-actions {
  border-top-color: #e2e8f0;
}

:root.light .gc-editor-header {
  border-bottom-color: #e2e8f0;
}

:root.light .gc-section {
  border-color: #e2e8f0;
  background: #fff;
}

:root.light .gc-section-header {
  background: #f9fafb;
}

:root.light .gc-section-header:hover {
  background: #f1f5f9;
}

:root.light .gc-section-title {
  color: #1e293b;
}

:root.light .gc-collapse-icon {
  color: #9ca3af;
}

:root.light .gc-section-badge {
  background: rgba(0, 0, 0, 0.04);
  color: #6b7280;
}

:root.light .gc-label {
  color: #4b5563;
}

:root.light .gc-input,
:root.light .gc-textarea,
:root.light .gc-select {
  background: #fff;
  border-color: #d1d5db;
  color: #1e293b;
}

:root.light .gc-input::placeholder,
:root.light .gc-textarea::placeholder {
  color: #9ca3af;
}

:root.light .gc-input-unit {
  color: #6b7280;
}

:root.light .gc-hint {
  color: #9ca3af;
}

:root.light .gc-th {
  color: #6b7280;
  border-bottom-color: #e2e8f0;
}

:root.light .gc-tr {
  border-bottom-color: #f3f4f6;
}

:root.light .gc-tr:hover {
  background: rgba(0, 0, 0, 0.02);
}

:root.light .gc-td-sub {
  color: #9ca3af;
}

:root.light .gc-row-num {
  color: #9ca3af;
}

:root.light .gc-calibration-panel {
  background: #fafbfc;
  border-color: #e2e8f0;
}

:root.light .gc-calibration-title {
  color: #4b5563;
}

:root.light .gc-cal-summary {
  color: #9ca3af;
}

:root.light .gc-info-box {
  background: rgba(59, 130, 246, 0.04);
  border-color: rgba(59, 130, 246, 0.12);
  color: #64748b;
}

:root.light .gc-info-box strong {
  color: #1e293b;
}

:root.light .gc-empty-section {
  border-color: #d1d5db;
  color: #9ca3af;
}

:root.light .gc-action-bar {
  border-top-color: #e2e8f0;
  background: #f9fafb;
}

:root.light .gc-badge {
  background: rgba(59, 130, 246, 0.06);
  border-color: rgba(59, 130, 246, 0.15);
}

:root.light .gc-badge-dirty {
  background: rgba(245, 158, 11, 0.06);
  border-color: rgba(245, 158, 11, 0.2);
}

:root.light .gc-validation-banner {
  background: rgba(239, 68, 68, 0.04);
  border-color: rgba(239, 68, 68, 0.15);
}

:root.light .gc-btn-secondary {
  background: rgba(0, 0, 0, 0.04);
  color: #4b5563;
  border-color: #d1d5db;
}

:root.light .gc-btn-secondary:hover:not(:disabled) {
  background: rgba(0, 0, 0, 0.08);
  color: #1e293b;
}

:root.light .gc-btn-icon {
  color: #9ca3af;
}

:root.light .gc-btn-icon:hover:not(:disabled) {
  background: rgba(0, 0, 0, 0.05);
  color: #1e293b;
}

:root.light .gc-btn-link {
  color: var(--color-accent, #3b82f6);
}

:root.light .gc-btn-add-cal {
  color: #9ca3af;
}

:root.light .gc-method-empty {
  color: #9ca3af;
}

:root.light .gc-empty-state {
  color: #9ca3af;
}

:root.light .gc-empty-icon {
  opacity: 0.3;
}

:root.light .gc-feedback-toast.success {
  background: rgba(34, 197, 94, 0.08);
  border-color: rgba(34, 197, 94, 0.25);
}

:root.light .gc-feedback-toast.error {
  background: rgba(239, 68, 68, 0.08);
  border-color: rgba(239, 68, 68, 0.25);
}

:root.light .gc-feedback-toast.warning {
  background: rgba(245, 158, 11, 0.08);
  border-color: rgba(245, 158, 11, 0.25);
}

:root.light .gc-feedback-toast.info {
  background: rgba(59, 130, 246, 0.08);
  border-color: rgba(59, 130, 246, 0.25);
}

:root.light .gc-push-status.sending {
  background: rgba(59, 130, 246, 0.06);
}

:root.light .gc-push-status.success {
  background: rgba(34, 197, 94, 0.06);
}

:root.light .gc-push-status.error {
  background: rgba(239, 68, 68, 0.06);
}
</style>
