import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'
import { useWindowSync } from '../composables/useWindowSync'
import type {
  ChannelConfig,
  ChannelValue,
  SystemStatus,
  WidgetConfig,
  LayoutConfig,
  WidgetType,
  WidgetStyle,
  DashboardPage,
  PipeConnection,
  PipePoint,
  PidLayerData,
  PidSymbol,
  PidPipe,
  PidPoint,
  PidTextAnnotation,
  PidCommand,
  PidGroup,
  PidTemplate,
  PidLayerInfo,
  BackendRecordingConfig,
} from '../types'

// Recording configuration interface
export interface RecordingConfig {
  basePath: string
  filePrefix: string
  fileFormat: 'csv' | 'tdms'
  sampleInterval: number
  sampleIntervalUnit: 'seconds' | 'milliseconds'
  decimation: number
  rotationMode: 'single' | 'time' | 'size' | 'samples' | 'session'
  maxFileSize: number
  maxFileDuration: number
  maxFileSamples: number
  namingPattern: 'timestamp' | 'sequential' | 'custom'
  includeDate: boolean
  includeTime: boolean
  includeChannelsInName: boolean
  sequentialStart: number
  sequentialPadding: number
  customSuffix: string
  directoryStructure: 'flat' | 'daily' | 'monthly' | 'experiment'
  experimentName: string
  writeMode: 'immediate' | 'buffered'
  bufferSize: number
  flushInterval: number
  onLimitReached: 'new_file' | 'stop' | 'circular'
  circularMaxFiles: number
  mode: 'manual' | 'triggered' | 'scheduled'
  triggerChannel: string
  triggerCondition: 'above' | 'below' | 'change'
  triggerValue: number
  preTriggerSamples: number
  postTriggerSamples: number
  scheduleEnabled: boolean
  scheduleStart: string
  scheduleEnd: string
  scheduleDays: string[]

  // CSV file recording toggle
  csvEnabled: boolean

  // File Reuse
  reuseFile: boolean            // Stop/start appends to same file instead of creating new

  // ALCOA+ Data Integrity Settings
  appendOnly: boolean           // Make files read-only after recording stops
  verifyOnClose: boolean        // Create SHA-256 integrity files
  includeAuditMetadata: boolean // Include operator, timestamps, session info

  // PostgreSQL Database Storage (optional, alongside file recording)
  dbEnabled: boolean
  dbHost: string
  dbPort: number
  dbName: string
  dbUser: string
  dbPassword: string
  dbTable: string
  dbBatchSize: number
  dbTimescale: boolean  // Enable TimescaleDB hypertable
}

const DEFAULT_RECORDING_CONFIG: RecordingConfig = {
  basePath: './data',
  filePrefix: 'recording',
  fileFormat: 'csv',
  sampleInterval: 1,
  sampleIntervalUnit: 'seconds',
  decimation: 1,
  rotationMode: 'single',
  maxFileSize: 100,
  maxFileDuration: 3600,
  maxFileSamples: 10000,
  namingPattern: 'timestamp',
  includeDate: true,
  includeTime: true,
  includeChannelsInName: false,
  sequentialStart: 1,
  sequentialPadding: 3,
  customSuffix: '',
  directoryStructure: 'flat',
  experimentName: '',
  writeMode: 'buffered',
  bufferSize: 100,
  flushInterval: 5.0,
  onLimitReached: 'new_file',
  circularMaxFiles: 10,
  mode: 'manual',
  triggerChannel: '',
  triggerCondition: 'above',
  triggerValue: 0,
  preTriggerSamples: 100,
  postTriggerSamples: 1000,
  scheduleEnabled: false,
  scheduleStart: '08:00',
  scheduleEnd: '17:00',
  scheduleDays: ['mon', 'tue', 'wed', 'thu', 'fri'],

  // CSV file recording (enabled by default for new projects)
  csvEnabled: true,

  // File Reuse
  reuseFile: false,            // Off by default — each start creates a new file

  // ALCOA+ Data Integrity Settings (FDA 21 CFR Part 11 compliance)
  appendOnly: false,           // Off by default for development flexibility
  verifyOnClose: true,         // On by default - creates integrity checksums
  includeAuditMetadata: true,  // On by default - includes operator attribution

  // PostgreSQL Database Storage (disabled by default)
  dbEnabled: false,
  dbHost: 'localhost',
  dbPort: 5432,
  dbName: 'iccsflux',
  dbUser: 'iccsflux',
  dbPassword: '',
  dbTable: 'recording_data',
  dbBatchSize: 50,
  dbTimescale: false
}

/**
 * Convert frontend RecordingConfig (camelCase) to backend format (snake_case).
 * Single source of truth for the field mapping — used by DataTab.startRecording()
 * and anywhere else that sends config to the backend.
 */
export function toBackendRecordingConfig(
  cfg: RecordingConfig,
  selectedChannels: string[],
  selectAll: boolean,
): BackendRecordingConfig {
  return {
    base_path: cfg.basePath,
    file_prefix: cfg.filePrefix,
    file_format: cfg.fileFormat,
    sample_interval: cfg.sampleInterval,
    sample_interval_unit: cfg.sampleIntervalUnit,
    decimation: 1,  // Decimation handled by sample interval — always send 1
    rotation_mode: cfg.rotationMode,
    max_file_size_mb: cfg.maxFileSize,
    max_file_duration_s: cfg.maxFileDuration,
    max_file_samples: cfg.maxFileSamples,
    naming_pattern: cfg.namingPattern,
    include_date: cfg.includeDate,
    include_time: cfg.includeTime,
    include_channels_in_name: cfg.includeChannelsInName,
    sequential_start: cfg.sequentialStart,
    sequential_padding: cfg.sequentialPadding,
    custom_suffix: cfg.customSuffix,
    directory_structure: cfg.directoryStructure,
    experiment_name: cfg.experimentName,
    write_mode: cfg.writeMode,
    buffer_size: cfg.bufferSize,
    flush_interval_s: cfg.flushInterval,
    on_limit_reached: cfg.onLimitReached,
    circular_max_files: cfg.circularMaxFiles,
    mode: cfg.mode,
    selected_channels: selectAll ? [] : selectedChannels,
    include_scripts: true,
    trigger_channel: cfg.triggerChannel,
    trigger_condition: cfg.triggerCondition,
    trigger_value: cfg.triggerValue,
    pre_trigger_samples: cfg.preTriggerSamples,
    post_trigger_samples: cfg.postTriggerSamples,
    schedule_start: cfg.scheduleStart,
    schedule_end: cfg.scheduleEnd,
    schedule_days: cfg.scheduleDays,
    reuse_file: cfg.reuseFile,
    append_only: cfg.appendOnly,
    verify_on_close: cfg.verifyOnClose,
    include_audit_metadata: cfg.includeAuditMetadata,
    db_enabled: cfg.dbEnabled,
    db_host: cfg.dbHost,
    db_port: cfg.dbPort,
    db_name: cfg.dbName,
    db_user: cfg.dbUser,
    db_password: cfg.dbPassword,
    db_table: cfg.dbTable,
    db_batch_size: cfg.dbBatchSize,
    db_timescale: cfg.dbTimescale,
  }
}

export const useDashboardStore = defineStore('dashboard', () => {
  // System state
  const systemId = ref<string>('default')
  const systemName = ref<string>('ICCSFlux')
  const mqttPrefix = ref<string>('nisystem')

  // Channel data
  const channels = ref<Record<string, ChannelConfig>>({})
  const values = ref<Record<string, ChannelValue>>({})
  const status = ref<SystemStatus | null>(null)

  // Multi-page dashboard state
  const pages = ref<DashboardPage[]>([])
  const currentPageId = ref<string>('default')
  const layoutVersion = ref(0)  // Increments on setLayout to force widget re-render
  const editMode = ref(false)   // Must be declared before windowSync handlers use it

  // Legacy: widgets ref for backward compatibility (maps to current page)
  const widgets = computed({
    get: () => {
      const page = pages.value.find(p => p.id === currentPageId.value)
      if (!page && pages.value.length > 0) {
        // currentPageId doesn't match any page - auto-correct to first page
        console.warn('[STORE] currentPageId mismatch, correcting to first page')
        currentPageId.value = pages.value[0]!.id
        return pages.value[0]!.widgets || []
      }
      return page?.widgets || []
    },
    set: (newWidgets: WidgetConfig[]) => {
      const pageIndex = pages.value.findIndex(p => p.id === currentPageId.value)
      if (pageIndex !== -1) {
        pages.value[pageIndex]!.widgets = newWidgets
      }
    }
  })

  // Pipes for current page (P&ID connections)
  const pipes = computed({
    get: () => {
      const page = pages.value.find(p => p.id === currentPageId.value)
      return page?.pipes || []
    },
    set: (newPipes: PipeConnection[]) => {
      const pageIndex = pages.value.findIndex(p => p.id === currentPageId.value)
      if (pageIndex !== -1) {
        if (!pages.value[pageIndex]!.pipes) {
          pages.value[pageIndex]!.pipes = []
        }
        pages.value[pageIndex]!.pipes = newPipes
      }
    }
  })

  // Pipe drawing mode state (legacy grid-based)
  const pipeDrawingMode = ref(false)
  const pipeDrawingStart = ref<{ widgetId?: string; port?: string; point?: PipePoint } | null>(null)

  // P&ID Canvas Layer (free-form, pixel-based)
  const pidEditMode = ref(false)  // Separate edit mode for P&ID layer
  const pidDrawingMode = ref(false)  // Free-form pipe drawing mode
  const pidGridSnapEnabled = ref(true)  // Snap to grid toggle (default ON)
  const pidGridSize = ref(10)  // Grid cell size in pixels (finer than widget grid, snaps ports)
  const pidShowGrid = ref(true)  // Show grid overlay (default ON)
  const pidColorScheme = ref<'standard' | 'isa101'>('standard')  // ISA-101 grayscale mode
  const pidOrthogonalPipes = ref(true)  // Draw pipes at 90-degree angles only (Shift to disable)
  // Pipe drawing defaults (shared between toolbar and canvas)
  const pidPipeColor = ref('#60a5fa')
  const pidPipeDashed = ref(false)
  const pidPipeAnimated = ref(false)
  // Style clipboard for copy/paste style between pipes
  const pidStyleClipboard = ref<Partial<PidPipe> | null>(null)

  function pidCopyStyle(pipeId: string) {
    const pipe = pidLayer.value.pipes.find(p => p.id === pipeId)
    if (!pipe) return
    pidStyleClipboard.value = {
      color: pipe.color,
      strokeWidth: pipe.strokeWidth,
      dashed: pipe.dashed,
      dashPattern: pipe.dashPattern,
      opacity: pipe.opacity,
      animated: pipe.animated,
      startArrow: pipe.startArrow,
      endArrow: pipe.endArrow,
      rounded: pipe.rounded,
      cornerRadius: pipe.cornerRadius,
      medium: pipe.medium,
      lineCode: pipe.lineCode,
      jumpStyle: pipe.jumpStyle,
      jumpSize: pipe.jumpSize,
    }
  }

  function pidPasteStyle(pipeId: string) {
    if (!pidStyleClipboard.value) return
    const beforeState = createPidStateSnapshot()
    updatePidPipe(pipeId, { ...pidStyleClipboard.value })
    pushPidCommand('modify', 'Paste pipe style', beforeState)
  }

  // P&ID Zoom/Pan (edit-mode only)
  const pidZoom = ref(1)
  const pidPanX = ref(0)
  const pidPanY = ref(0)
  const pidSymbolPanelOpen = ref(true)  // Symbol panel sidebar
  const pidShowMinimap = ref(true)      // Minimap overlay
  const pidShowRulers = ref(true)       // Ruler overlays on canvas edges
  const pidAutoRoute = ref(false)       // Auto-route pipes around obstacles
  const pidPropertiesPanelOpen = ref(true) // Properties panel sidebar

  // P&ID Nozzle stubs
  const pidShowNozzleStubs = ref(true)

  // P&ID Panel collapse & resize
  const pidSymbolPanelCollapsed = ref(false)
  const pidPropertiesPanelCollapsed = ref(false)
  const pidSymbolPanelWidth = ref(220)
  const pidPropertiesPanelWidth = ref(240)

  // P&ID Custom symbols (#4.1)
  interface CustomSymbolDef {
    svg: string
    name: string
    category: string
    ports: Array<{ id: string; x: number; y: number; direction: 'left' | 'right' | 'top' | 'bottom' }>
  }
  const pidCustomSymbols = ref<Record<string, CustomSymbolDef>>(
    JSON.parse(localStorage.getItem('pid-custom-symbols') || '{}')
  )

  function pidAddCustomSymbol(id: string, def: CustomSymbolDef) {
    pidCustomSymbols.value = { ...pidCustomSymbols.value, [id]: def }
    localStorage.setItem('pid-custom-symbols', JSON.stringify(pidCustomSymbols.value))
  }

  function pidRemoveCustomSymbol(id: string) {
    const copy = { ...pidCustomSymbols.value }
    delete copy[id]
    pidCustomSymbols.value = copy
    localStorage.setItem('pid-custom-symbols', JSON.stringify(pidCustomSymbols.value))
  }

  // P&ID Favorite & Recent symbols (#3.4)
  const pidFavoriteSymbols = ref<string[]>(JSON.parse(localStorage.getItem('pid-favorites') || '[]'))
  const pidRecentSymbols = ref<string[]>(JSON.parse(localStorage.getItem('pid-recent') || '[]'))

  function pidToggleFavorite(type: string) {
    const idx = pidFavoriteSymbols.value.indexOf(type)
    if (idx >= 0) {
      pidFavoriteSymbols.value = pidFavoriteSymbols.value.filter(t => t !== type)
    } else {
      pidFavoriteSymbols.value = [...pidFavoriteSymbols.value, type]
    }
    localStorage.setItem('pid-favorites', JSON.stringify(pidFavoriteSymbols.value))
  }

  function pidTrackRecentSymbol(type: string) {
    const filtered = pidRecentSymbols.value.filter(t => t !== type)
    pidRecentSymbols.value = [type, ...filtered].slice(0, 10)
    localStorage.setItem('pid-recent', JSON.stringify(pidRecentSymbols.value))
  }

  // P&ID Operator Notes (#6.6) — session-scoped sticky notes (localStorage, not project file)
  interface PidOperatorNote {
    id: string
    x: number
    y: number
    text: string
    color: string
    author: string
    timestamp: number
  }
  const pidOperatorNotes = ref<PidOperatorNote[]>(JSON.parse(localStorage.getItem('pid-operator-notes') || '[]'))

  function pidAddOperatorNote(x: number, y: number, text: string, color = '#fbbf24', author = 'Operator') {
    const note: PidOperatorNote = {
      id: `note-${Date.now()}-${Math.random().toString(36).slice(2, 5)}`,
      x, y, text, color, author,
      timestamp: Date.now(),
    }
    pidOperatorNotes.value = [...pidOperatorNotes.value, note]
    localStorage.setItem('pid-operator-notes', JSON.stringify(pidOperatorNotes.value))
    return note.id
  }

  function pidUpdateOperatorNote(id: string, updates: Partial<Omit<PidOperatorNote, 'id'>>) {
    pidOperatorNotes.value = pidOperatorNotes.value.map(n =>
      n.id === id ? { ...n, ...updates } : n
    )
    localStorage.setItem('pid-operator-notes', JSON.stringify(pidOperatorNotes.value))
  }

  function pidRemoveOperatorNote(id: string) {
    pidOperatorNotes.value = pidOperatorNotes.value.filter(n => n.id !== id)
    localStorage.setItem('pid-operator-notes', JSON.stringify(pidOperatorNotes.value))
  }

  function pidClearOperatorNotes() {
    pidOperatorNotes.value = []
    localStorage.removeItem('pid-operator-notes')
  }

  // P&ID Focus mode
  const pidFocusMode = ref(false)
  const pidToolbarCompact = ref(false)
  const pidFocusModePrevState = ref<{
    symbolPanelOpen: boolean
    symbolPanelCollapsed: boolean
    propertiesPanelOpen: boolean
    propertiesPanelCollapsed: boolean
    showMinimap: boolean
    showRulers: boolean
    showGrid: boolean
  } | null>(null)

  // ========================================================================
  // P&ID TEMPLATE LIBRARY
  // ========================================================================
  const pidTemplates = ref<PidTemplate[]>([])
  const PID_TEMPLATES_KEY = 'nisystem-pid-templates'

  // Load templates from localStorage
  function loadPidTemplates() {
    try {
      const saved = localStorage.getItem(PID_TEMPLATES_KEY)
      if (saved) {
        pidTemplates.value = JSON.parse(saved)
      }
    } catch (e) {
      console.error('[STORE] Failed to load P&ID templates:', e)
    }
  }

  // Save templates to localStorage
  function savePidTemplates() {
    try {
      localStorage.setItem(PID_TEMPLATES_KEY, JSON.stringify(pidTemplates.value))
    } catch (e) {
      console.error('[STORE] Failed to save P&ID templates:', e)
    }
  }

  // Load templates on init
  loadPidTemplates()

  // ========================================================================
  // P&ID UNDO/REDO SYSTEM (Command Pattern)
  // ========================================================================
  const pidUndoStack = ref<PidCommand[]>([])
  const pidRedoStack = ref<PidCommand[]>([])
  const PID_MAX_UNDO_STACK = 50  // Limit stack size to prevent memory issues

  // ========================================================================
  // P&ID CLIPBOARD (Copy/Paste)
  // ========================================================================
  const pidClipboard = ref<{
    symbols: PidSymbol[]
    pipes: PidPipe[]
    textAnnotations: PidTextAnnotation[]
  } | null>(null)

  // ========================================================================
  // P&ID SELECTION STATE (Multi-Select)
  // ========================================================================
  const pidSelectedIds = ref<{
    symbolIds: string[]
    pipeIds: string[]
    textAnnotationIds: string[]
  }>({ symbolIds: [], pipeIds: [], textAnnotationIds: [] })

  // Computed: Check if anything is selected
  const hasPidSelection = computed(() =>
    pidSelectedIds.value.symbolIds.length > 0 ||
    pidSelectedIds.value.pipeIds.length > 0 ||
    pidSelectedIds.value.textAnnotationIds.length > 0
  )

  // ========================================================================
  // CROSS-WINDOW SYNC (Multi-Monitor Support)
  // ========================================================================
  const windowSync = useWindowSync()

  // Initialize window sync
  windowSync.init()

  // Listen for layout updates from other windows
  windowSync.onLayoutUpdate((newPages: DashboardPage[]) => {
    console.log('[STORE] Received layout update from another window')
    pages.value = newPages
    layoutVersion.value++
  })

  // Listen for edit mode changes from other windows
  windowSync.onEditModeChange((enabled: boolean) => {
    console.log('[STORE] Received edit mode change from another window:', enabled)
    editMode.value = enabled
  })

  // Watch for local layout changes and broadcast to other windows
  watch(pages, (newPages) => {
    if (!windowSync.isReceiving()) {
      windowSync.broadcastLayoutUpdate(JSON.parse(JSON.stringify(newPages)))
    }
  }, { deep: true })

  // Watch for edit mode changes and broadcast
  watch(editMode, (enabled) => {
    if (!windowSync.isReceiving()) {
      windowSync.broadcastEditMode(enabled)
    }
  })

  // P&ID layer for current page
  const pidLayer = computed({
    get: (): PidLayerData => {
      const page = pages.value.find(p => p.id === currentPageId.value)
      return page?.pidLayer || { symbols: [], pipes: [], visible: true, opacity: 1 }
    },
    set: (newLayer: PidLayerData) => {
      const page = pages.value.find(p => p.id === currentPageId.value)
      if (page) {
        page.pidLayer = newLayer
        saveLayoutToStorage()
      }
    }
  })

  // Grid settings
  const gridColumns = ref(24)  // 24 columns for finer control (was 12)
  const rowHeight = ref(30)    // Smaller row height to match (was 60)

  // ========================================================================
  // RECORDING CONFIGURATION (Data tab)
  // ========================================================================
  const recordingConfig = ref<RecordingConfig>({ ...DEFAULT_RECORDING_CONFIG })
  const selectedRecordingChannels = ref<string[]>([])
  const selectAllRecordingChannels = ref(true)

  // Chart state (max 2 charts per page)
  const maxCharts = 2

  // Computed
  const channelsByGroup = computed(() => {
    const groups: Record<string, ChannelConfig[]> = {}

    Object.values(channels.value).forEach(ch => {
      const group = ch.group || 'Ungrouped'
      if (!groups[group]) groups[group] = []
      groups[group].push(ch)
    })

    return groups
  })

  // Visible channels only (for widget dropdowns)
  const visibleChannels = computed(() => {
    return Object.values(channels.value).filter(ch => ch.visible !== false)
  })

  const visibleChannelsByGroup = computed(() => {
    const groups: Record<string, ChannelConfig[]> = {}

    visibleChannels.value.forEach(ch => {
      const group = ch.group || 'Ungrouped'
      if (!groups[group]) groups[group] = []
      groups[group].push(ch)
    })

    return groups
  })

  const chartWidgets = computed(() =>
    widgets.value.filter(w => w.type === 'chart')
  )

  const canAddChart = computed(() =>
    chartWidgets.value.length < maxCharts
  )

  const isAcquiring = computed(() => status.value?.acquiring ?? false)
  const isRecording = computed(() => status.value?.recording ?? false)
  const isSchedulerEnabled = computed(() => status.value?.scheduler_enabled ?? false)
  const isConnected = computed(() => status.value?.status === 'online')

  // Actions
  function setChannels(channelConfigs: Record<string, ChannelConfig>) {
    channels.value = channelConfigs
  }

  function updateValues(newValues: Record<string, number>) {
    const timestamp = Date.now()

    Object.entries(newValues).forEach(([name, value]) => {
      const config = channels.value[name]

      values.value[name] = {
        name,
        value,
        timestamp,
        alarm: config ? checkAlarm(value, config) : false,
        warning: config ? checkWarning(value, config) : false
      }
    })
  }

  function checkAlarm(value: number, config: ChannelConfig): boolean {
    // Use != null to check both undefined AND null
    if (config.low_limit != null && value < config.low_limit) return true
    if (config.high_limit != null && value > config.high_limit) return true
    return false
  }

  function checkWarning(value: number, config: ChannelConfig): boolean {
    // Use != null to check both undefined AND null
    if (config.low_warning != null && value < config.low_warning) return true
    if (config.high_warning != null && value > config.high_warning) return true
    return false
  }

  // Update values from scripts (calculated params, transformations)
  function updateScriptValues(scriptValues: Record<string, { value: number; name: string }>) {
    const timestamp = Date.now()

    Object.entries(scriptValues).forEach(([name, data]) => {
      // Add to values so widgets can bind to them
      values.value[name] = {
        name,
        value: data.value,
        timestamp,
        alarm: false,
        warning: false
      }

      // Add virtual channel config if not exists
      if (!channels.value[name]) {
        channels.value[name] = {
          name,  // TAG is the only identifier
          channel_type: 'script',
          unit: '',
          group: 'Scripts',
          enabled: true
        }
      }
    })
  }

  function setStatus(newStatus: SystemStatus) {
    status.value = newStatus
  }

  function setSystemInfo(id: string, name: string, prefix: string) {
    systemId.value = id
    systemName.value = name
    mqttPrefix.value = prefix
  }

  // ========================================================================
  // PAGE MANAGEMENT
  // ========================================================================

  const currentPage = computed(() =>
    pages.value.find(p => p.id === currentPageId.value)
  )

  const sortedPages = computed(() =>
    [...pages.value].sort((a, b) => a.order - b.order)
  )

  function ensureDefaultPage() {
    if (pages.value.length === 0) {
      pages.value.push({
        id: 'default',
        name: 'Page 1',
        widgets: [],
        order: 0,
        createdAt: new Date().toISOString()
      })
      currentPageId.value = 'default'
    }
  }

  function addPage(name?: string): string {
    const id = `page-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`
    const order = pages.value.length
    const pageName = name || `Page ${order + 1}`

    pages.value.push({
      id,
      name: pageName,
      widgets: [],
      order,
      createdAt: new Date().toISOString()
    })

    return id
  }

  function removePage(pageId: string) {
    // Can't remove last page
    if (pages.value.length <= 1) return false

    const index = pages.value.findIndex(p => p.id === pageId)
    if (index === -1) return false

    pages.value.splice(index, 1)

    // If we removed the current page, switch to first available
    if (currentPageId.value === pageId) {
      currentPageId.value = pages.value[0]?.id || 'default'
    }

    // Reorder remaining pages
    pages.value.forEach((p, i) => p.order = i)

    saveLayoutToStorage()
    return true
  }

  function renamePage(pageId: string, newName: string) {
    const page = pages.value.find(p => p.id === pageId)
    if (page) {
      page.name = newName.trim() || `Page ${page.order + 1}`
    }
  }

  function switchPage(pageId: string) {
    if (pages.value.some(p => p.id === pageId)) {
      currentPageId.value = pageId
    }
  }

  function duplicatePage(pageId: string): string | null {
    const source = pages.value.find(p => p.id === pageId)
    if (!source) return null

    const id = `page-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`
    const newWidgets = source.widgets.map(w => ({
      ...w,
      id: `widget-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`
    }))

    pages.value.push({
      id,
      name: `${source.name} (copy)`,
      widgets: newWidgets,
      order: pages.value.length,
      createdAt: new Date().toISOString(),
      ...(source.pidLayer ? { pidLayer: JSON.parse(JSON.stringify(source.pidLayer)) } : {})
    })

    saveLayoutToStorage()
    return id
  }

  function movePage(pageId: string, direction: 'up' | 'down') {
    const index = pages.value.findIndex(p => p.id === pageId)
    if (index === -1) return

    const newIndex = direction === 'up' ? index - 1 : index + 1
    if (newIndex < 0 || newIndex >= pages.value.length) return

    // Swap orders
    const currentPage = pages.value[index]
    const targetPage = pages.value[newIndex]
    if (!currentPage || !targetPage) return

    const temp = currentPage.order
    currentPage.order = targetPage.order
    targetPage.order = temp
  }

  /**
   * Set ISA-101 display hierarchy level for a page
   */
  function setPageHierarchyLevel(pageId: string, level: 'L1' | 'L2' | 'L3' | 'L4' | undefined) {
    const page = pages.value.find(p => p.id === pageId)
    if (page) {
      page.hierarchyLevel = level
      saveLayoutToStorage()
    }
  }

  /**
   * Link a page to a parent page (for navigation)
   */
  function setPageParent(pageId: string, parentId: string | undefined) {
    const page = pages.value.find(p => p.id === pageId)
    if (page) {
      if (!page.linkedPages) page.linkedPages = {}
      page.linkedPages.parentId = parentId
      saveLayoutToStorage()
    }
  }

  /**
   * Get pages by hierarchy level
   */
  function getPagesByLevel(level: 'L1' | 'L2' | 'L3' | 'L4') {
    return pages.value.filter(p => p.hierarchyLevel === level)
  }

  /**
   * Get child pages linked to a parent
   */
  function getChildPages(parentId: string) {
    return pages.value.filter(p => p.linkedPages?.parentId === parentId)
  }

  // ========================================================================
  // WIDGET ACTIONS (operate on current page)
  // ========================================================================

  function addWidget(widget: Omit<WidgetConfig, 'id'>) {
    ensureDefaultPage()
    const page = pages.value.find(p => p.id === currentPageId.value)
    if (!page) return null

    const id = `widget-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`

    // Check chart limit per page
    if (widget.type === 'chart' && !canAddChart.value) {
      console.warn('Maximum number of charts reached')
      return null
    }

    const newWidget: WidgetConfig = { id, ...widget }
    page.widgets.push(newWidget)
    return id
  }

  function removeWidget(widgetId: string) {
    const page = pages.value.find(p => p.id === currentPageId.value)
    if (!page) return

    const index = page.widgets.findIndex(w => w.id === widgetId)
    if (index !== -1) {
      page.widgets.splice(index, 1)
    }
  }

  function moveWidgetToPage(widgetId: string, targetPageId: string): boolean {
    if (currentPageId.value === targetPageId) return false

    const sourcePage = pages.value.find(p => p.id === currentPageId.value)
    const targetPage = pages.value.find(p => p.id === targetPageId)
    if (!sourcePage || !targetPage) return false

    const widgetIndex = sourcePage.widgets.findIndex(w => w.id === widgetId)
    if (widgetIndex === -1) return false

    // Remove from source and add to target
    const [widget] = sourcePage.widgets.splice(widgetIndex, 1)
    if (widget) {
      // Reset position to avoid overlap on target page
      widget.x = 0
      widget.y = targetPage.widgets.reduce((maxY, w) => Math.max(maxY, w.y + w.h), 0)
      targetPage.widgets.push(widget)
    }

    return true
  }

  function copyWidgetToPage(widgetId: string, targetPageId: string): boolean {
    const sourcePage = pages.value.find(p => p.id === currentPageId.value)
    const targetPage = pages.value.find(p => p.id === targetPageId)
    if (!sourcePage || !targetPage) return false

    const widget = sourcePage.widgets.find(w => w.id === widgetId)
    if (!widget) return false

    // Create a copy with new ID
    const newWidget: WidgetConfig = {
      ...widget,
      id: `widget-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
      x: 0,
      y: targetPage.widgets.reduce((maxY, w) => Math.max(maxY, w.y + w.h), 0)
    }
    targetPage.widgets.push(newWidget)

    return true
  }

  function updateWidget(widgetId: string, updates: Partial<WidgetConfig>) {
    const page = pages.value.find(p => p.id === currentPageId.value)
    if (!page) return

    const widget = page.widgets.find(w => w.id === widgetId)
    if (widget) {
      Object.assign(widget, updates)
    }
  }

  function updateWidgetPosition(widgetId: string, x: number, y: number, w: number, h: number) {
    updateWidget(widgetId, { x, y, w, h })
  }

  function setEditMode(enabled: boolean) {
    editMode.value = enabled
  }

  function toggleEditMode() {
    editMode.value = !editMode.value
  }

  /**
   * Auto-generate widgets for all visible channels based on channel type.
   * Creates a sensible default widget for each channel type:
   * - Analog inputs (thermocouple, rtd, voltage, etc.) → numeric display
   * - Digital inputs → LED indicator
   * - Digital outputs → toggle switch
   * - Analog outputs → setpoint control
   * - Counters → numeric display
   *
   * Widgets are arranged in a grid layout automatically.
   *
   * @param options Configuration for auto-generation
   * @returns Number of widgets created
   */
  function autoGenerateWidgets(options?: {
    channelFilter?: (channel: ChannelConfig) => boolean  // Optional filter function
    widgetSize?: 'compact' | 'normal' | 'large'          // Size preset (default: compact)
    columns?: number                                     // Grid columns (default 4)
  }): number {
    ensureDefaultPage()
    const page = pages.value.find(p => p.id === currentPageId.value)
    if (!page) return 0

    const opts = {
      widgetSize: 'compact',
      columns: 4,
      ...options
    }

    // Get all visible channels
    const channelsToAdd = Object.values(channels.value).filter(ch => {
      // Skip invisible channels
      if (ch.visible === false) return false
      // Apply custom filter if provided
      if (opts.channelFilter && !opts.channelFilter(ch)) return false
      return true
    })

    if (channelsToAdd.length === 0) {
      console.warn('[AUTO-WIDGETS] No visible channels to create widgets for')
      return 0
    }

    // Map channel type to widget type
    function getWidgetTypeForChannel(channel: ChannelConfig): WidgetType {
      switch (channel.channel_type) {
        // Analog inputs → numeric display
        case 'thermocouple':
        case 'rtd':
        case 'voltage':
        case 'current':
        case 'strain':
        case 'iepe':
        case 'resistance':
        case 'modbus_register':
        case 'counter':
          return 'numeric'

        // Digital inputs → LED indicator
        case 'digital_input':
        case 'modbus_coil':
          return 'led'

        // Digital outputs → toggle switch
        case 'digital_output':
          return 'toggle'

        // Analog outputs → setpoint control
        case 'analog_output':
          return 'setpoint'

        // Default fallback
        default:
          return 'numeric'
      }
    }

    // Get widget size based on preset
    function getWidgetSize(type: WidgetType): { w: number; h: number } {
      const sizes: Record<string, Record<string, { w: number; h: number }>> = {
        compact: { numeric: { w: 2, h: 1 }, led: { w: 1, h: 1 }, toggle: { w: 1, h: 1 }, setpoint: { w: 2, h: 1 } },
        normal:  { numeric: { w: 3, h: 1 }, led: { w: 1, h: 1 }, toggle: { w: 1, h: 1 }, setpoint: { w: 2, h: 1 } },
        large:   { numeric: { w: 3, h: 2 }, led: { w: 2, h: 2 }, toggle: { w: 2, h: 2 }, setpoint: { w: 3, h: 2 } }
      }
      return sizes[opts.widgetSize]?.[type] || { w: 3, h: 1 }
    }

    // Calculate starting Y position (below existing widgets)
    const maxY = page.widgets.reduce((max, w) => Math.max(max, w.y + w.h), 0)

    let widgetCount = 0
    let currentX = 0
    let currentY = maxY

    // Create widgets in grid layout
    for (const channel of channelsToAdd) {
      const widgetType = getWidgetTypeForChannel(channel)
      const size = getWidgetSize(widgetType)

      // Check if widget fits in current row
      if (currentX + size.w > opts.columns) {
        currentX = 0
        currentY += 2  // Move to next row (standard row height)
      }

      const widgetId = addWidget({
        type: widgetType,
        channel: channel.name,
        x: currentX,
        y: currentY,
        w: size.w,
        h: size.h,
        label: channel.name,  // Use channel TAG as label
        showUnit: true,
        decimals: 2
      })

      if (widgetId) {
        widgetCount++
        currentX += size.w
      }
    }

    console.log(`[AUTO-WIDGETS] Created ${widgetCount} widgets for ${channelsToAdd.length} channels`)
    return widgetCount
  }

  // ========================================================================
  // PIPE/CONNECTION ACTIONS (P&ID routing)
  // ========================================================================

  function addPipe(pipe: Omit<PipeConnection, 'id'>): string {
    const page = pages.value.find(p => p.id === currentPageId.value)
    if (!page) return ''

    if (!page.pipes) {
      page.pipes = []
    }

    const id = `pipe-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`
    const newPipe: PipeConnection = { id, ...pipe }
    page.pipes.push(newPipe)
    return id
  }

  function updatePipe(pipeId: string, updates: Partial<PipeConnection>) {
    const page = pages.value.find(p => p.id === currentPageId.value)
    if (!page?.pipes) return

    const pipe = page.pipes.find(p => p.id === pipeId)
    if (pipe) {
      Object.assign(pipe, updates)
    }
  }

  function removePipe(pipeId: string) {
    const page = pages.value.find(p => p.id === currentPageId.value)
    if (!page?.pipes) return

    const index = page.pipes.findIndex(p => p.id === pipeId)
    if (index !== -1) {
      page.pipes.splice(index, 1)
    }
  }

  function setPipeDrawingMode(enabled: boolean) {
    pipeDrawingMode.value = enabled
    if (!enabled) {
      pipeDrawingStart.value = null
    }
  }

  function startPipeDrawing(start: { widgetId?: string; port?: string; point?: PipePoint }) {
    pipeDrawingStart.value = start
  }

  function finishPipeDrawing(end: { widgetId?: string; port?: string; point?: PipePoint }) {
    if (!pipeDrawingStart.value) return

    // Create pipe with at least 2 points
    const startPoint = pipeDrawingStart.value.point || { x: 0, y: 0 }
    const endPoint = end.point || { x: 5, y: 5 }

    const newPipe: Omit<PipeConnection, 'id'> = {
      points: [startPoint, endPoint],
      startWidgetId: pipeDrawingStart.value.widgetId,
      startPort: pipeDrawingStart.value.port as PipeConnection['startPort'],
      endWidgetId: end.widgetId,
      endPort: end.port as PipeConnection['endPort'],
      color: '#60a5fa',
      strokeWidth: 3
    }

    addPipe(newPipe)
    pipeDrawingStart.value = null
    pipeDrawingMode.value = false
  }

  function cancelPipeDrawing() {
    pipeDrawingStart.value = null
  }

  // ========================================================================
  // P&ID CANVAS LAYER (Free-Form, Pixel-Based)
  // ========================================================================

  function setPidEditMode(enabled: boolean) {
    pidEditMode.value = enabled
    if (!enabled) {
      pidDrawingMode.value = false
      if (pidFocusMode.value) exitPidFocusMode()
    }
  }

  function setPidDrawingMode(enabled: boolean) {
    pidDrawingMode.value = enabled
  }

  function togglePidSymbolPanelCollapse() {
    if (!pidSymbolPanelOpen.value) {
      pidSymbolPanelOpen.value = true
      pidSymbolPanelCollapsed.value = false
    } else {
      pidSymbolPanelCollapsed.value = !pidSymbolPanelCollapsed.value
    }
  }

  function togglePidPropertiesPanelCollapse() {
    if (!pidPropertiesPanelOpen.value) {
      pidPropertiesPanelOpen.value = true
      pidPropertiesPanelCollapsed.value = false
    } else {
      pidPropertiesPanelCollapsed.value = !pidPropertiesPanelCollapsed.value
    }
  }

  function enterPidFocusMode() {
    pidFocusModePrevState.value = {
      symbolPanelOpen: pidSymbolPanelOpen.value,
      symbolPanelCollapsed: pidSymbolPanelCollapsed.value,
      propertiesPanelOpen: pidPropertiesPanelOpen.value,
      propertiesPanelCollapsed: pidPropertiesPanelCollapsed.value,
      showMinimap: pidShowMinimap.value,
      showRulers: pidShowRulers.value,
      showGrid: pidShowGrid.value,
    }
    pidSymbolPanelCollapsed.value = true
    pidPropertiesPanelCollapsed.value = true
    pidShowMinimap.value = false
    pidShowRulers.value = false
    pidToolbarCompact.value = true
    pidFocusMode.value = true
  }

  function exitPidFocusMode() {
    const prev = pidFocusModePrevState.value
    if (prev) {
      pidSymbolPanelOpen.value = prev.symbolPanelOpen
      pidSymbolPanelCollapsed.value = prev.symbolPanelCollapsed
      pidPropertiesPanelOpen.value = prev.propertiesPanelOpen
      pidPropertiesPanelCollapsed.value = prev.propertiesPanelCollapsed
      pidShowMinimap.value = prev.showMinimap
      pidShowRulers.value = prev.showRulers
      pidShowGrid.value = prev.showGrid
    }
    pidToolbarCompact.value = false
    pidFocusMode.value = false
    pidFocusModePrevState.value = null
  }

  function togglePidFocusMode() {
    if (pidFocusMode.value) {
      exitPidFocusMode()
    } else {
      enterPidFocusMode()
    }
  }

  function togglePidGridSnap() {
    pidGridSnapEnabled.value = !pidGridSnapEnabled.value
    pidShowGrid.value = pidGridSnapEnabled.value
  }

  function setPidGridSize(size: number) {
    pidGridSize.value = Math.max(5, Math.min(100, size))
  }

  function togglePidColorScheme() {
    pidColorScheme.value = pidColorScheme.value === 'standard' ? 'isa101' : 'standard'
  }

  function setPidColorScheme(scheme: 'standard' | 'isa101') {
    pidColorScheme.value = scheme
  }

  function setPidZoom(zoom: number) {
    pidZoom.value = Math.max(0.1, Math.min(5, zoom))
  }

  function setPidPan(x: number, y: number) {
    pidPanX.value = x
    pidPanY.value = y
  }

  function pidResetZoom() {
    pidZoom.value = 1
    pidPanX.value = 0
    pidPanY.value = 0
  }

  function pidFitToContent(canvasWidth: number, canvasHeight: number) {
    const symbols = pidLayer.value.symbols
    const pipes = pidLayer.value.pipes
    if (symbols.length === 0 && pipes.length === 0) {
      pidResetZoom()
      return
    }
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
    for (const sym of symbols) {
      minX = Math.min(minX, sym.x)
      minY = Math.min(minY, sym.y)
      maxX = Math.max(maxX, sym.x + sym.width)
      maxY = Math.max(maxY, sym.y + sym.height)
    }
    for (const pipe of pipes) {
      for (const pt of pipe.points) {
        minX = Math.min(minX, pt.x)
        minY = Math.min(minY, pt.y)
        maxX = Math.max(maxX, pt.x)
        maxY = Math.max(maxY, pt.y)
      }
    }
    const pad = 40
    const contentW = maxX - minX + pad * 2
    const contentH = maxY - minY + pad * 2
    const newZoom = Math.max(0.1, Math.min(5, Math.min(canvasWidth / contentW, canvasHeight / contentH)))
    pidZoom.value = newZoom
    pidPanX.value = (canvasWidth - contentW * newZoom) / 2 - (minX - pad) * newZoom
    pidPanY.value = (canvasHeight - contentH * newZoom) / 2 - (minY - pad) * newZoom
  }

  function addPidSymbol(symbol: Omit<PidSymbol, 'id'>): string {
    const id = `pid-symbol-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`
    const newSymbol: PidSymbol = { ...symbol, id }

    pidLayer.value = {
      ...pidLayer.value,
      symbols: [...pidLayer.value.symbols, newSymbol]
    }

    return id
  }

  function updatePidSymbol(id: string, updates: Partial<PidSymbol>) {
    pidLayer.value = {
      ...pidLayer.value,
      symbols: pidLayer.value.symbols.map(s =>
        s.id === id ? { ...s, ...updates } : s
      )
    }
  }

  function removePidSymbol(id: string) {
    // Clean up pipe connections that reference this symbol
    const cleanedPipes = pidLayer.value.pipes.map(pipe => {
      let updated = pipe
      if (pipe.startConnection?.symbolId === id) {
        const { startConnection, ...rest } = updated
        updated = { ...rest, startSymbolId: undefined, startPortId: undefined } as typeof pipe
      }
      if (pipe.endConnection?.symbolId === id) {
        const { endConnection, ...rest } = updated
        updated = { ...rest, endSymbolId: undefined, endPortId: undefined } as typeof pipe
      }
      if (pipe.startSymbolId === id) {
        updated = { ...updated, startSymbolId: undefined, startPortId: undefined }
      }
      if (pipe.endSymbolId === id) {
        updated = { ...updated, endSymbolId: undefined, endPortId: undefined }
      }
      return updated
    })
    pidLayer.value = {
      ...pidLayer.value,
      symbols: pidLayer.value.symbols.filter(s => s.id !== id),
      pipes: cleanedPipes
    }
  }

  function addPidPipe(pipe: Omit<PidPipe, 'id'>): string {
    const id = `pid-pipe-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`
    const newPipe: PidPipe = { ...pipe, id }

    pidLayer.value = {
      ...pidLayer.value,
      pipes: [...pidLayer.value.pipes, newPipe]
    }

    return id
  }

  function updatePidPipe(id: string, updates: Partial<PidPipe>) {
    pidLayer.value = {
      ...pidLayer.value,
      pipes: pidLayer.value.pipes.map(p =>
        p.id === id ? { ...p, ...updates } : p
      )
    }
  }

  function removePidPipe(id: string) {
    pidLayer.value = {
      ...pidLayer.value,
      pipes: pidLayer.value.pipes.filter(p => p.id !== id)
    }
  }

  function updatePidLayer(layer: PidLayerData) {
    pidLayer.value = layer
  }

  function clearPidLayer() {
    const beforeState = createPidStateSnapshot()
    pidLayer.value = { symbols: [], pipes: [], textAnnotations: [], groups: [], visible: true, opacity: 1 }
    pushPidCommand('batch', 'Clear all P&ID elements', beforeState)
    saveLayoutToStorage()
  }

  /**
   * Set background image for current page's P&ID layer
   */
  function setPidBackgroundImage(imageConfig: {
    url: string
    x?: number
    y?: number
    width?: number
    height?: number
    opacity?: number
    locked?: boolean
  }) {
    const background = {
      url: imageConfig.url,
      x: imageConfig.x ?? 0,
      y: imageConfig.y ?? 0,
      width: imageConfig.width ?? 800,
      height: imageConfig.height ?? 600,
      opacity: imageConfig.opacity ?? 0.5,
      locked: imageConfig.locked ?? false
    }

    pidLayer.value = {
      ...pidLayer.value,
      backgroundImage: background
    }
    saveLayoutToStorage()
  }

  /**
   * Update background image properties
   */
  function updatePidBackgroundImage(updates: Partial<{
    x: number
    y: number
    width: number
    height: number
    opacity: number
    locked: boolean
  }>) {
    if (!pidLayer.value.backgroundImage) return

    pidLayer.value = {
      ...pidLayer.value,
      backgroundImage: {
        ...pidLayer.value.backgroundImage,
        ...updates
      }
    }
    saveLayoutToStorage()
  }

  /**
   * Remove background image
   */
  function removePidBackgroundImage() {
    pidLayer.value = {
      ...pidLayer.value,
      backgroundImage: undefined
    }
    saveLayoutToStorage()
  }

  // ========================================================================
  // P&ID UNDO/REDO ACTIONS (Command Pattern)
  // ========================================================================

  /**
   * Create a snapshot of current PID layer state for undo/redo
   */
  function createPidStateSnapshot(): PidCommand['beforeState'] {
    return {
      symbols: JSON.parse(JSON.stringify(pidLayer.value.symbols)),
      pipes: JSON.parse(JSON.stringify(pidLayer.value.pipes)),
      textAnnotations: JSON.parse(JSON.stringify(pidLayer.value.textAnnotations || [])),
      groups: JSON.parse(JSON.stringify(pidLayer.value.groups || [])),
      layerInfos: JSON.parse(JSON.stringify(pidLayer.value.layerInfos || []))
    }
  }

  /**
   * Push a command to the undo stack (called after each edit operation)
   */
  function pushPidCommand(type: PidCommand['type'], description: string, beforeState: PidCommand['beforeState']) {
    const command: PidCommand = {
      id: `cmd-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
      type,
      timestamp: Date.now(),
      description,
      beforeState,
      afterState: createPidStateSnapshot()
    }

    pidUndoStack.value.push(command)

    // Limit stack size
    if (pidUndoStack.value.length > PID_MAX_UNDO_STACK) {
      pidUndoStack.value.shift()
    }

    // Clear redo stack on new action
    pidRedoStack.value = []
  }

  /**
   * Undo the last PID operation
   */
  function pidUndo(): boolean {
    const command = pidUndoStack.value.pop()
    if (!command) return false

    // Restore before state (including layerInfos for #3.6)
    pidLayer.value = {
      ...pidLayer.value,
      symbols: command.beforeState.symbols || [],
      pipes: command.beforeState.pipes || [],
      textAnnotations: command.beforeState.textAnnotations || [],
      groups: command.beforeState.groups || [],
      ...(command.beforeState.layerInfos ? { layerInfos: command.beforeState.layerInfos } : {})
    }

    // Push to redo stack
    pidRedoStack.value.push(command)

    saveLayoutToStorage()
    return true
  }

  /**
   * Redo the last undone PID operation
   */
  function pidRedo(): boolean {
    const command = pidRedoStack.value.pop()
    if (!command) return false

    // Restore after state (including layerInfos for #3.6)
    pidLayer.value = {
      ...pidLayer.value,
      symbols: command.afterState.symbols || [],
      pipes: command.afterState.pipes || [],
      textAnnotations: command.afterState.textAnnotations || [],
      groups: command.afterState.groups || [],
      ...(command.afterState.layerInfos ? { layerInfos: command.afterState.layerInfos } : {})
    }

    // Push back to undo stack
    pidUndoStack.value.push(command)

    saveLayoutToStorage()
    return true
  }

  /**
   * Check if undo is available
   */
  const canPidUndo = computed(() => pidUndoStack.value.length > 0)

  /**
   * Check if redo is available
   */
  const canPidRedo = computed(() => pidRedoStack.value.length > 0)

  /**
   * Clear undo/redo history
   */
  function clearPidHistory() {
    pidUndoStack.value = []
    pidRedoStack.value = []
  }

  // ========================================================================
  // P&ID COPY/PASTE/DUPLICATE ACTIONS
  // ========================================================================

  /**
   * Copy selected PID elements to clipboard
   */
  function pidCopy(): boolean {
    if (!hasPidSelection.value) return false

    const selectedSymbols = pidLayer.value.symbols.filter(s =>
      pidSelectedIds.value.symbolIds.includes(s.id)
    )
    const selectedPipes = pidLayer.value.pipes.filter(p =>
      pidSelectedIds.value.pipeIds.includes(p.id)
    )
    const selectedTextAnnotations = (pidLayer.value.textAnnotations || []).filter(t =>
      pidSelectedIds.value.textAnnotationIds.includes(t.id)
    )

    pidClipboard.value = {
      symbols: JSON.parse(JSON.stringify(selectedSymbols)),
      pipes: JSON.parse(JSON.stringify(selectedPipes)),
      textAnnotations: JSON.parse(JSON.stringify(selectedTextAnnotations))
    }

    return true
  }

  /**
   * Paste clipboard contents with offset
   */
  function pidPaste(offsetX: number = 20, offsetY: number = 20): string[] {
    if (!pidClipboard.value) return []

    const beforeState = createPidStateSnapshot()
    const newIds: string[] = []
    const idMapping: Record<string, string> = {}

    // Paste symbols with new IDs and offset positions
    for (const symbol of pidClipboard.value.symbols) {
      const newId = `pid-symbol-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`
      idMapping[symbol.id] = newId

      const newSymbol: PidSymbol = {
        ...symbol,
        id: newId,
        x: symbol.x + offsetX,
        y: symbol.y + offsetY,
        groupId: undefined  // Clear group association
      }

      pidLayer.value = {
        ...pidLayer.value,
        symbols: [...pidLayer.value.symbols, newSymbol]
      }

      newIds.push(newId)
    }

    // Paste pipes with new IDs and offset positions, update symbol references
    for (const pipe of pidClipboard.value.pipes) {
      const newId = `pid-pipe-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`
      idMapping[pipe.id] = newId

      const newPipe: PidPipe = {
        ...pipe,
        id: newId,
        points: pipe.points.map(p => ({ x: p.x + offsetX, y: p.y + offsetY })),
        groupId: undefined,
        // Update symbol references if they were in the clipboard
        startSymbolId: pipe.startSymbolId ? idMapping[pipe.startSymbolId] || pipe.startSymbolId : undefined,
        endSymbolId: pipe.endSymbolId ? idMapping[pipe.endSymbolId] || pipe.endSymbolId : undefined
      }

      pidLayer.value = {
        ...pidLayer.value,
        pipes: [...pidLayer.value.pipes, newPipe]
      }

      newIds.push(newId)
    }

    // Paste text annotations with new IDs and offset positions
    for (const annotation of pidClipboard.value.textAnnotations) {
      const newId = `pid-text-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`
      idMapping[annotation.id] = newId

      const newAnnotation: PidTextAnnotation = {
        ...annotation,
        id: newId,
        x: annotation.x + offsetX,
        y: annotation.y + offsetY,
        groupId: undefined
      }

      pidLayer.value = {
        ...pidLayer.value,
        textAnnotations: [...(pidLayer.value.textAnnotations || []), newAnnotation]
      }

      newIds.push(newId)
    }

    // Push undo command
    pushPidCommand('paste', `Paste ${newIds.length} element(s)`, beforeState)

    // Select newly pasted items
    pidSelectItems(
      pidClipboard.value.symbols.map(s => idMapping[s.id]!),
      pidClipboard.value.pipes.map(p => idMapping[p.id]!),
      pidClipboard.value.textAnnotations.map(t => idMapping[t.id]!)
    )

    saveLayoutToStorage()
    return newIds
  }

  /**
   * Duplicate selected elements in place (shortcut for copy + paste)
   */
  function pidDuplicate(): string[] {
    if (pidCopy()) {
      return pidPaste(20, 20)
    }
    return []
  }

  /**
   * Cut selected elements (copy + delete)
   */
  function pidCut(): boolean {
    if (!pidCopy()) return false
    pidDeleteSelected()
    return true
  }

  /**
   * Check if clipboard has content
   */
  const hasPidClipboard = computed(() =>
    pidClipboard.value !== null && (
      pidClipboard.value.symbols.length > 0 ||
      pidClipboard.value.pipes.length > 0 ||
      pidClipboard.value.textAnnotations.length > 0
    )
  )

  // ========================================================================
  // P&ID SELECTION ACTIONS
  // ========================================================================

  /**
   * Select specific items by IDs
   */
  function pidSelectItems(symbolIds: string[], pipeIds: string[], textAnnotationIds: string[]) {
    pidSelectedIds.value = { symbolIds, pipeIds, textAnnotationIds }
  }

  /**
   * Add items to selection (for Shift+Click)
   */
  function pidAddToSelection(symbolIds: string[], pipeIds: string[], textAnnotationIds: string[]) {
    pidSelectedIds.value = {
      symbolIds: [...new Set([...pidSelectedIds.value.symbolIds, ...symbolIds])],
      pipeIds: [...new Set([...pidSelectedIds.value.pipeIds, ...pipeIds])],
      textAnnotationIds: [...new Set([...pidSelectedIds.value.textAnnotationIds, ...textAnnotationIds])]
    }
  }

  /**
   * Remove items from selection
   */
  function pidRemoveFromSelection(symbolIds: string[], pipeIds: string[], textAnnotationIds: string[]) {
    pidSelectedIds.value = {
      symbolIds: pidSelectedIds.value.symbolIds.filter(id => !symbolIds.includes(id)),
      pipeIds: pidSelectedIds.value.pipeIds.filter(id => !pipeIds.includes(id)),
      textAnnotationIds: pidSelectedIds.value.textAnnotationIds.filter(id => !textAnnotationIds.includes(id))
    }
  }

  /**
   * Toggle item selection (for Ctrl+Click)
   */
  function pidToggleSelection(id: string, type: 'symbol' | 'pipe' | 'textAnnotation') {
    if (type === 'symbol') {
      if (pidSelectedIds.value.symbolIds.includes(id)) {
        pidRemoveFromSelection([id], [], [])
      } else {
        pidAddToSelection([id], [], [])
      }
    } else if (type === 'pipe') {
      if (pidSelectedIds.value.pipeIds.includes(id)) {
        pidRemoveFromSelection([], [id], [])
      } else {
        pidAddToSelection([], [id], [])
      }
    } else {
      if (pidSelectedIds.value.textAnnotationIds.includes(id)) {
        pidRemoveFromSelection([], [], [id])
      } else {
        pidAddToSelection([], [], [id])
      }
    }
  }

  /**
   * Clear all selection
   */
  function pidClearSelection() {
    pidSelectedIds.value = { symbolIds: [], pipeIds: [], textAnnotationIds: [] }
  }

  /**
   * Select all elements on current page
   */
  function pidSelectAll() {
    pidSelectedIds.value = {
      symbolIds: pidLayer.value.symbols.map(s => s.id),
      pipeIds: pidLayer.value.pipes.map(p => p.id),
      textAnnotationIds: (pidLayer.value.textAnnotations || []).map(t => t.id)
    }
  }

  /**
   * Delete all selected elements
   */
  function pidDeleteSelected(): boolean {
    if (!hasPidSelection.value) return false

    const beforeState = createPidStateSnapshot()

    // Remove selected symbols (skip locked ones)
    const unlockedSymbolIds = pidSelectedIds.value.symbolIds.filter(
      id => !pidLayer.value.symbols.find(s => s.id === id)?.locked
    )
    if (unlockedSymbolIds.length > 0) {
      pidLayer.value = {
        ...pidLayer.value,
        symbols: pidLayer.value.symbols.filter(s => !unlockedSymbolIds.includes(s.id))
      }
    }

    // Remove selected pipes
    if (pidSelectedIds.value.pipeIds.length > 0) {
      pidLayer.value = {
        ...pidLayer.value,
        pipes: pidLayer.value.pipes.filter(p => !pidSelectedIds.value.pipeIds.includes(p.id))
      }
    }

    // Remove selected text annotations
    if (pidSelectedIds.value.textAnnotationIds.length > 0 && pidLayer.value.textAnnotations) {
      pidLayer.value = {
        ...pidLayer.value,
        textAnnotations: pidLayer.value.textAnnotations.filter(t => !pidSelectedIds.value.textAnnotationIds.includes(t.id))
      }
    }

    const deletedCount =
      unlockedSymbolIds.length +
      pidSelectedIds.value.pipeIds.length +
      pidSelectedIds.value.textAnnotationIds.length

    // Push undo command
    pushPidCommand('delete', `Delete ${deletedCount} element(s)`, beforeState)

    // Clear selection
    pidClearSelection()

    saveLayoutToStorage()
    return true
  }

  /**
   * Bring selected elements to front (highest z-index)
   */
  function pidBringToFront() {
    if (!hasPidSelection.value) return

    const beforeState = createPidStateSnapshot()

    // Find max z-index
    const allZIndices = [
      ...pidLayer.value.symbols.map(s => s.zIndex || 0),
      ...pidLayer.value.pipes.map(p => p.zIndex || 0),
      ...(pidLayer.value.textAnnotations || []).map(t => t.zIndex || 0)
    ]
    const maxZ = Math.max(0, ...allZIndices)

    // Update z-index for selected items
    let nextZ = maxZ + 1

    if (pidSelectedIds.value.symbolIds.length > 0) {
      pidLayer.value = {
        ...pidLayer.value,
        symbols: pidLayer.value.symbols.map(s =>
          pidSelectedIds.value.symbolIds.includes(s.id)
            ? { ...s, zIndex: nextZ++ }
            : s
        )
      }
    }

    if (pidSelectedIds.value.pipeIds.length > 0) {
      pidLayer.value = {
        ...pidLayer.value,
        pipes: pidLayer.value.pipes.map(p =>
          pidSelectedIds.value.pipeIds.includes(p.id)
            ? { ...p, zIndex: nextZ++ }
            : p
        )
      }
    }

    if (pidSelectedIds.value.textAnnotationIds.length > 0 && pidLayer.value.textAnnotations) {
      pidLayer.value = {
        ...pidLayer.value,
        textAnnotations: pidLayer.value.textAnnotations.map(t =>
          pidSelectedIds.value.textAnnotationIds.includes(t.id)
            ? { ...t, zIndex: nextZ++ }
            : t
        )
      }
    }

    pushPidCommand('modify', 'Bring to front', beforeState)
    saveLayoutToStorage()
  }

  /**
   * Send selected elements to back (lowest z-index)
   */
  function pidSendToBack() {
    if (!hasPidSelection.value) return

    const beforeState = createPidStateSnapshot()

    // Find min z-index
    const allZIndices = [
      ...pidLayer.value.symbols.map(s => s.zIndex || 0),
      ...pidLayer.value.pipes.map(p => p.zIndex || 0),
      ...(pidLayer.value.textAnnotations || []).map(t => t.zIndex || 0)
    ]
    const minZ = Math.min(0, ...allZIndices)

    // Update z-index for selected items
    let nextZ = minZ - 1

    if (pidSelectedIds.value.symbolIds.length > 0) {
      pidLayer.value = {
        ...pidLayer.value,
        symbols: pidLayer.value.symbols.map(s =>
          pidSelectedIds.value.symbolIds.includes(s.id)
            ? { ...s, zIndex: nextZ-- }
            : s
        )
      }
    }

    if (pidSelectedIds.value.pipeIds.length > 0) {
      pidLayer.value = {
        ...pidLayer.value,
        pipes: pidLayer.value.pipes.map(p =>
          pidSelectedIds.value.pipeIds.includes(p.id)
            ? { ...p, zIndex: nextZ-- }
            : p
        )
      }
    }

    if (pidSelectedIds.value.textAnnotationIds.length > 0 && pidLayer.value.textAnnotations) {
      pidLayer.value = {
        ...pidLayer.value,
        textAnnotations: pidLayer.value.textAnnotations.map(t =>
          pidSelectedIds.value.textAnnotationIds.includes(t.id)
            ? { ...t, zIndex: nextZ-- }
            : t
        )
      }
    }

    pushPidCommand('modify', 'Send to back', beforeState)
    saveLayoutToStorage()
  }

  // ========================================================================
  // P&ID ALIGNMENT TOOLS
  // ========================================================================

  /**
   * Get bounding box of all selected elements
   */
  function getSelectedBounds(): { minX: number; maxX: number; minY: number; maxY: number; items: Array<{ id: string; type: 'symbol' | 'pipe' | 'text'; x: number; y: number; width: number; height: number }> } | null {
    if (!hasPidSelection.value) return null

    const items: Array<{ id: string; type: 'symbol' | 'pipe' | 'text'; x: number; y: number; width: number; height: number }> = []

    // Collect symbols
    for (const id of pidSelectedIds.value.symbolIds) {
      const symbol = pidLayer.value.symbols.find(s => s.id === id)
      if (symbol) {
        items.push({
          id: symbol.id,
          type: 'symbol',
          x: symbol.x,
          y: symbol.y,
          width: symbol.width || 60,
          height: symbol.height || 60
        })
      }
    }

    // Collect text annotations
    for (const id of pidSelectedIds.value.textAnnotationIds) {
      const text = (pidLayer.value.textAnnotations || []).find(t => t.id === id)
      if (text) {
        // Estimate text dimensions based on font size
        const estimatedWidth = (text.text.length * text.fontSize * 0.6) || 100
        const estimatedHeight = text.fontSize * 1.2 || 20
        items.push({
          id: text.id,
          type: 'text',
          x: text.x,
          y: text.y,
          width: estimatedWidth,
          height: estimatedHeight
        })
      }
    }

    // Collect pipes (use bounding box of all points)
    for (const id of pidSelectedIds.value.pipeIds) {
      const pipe = pidLayer.value.pipes.find(p => p.id === id)
      if (pipe && pipe.points.length > 0) {
        const xs = pipe.points.map(p => p.x)
        const ys = pipe.points.map(p => p.y)
        const minX = Math.min(...xs)
        const maxX = Math.max(...xs)
        const minY = Math.min(...ys)
        const maxY = Math.max(...ys)
        items.push({
          id: pipe.id,
          type: 'pipe',
          x: minX,
          y: minY,
          width: maxX - minX || 1,
          height: maxY - minY || 1
        })
      }
    }

    if (items.length === 0) return null

    const minX = Math.min(...items.map(i => i.x))
    const maxX = Math.max(...items.map(i => i.x + i.width))
    const minY = Math.min(...items.map(i => i.y))
    const maxY = Math.max(...items.map(i => i.y + i.height))

    return { minX, maxX, minY, maxY, items }
  }

  /**
   * Align selected elements to the left
   */
  function pidAlignLeft() {
    const bounds = getSelectedBounds()
    if (!bounds || bounds.items.length < 2) return

    const beforeState = createPidStateSnapshot()
    const targetX = bounds.minX

    // Move symbols
    pidLayer.value = {
      ...pidLayer.value,
      symbols: pidLayer.value.symbols.map(s => {
        if (pidSelectedIds.value.symbolIds.includes(s.id)) {
          return { ...s, x: targetX }
        }
        return s
      })
    }

    // Move text annotations
    if (pidLayer.value.textAnnotations) {
      pidLayer.value = {
        ...pidLayer.value,
        textAnnotations: pidLayer.value.textAnnotations.map(t => {
          if (pidSelectedIds.value.textAnnotationIds.includes(t.id)) {
            return { ...t, x: targetX }
          }
          return t
        })
      }
    }

    // Move pipes (shift all points)
    pidLayer.value = {
      ...pidLayer.value,
      pipes: pidLayer.value.pipes.map(p => {
        if (pidSelectedIds.value.pipeIds.includes(p.id)) {
          const pipeMinX = Math.min(...p.points.map(pt => pt.x))
          const dx = targetX - pipeMinX
          return { ...p, points: p.points.map(pt => ({ x: pt.x + dx, y: pt.y })) }
        }
        return p
      })
    }

    pushPidCommand('modify', 'Align left', beforeState)
    saveLayoutToStorage()
  }

  /**
   * Align selected elements to horizontal center
   */
  function pidAlignCenterH() {
    const bounds = getSelectedBounds()
    if (!bounds || bounds.items.length < 2) return

    const beforeState = createPidStateSnapshot()
    const centerX = (bounds.minX + bounds.maxX) / 2

    // Move symbols to center
    pidLayer.value = {
      ...pidLayer.value,
      symbols: pidLayer.value.symbols.map(s => {
        if (pidSelectedIds.value.symbolIds.includes(s.id)) {
          const width = s.width || 60
          return { ...s, x: centerX - width / 2 }
        }
        return s
      })
    }

    // Move text annotations
    if (pidLayer.value.textAnnotations) {
      pidLayer.value = {
        ...pidLayer.value,
        textAnnotations: pidLayer.value.textAnnotations.map(t => {
          if (pidSelectedIds.value.textAnnotationIds.includes(t.id)) {
            const width = t.text.length * t.fontSize * 0.6
            return { ...t, x: centerX - width / 2 }
          }
          return t
        })
      }
    }

    // Move pipes
    pidLayer.value = {
      ...pidLayer.value,
      pipes: pidLayer.value.pipes.map(p => {
        if (pidSelectedIds.value.pipeIds.includes(p.id)) {
          const xs = p.points.map(pt => pt.x)
          const pipeCenterX = (Math.min(...xs) + Math.max(...xs)) / 2
          const dx = centerX - pipeCenterX
          return { ...p, points: p.points.map(pt => ({ x: pt.x + dx, y: pt.y })) }
        }
        return p
      })
    }

    pushPidCommand('modify', 'Align center horizontal', beforeState)
    saveLayoutToStorage()
  }

  /**
   * Align selected elements to the right
   */
  function pidAlignRight() {
    const bounds = getSelectedBounds()
    if (!bounds || bounds.items.length < 2) return

    const beforeState = createPidStateSnapshot()
    const targetX = bounds.maxX

    // Move symbols
    pidLayer.value = {
      ...pidLayer.value,
      symbols: pidLayer.value.symbols.map(s => {
        if (pidSelectedIds.value.symbolIds.includes(s.id)) {
          const width = s.width || 60
          return { ...s, x: targetX - width }
        }
        return s
      })
    }

    // Move text annotations
    if (pidLayer.value.textAnnotations) {
      pidLayer.value = {
        ...pidLayer.value,
        textAnnotations: pidLayer.value.textAnnotations.map(t => {
          if (pidSelectedIds.value.textAnnotationIds.includes(t.id)) {
            const width = t.text.length * t.fontSize * 0.6
            return { ...t, x: targetX - width }
          }
          return t
        })
      }
    }

    // Move pipes
    pidLayer.value = {
      ...pidLayer.value,
      pipes: pidLayer.value.pipes.map(p => {
        if (pidSelectedIds.value.pipeIds.includes(p.id)) {
          const pipeMaxX = Math.max(...p.points.map(pt => pt.x))
          const dx = targetX - pipeMaxX
          return { ...p, points: p.points.map(pt => ({ x: pt.x + dx, y: pt.y })) }
        }
        return p
      })
    }

    pushPidCommand('modify', 'Align right', beforeState)
    saveLayoutToStorage()
  }

  /**
   * Align selected elements to the top
   */
  function pidAlignTop() {
    const bounds = getSelectedBounds()
    if (!bounds || bounds.items.length < 2) return

    const beforeState = createPidStateSnapshot()
    const targetY = bounds.minY

    // Move symbols
    pidLayer.value = {
      ...pidLayer.value,
      symbols: pidLayer.value.symbols.map(s => {
        if (pidSelectedIds.value.symbolIds.includes(s.id)) {
          return { ...s, y: targetY }
        }
        return s
      })
    }

    // Move text annotations
    if (pidLayer.value.textAnnotations) {
      pidLayer.value = {
        ...pidLayer.value,
        textAnnotations: pidLayer.value.textAnnotations.map(t => {
          if (pidSelectedIds.value.textAnnotationIds.includes(t.id)) {
            return { ...t, y: targetY }
          }
          return t
        })
      }
    }

    // Move pipes
    pidLayer.value = {
      ...pidLayer.value,
      pipes: pidLayer.value.pipes.map(p => {
        if (pidSelectedIds.value.pipeIds.includes(p.id)) {
          const pipeMinY = Math.min(...p.points.map(pt => pt.y))
          const dy = targetY - pipeMinY
          return { ...p, points: p.points.map(pt => ({ x: pt.x, y: pt.y + dy })) }
        }
        return p
      })
    }

    pushPidCommand('modify', 'Align top', beforeState)
    saveLayoutToStorage()
  }

  /**
   * Align selected elements to vertical center
   */
  function pidAlignCenterV() {
    const bounds = getSelectedBounds()
    if (!bounds || bounds.items.length < 2) return

    const beforeState = createPidStateSnapshot()
    const centerY = (bounds.minY + bounds.maxY) / 2

    // Move symbols to center
    pidLayer.value = {
      ...pidLayer.value,
      symbols: pidLayer.value.symbols.map(s => {
        if (pidSelectedIds.value.symbolIds.includes(s.id)) {
          const height = s.height || 60
          return { ...s, y: centerY - height / 2 }
        }
        return s
      })
    }

    // Move text annotations
    if (pidLayer.value.textAnnotations) {
      pidLayer.value = {
        ...pidLayer.value,
        textAnnotations: pidLayer.value.textAnnotations.map(t => {
          if (pidSelectedIds.value.textAnnotationIds.includes(t.id)) {
            const height = t.fontSize * 1.2
            return { ...t, y: centerY - height / 2 }
          }
          return t
        })
      }
    }

    // Move pipes
    pidLayer.value = {
      ...pidLayer.value,
      pipes: pidLayer.value.pipes.map(p => {
        if (pidSelectedIds.value.pipeIds.includes(p.id)) {
          const ys = p.points.map(pt => pt.y)
          const pipeCenterY = (Math.min(...ys) + Math.max(...ys)) / 2
          const dy = centerY - pipeCenterY
          return { ...p, points: p.points.map(pt => ({ x: pt.x, y: pt.y + dy })) }
        }
        return p
      })
    }

    pushPidCommand('modify', 'Align center vertical', beforeState)
    saveLayoutToStorage()
  }

  /**
   * Align selected elements to the bottom
   */
  function pidAlignBottom() {
    const bounds = getSelectedBounds()
    if (!bounds || bounds.items.length < 2) return

    const beforeState = createPidStateSnapshot()
    const targetY = bounds.maxY

    // Move symbols
    pidLayer.value = {
      ...pidLayer.value,
      symbols: pidLayer.value.symbols.map(s => {
        if (pidSelectedIds.value.symbolIds.includes(s.id)) {
          const height = s.height || 60
          return { ...s, y: targetY - height }
        }
        return s
      })
    }

    // Move text annotations
    if (pidLayer.value.textAnnotations) {
      pidLayer.value = {
        ...pidLayer.value,
        textAnnotations: pidLayer.value.textAnnotations.map(t => {
          if (pidSelectedIds.value.textAnnotationIds.includes(t.id)) {
            const height = t.fontSize * 1.2
            return { ...t, y: targetY - height }
          }
          return t
        })
      }
    }

    // Move pipes
    pidLayer.value = {
      ...pidLayer.value,
      pipes: pidLayer.value.pipes.map(p => {
        if (pidSelectedIds.value.pipeIds.includes(p.id)) {
          const pipeMaxY = Math.max(...p.points.map(pt => pt.y))
          const dy = targetY - pipeMaxY
          return { ...p, points: p.points.map(pt => ({ x: pt.x, y: pt.y + dy })) }
        }
        return p
      })
    }

    pushPidCommand('modify', 'Align bottom', beforeState)
    saveLayoutToStorage()
  }

  /**
   * Distribute selected elements evenly horizontally
   */
  function pidDistributeH() {
    const bounds = getSelectedBounds()
    if (!bounds || bounds.items.length < 3) return  // Need at least 3 items to distribute

    const beforeState = createPidStateSnapshot()

    // Sort items by x position
    const sortedItems = [...bounds.items].sort((a, b) => a.x - b.x)
    const totalWidth = bounds.maxX - bounds.minX
    const itemWidths = sortedItems.reduce((sum, item) => sum + item.width, 0)
    const spacing = (totalWidth - itemWidths) / (sortedItems.length - 1)

    let currentX = bounds.minX

    for (const item of sortedItems) {
      const dx = currentX - item.x

      if (item.type === 'symbol') {
        pidLayer.value = {
          ...pidLayer.value,
          symbols: pidLayer.value.symbols.map(s =>
            s.id === item.id ? { ...s, x: currentX } : s
          )
        }
      } else if (item.type === 'text') {
        pidLayer.value = {
          ...pidLayer.value,
          textAnnotations: (pidLayer.value.textAnnotations || []).map(t =>
            t.id === item.id ? { ...t, x: currentX } : t
          )
        }
      } else if (item.type === 'pipe') {
        pidLayer.value = {
          ...pidLayer.value,
          pipes: pidLayer.value.pipes.map(p =>
            p.id === item.id ? { ...p, points: p.points.map(pt => ({ x: pt.x + dx, y: pt.y })) } : p
          )
        }
      }

      currentX += item.width + spacing
    }

    pushPidCommand('modify', 'Distribute horizontally', beforeState)
    saveLayoutToStorage()
  }

  /**
   * Distribute selected elements evenly vertically
   */
  function pidDistributeV() {
    const bounds = getSelectedBounds()
    if (!bounds || bounds.items.length < 3) return  // Need at least 3 items to distribute

    const beforeState = createPidStateSnapshot()

    // Sort items by y position
    const sortedItems = [...bounds.items].sort((a, b) => a.y - b.y)
    const totalHeight = bounds.maxY - bounds.minY
    const itemHeights = sortedItems.reduce((sum, item) => sum + item.height, 0)
    const spacing = (totalHeight - itemHeights) / (sortedItems.length - 1)

    let currentY = bounds.minY

    for (const item of sortedItems) {
      const dy = currentY - item.y

      if (item.type === 'symbol') {
        pidLayer.value = {
          ...pidLayer.value,
          symbols: pidLayer.value.symbols.map(s =>
            s.id === item.id ? { ...s, y: currentY } : s
          )
        }
      } else if (item.type === 'text') {
        pidLayer.value = {
          ...pidLayer.value,
          textAnnotations: (pidLayer.value.textAnnotations || []).map(t =>
            t.id === item.id ? { ...t, y: currentY } : t
          )
        }
      } else if (item.type === 'pipe') {
        pidLayer.value = {
          ...pidLayer.value,
          pipes: pidLayer.value.pipes.map(p =>
            p.id === item.id ? { ...p, points: p.points.map(pt => ({ x: pt.x, y: pt.y + dy })) } : p
          )
        }
      }

      currentY += item.height + spacing
    }

    pushPidCommand('modify', 'Distribute vertically', beforeState)
    saveLayoutToStorage()
  }

  // ========================================================================
  // P&ID GROUPING TOOLS
  // ========================================================================

  /**
   * Group selected elements together
   */
  function pidGroup(): string | null {
    if (!hasPidSelection.value) return null

    const totalSelected = pidSelectedIds.value.symbolIds.length +
      pidSelectedIds.value.pipeIds.length +
      pidSelectedIds.value.textAnnotationIds.length

    // Need at least 2 items to group
    if (totalSelected < 2) return null

    const beforeState = createPidStateSnapshot()

    // Generate group ID
    const groupId = `pid-group-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`

    // Create group object
    const group: PidGroup = {
      id: groupId,
      symbolIds: [...pidSelectedIds.value.symbolIds],
      pipeIds: [...pidSelectedIds.value.pipeIds],
      textAnnotationIds: [...pidSelectedIds.value.textAnnotationIds]
    }

    // Calculate group bounding box
    const bounds = getSelectedBounds()
    if (bounds) {
      group.x = bounds.minX
      group.y = bounds.minY
      group.width = bounds.maxX - bounds.minX
      group.height = bounds.maxY - bounds.minY
    }

    // Update all member elements with groupId
    pidLayer.value = {
      ...pidLayer.value,
      symbols: pidLayer.value.symbols.map(s =>
        pidSelectedIds.value.symbolIds.includes(s.id) ? { ...s, groupId } : s
      ),
      pipes: pidLayer.value.pipes.map(p =>
        pidSelectedIds.value.pipeIds.includes(p.id) ? { ...p, groupId } : p
      ),
      textAnnotations: (pidLayer.value.textAnnotations || []).map(t =>
        pidSelectedIds.value.textAnnotationIds.includes(t.id) ? { ...t, groupId } : t
      ),
      groups: [...(pidLayer.value.groups || []), group]
    }

    pushPidCommand('group', `Group ${totalSelected} element(s)`, beforeState)
    saveLayoutToStorage()

    return groupId
  }

  /**
   * Ungroup the group that contains the first selected element
   */
  function pidUngroup(): boolean {
    if (!hasPidSelection.value) return false

    // Find the group that contains any of the selected elements
    const groups = pidLayer.value.groups || []
    let targetGroup: PidGroup | null = null

    for (const group of groups) {
      // Check if any selected element is in this group
      if (pidSelectedIds.value.symbolIds.some(id => group.symbolIds.includes(id)) ||
          pidSelectedIds.value.pipeIds.some(id => group.pipeIds.includes(id)) ||
          pidSelectedIds.value.textAnnotationIds.some(id => group.textAnnotationIds.includes(id))) {
        targetGroup = group
        break
      }
    }

    if (!targetGroup) return false
    if (targetGroup.locked) return false  // Can't ungroup locked groups

    const beforeState = createPidStateSnapshot()

    // Clear groupId from all members
    pidLayer.value = {
      ...pidLayer.value,
      symbols: pidLayer.value.symbols.map(s =>
        targetGroup!.symbolIds.includes(s.id) ? { ...s, groupId: undefined } : s
      ),
      pipes: pidLayer.value.pipes.map(p =>
        targetGroup!.pipeIds.includes(p.id) ? { ...p, groupId: undefined } : p
      ),
      textAnnotations: (pidLayer.value.textAnnotations || []).map(t =>
        targetGroup!.textAnnotationIds.includes(t.id) ? { ...t, groupId: undefined } : t
      ),
      groups: groups.filter(g => g.id !== targetGroup!.id)
    }

    // Select all the former group members
    pidSelectItems(
      targetGroup.symbolIds,
      targetGroup.pipeIds,
      targetGroup.textAnnotationIds
    )

    pushPidCommand('ungroup', 'Ungroup elements', beforeState)
    saveLayoutToStorage()

    return true
  }

  /**
   * Check if a symbol/pipe/text is in a group
   */
  function pidGetGroup(elementId: string): PidGroup | null {
    const groups = pidLayer.value.groups || []
    for (const group of groups) {
      if (group.symbolIds.includes(elementId) ||
          group.pipeIds.includes(elementId) ||
          group.textAnnotationIds.includes(elementId)) {
        return group
      }
    }
    return null
  }

  /**
   * Select all members of a group
   */
  function pidSelectGroup(groupId: string) {
    const group = (pidLayer.value.groups || []).find(g => g.id === groupId)
    if (!group) return

    pidSelectItems(
      group.symbolIds,
      group.pipeIds,
      group.textAnnotationIds
    )
  }

  /**
   * Move selected elements by offset
   */
  function pidMoveSelected(dx: number, dy: number) {
    if (!hasPidSelection.value) return

    const beforeState = createPidStateSnapshot()

    // Move symbols (skip locked ones)
    pidLayer.value = {
      ...pidLayer.value,
      symbols: pidLayer.value.symbols.map(s =>
        pidSelectedIds.value.symbolIds.includes(s.id) && !s.locked
          ? { ...s, x: s.x + dx, y: s.y + dy }
          : s
      )
    }

    // Move pipes
    pidLayer.value = {
      ...pidLayer.value,
      pipes: pidLayer.value.pipes.map(p =>
        pidSelectedIds.value.pipeIds.includes(p.id)
          ? { ...p, points: p.points.map(pt => ({ x: pt.x + dx, y: pt.y + dy })) }
          : p
      )
    }

    // Move text annotations
    if (pidLayer.value.textAnnotations) {
      pidLayer.value = {
        ...pidLayer.value,
        textAnnotations: pidLayer.value.textAnnotations.map(t =>
          pidSelectedIds.value.textAnnotationIds.includes(t.id)
            ? { ...t, x: t.x + dx, y: t.y + dy }
            : t
        )
      }
    }

    pushPidCommand('move', `Move ${pidSelectedIds.value.symbolIds.length + pidSelectedIds.value.pipeIds.length + pidSelectedIds.value.textAnnotationIds.length} element(s)`, beforeState)
    saveLayoutToStorage()
  }

  // ========================================================================
  // P&ID TEXT ANNOTATION ACTIONS
  // ========================================================================

  /**
   * Add a text annotation to the canvas
   */
  function addPidTextAnnotation(annotation: Omit<PidTextAnnotation, 'id'>): string {
    const beforeState = createPidStateSnapshot()

    const id = `pid-text-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`
    const newAnnotation: PidTextAnnotation = { ...annotation, id }

    pidLayer.value = {
      ...pidLayer.value,
      textAnnotations: [...(pidLayer.value.textAnnotations || []), newAnnotation]
    }

    pushPidCommand('add', 'Add text annotation', beforeState)
    saveLayoutToStorage()
    return id
  }

  /**
   * Update a text annotation
   */
  function updatePidTextAnnotation(id: string, updates: Partial<PidTextAnnotation>) {
    const beforeState = createPidStateSnapshot()

    pidLayer.value = {
      ...pidLayer.value,
      textAnnotations: (pidLayer.value.textAnnotations || []).map(t =>
        t.id === id ? { ...t, ...updates } : t
      )
    }

    pushPidCommand('modify', 'Update text annotation', beforeState)
    saveLayoutToStorage()
  }

  /**
   * Remove a text annotation
   */
  function removePidTextAnnotation(id: string) {
    const beforeState = createPidStateSnapshot()

    pidLayer.value = {
      ...pidLayer.value,
      textAnnotations: (pidLayer.value.textAnnotations || []).filter(t => t.id !== id)
    }

    pushPidCommand('delete', 'Delete text annotation', beforeState)
    saveLayoutToStorage()
  }

  // ========================================================================
  // P&ID GUIDE LINES (dragged from rulers)
  // ========================================================================

  function addPidGuide(axis: 'h' | 'v', position: number) {
    const id = `guide-${Date.now()}-${Math.random().toString(36).slice(2, 5)}`
    const guides = [...(pidLayer.value.guides || []), { id, axis, position }]
    pidLayer.value = { ...pidLayer.value, guides }
  }

  function removePidGuide(id: string) {
    const guides = (pidLayer.value.guides || []).filter(g => g.id !== id)
    pidLayer.value = { ...pidLayer.value, guides }
  }

  function updatePidGuide(id: string, position: number) {
    const guides = (pidLayer.value.guides || []).map(g =>
      g.id === id ? { ...g, position } : g
    )
    pidLayer.value = { ...pidLayer.value, guides }
  }

  // ========================================================================
  // P&ID NAMED LAYERS
  // ========================================================================

  const pidActiveLayerId = ref('main')

  function ensureLayerInfos(): PidLayerInfo[] {
    if (!pidLayer.value.layerInfos || pidLayer.value.layerInfos.length === 0) {
      return [{ id: 'main', name: 'Main', visible: true, locked: false, opacity: 1, order: 0 }]
    }
    return pidLayer.value.layerInfos
  }

  function pidAddLayer(name: string): string {
    const beforeState = createPidStateSnapshot()
    const infos = ensureLayerInfos()
    const id = `layer-${Date.now()}-${Math.random().toString(36).slice(2, 5)}`
    const newInfo: PidLayerInfo = { id, name, visible: true, locked: false, opacity: 1, order: infos.length }
    pidLayer.value = { ...pidLayer.value, layerInfos: [...infos, newInfo] }
    pidActiveLayerId.value = id
    pushPidCommand('modify', `Add layer "${name}"`, beforeState)
    saveLayoutToStorage()
    return id
  }

  function pidRemoveLayer(layerId: string) {
    const beforeState = createPidStateSnapshot()
    const infos = ensureLayerInfos()
    if (infos.length <= 1) return // Can't remove last layer
    const mainId = infos[0]!.id
    // Move elements from removed layer to first layer
    const symbols = pidLayer.value.symbols.map(s =>
      s.layerId === layerId ? { ...s, layerId: mainId } : s
    )
    const pipes = pidLayer.value.pipes.map(p =>
      p.layerId === layerId ? { ...p, layerId: mainId } : p
    )
    const textAnnotations = (pidLayer.value.textAnnotations || []).map(t =>
      t.layerId === layerId ? { ...t, layerId: mainId } : t
    )
    const newInfos = infos.filter(l => l.id !== layerId).map((l, i) => ({ ...l, order: i }))
    pidLayer.value = { ...pidLayer.value, layerInfos: newInfos, symbols, pipes, textAnnotations }
    if (pidActiveLayerId.value === layerId) {
      pidActiveLayerId.value = newInfos[0]?.id || 'main'
    }
    pushPidCommand('modify', 'Remove layer', beforeState)
    saveLayoutToStorage()
  }

  function pidRenameLayer(layerId: string, name: string) {
    const beforeState = createPidStateSnapshot()
    const infos = ensureLayerInfos()
    pidLayer.value = {
      ...pidLayer.value,
      layerInfos: infos.map(l => l.id === layerId ? { ...l, name } : l)
    }
    pushPidCommand('modify', `Rename layer to "${name}"`, beforeState)
    saveLayoutToStorage()
  }

  function pidToggleLayerVisibility(layerId: string) {
    const infos = ensureLayerInfos()
    pidLayer.value = {
      ...pidLayer.value,
      layerInfos: infos.map(l => l.id === layerId ? { ...l, visible: !l.visible } : l)
    }
  }

  function pidToggleLayerLock(layerId: string) {
    const infos = ensureLayerInfos()
    pidLayer.value = {
      ...pidLayer.value,
      layerInfos: infos.map(l => l.id === layerId ? { ...l, locked: !l.locked } : l)
    }
  }

  function pidSetLayerOpacity(layerId: string, opacity: number) {
    const infos = ensureLayerInfos()
    pidLayer.value = {
      ...pidLayer.value,
      layerInfos: infos.map(l => l.id === layerId ? { ...l, opacity } : l)
    }
  }

  function pidMoveToLayer(targetLayerId: string) {
    const symbolIds = pidSelectedIds.value.symbolIds
    const pipeIds = pidSelectedIds.value.pipeIds
    const textIds = pidSelectedIds.value.textAnnotationIds
    if (symbolIds.length === 0 && pipeIds.length === 0 && textIds.length === 0) return

    const symbols = pidLayer.value.symbols.map(s =>
      symbolIds.includes(s.id) ? { ...s, layerId: targetLayerId } : s
    )
    const pipes = pidLayer.value.pipes.map(p =>
      pipeIds.includes(p.id) ? { ...p, layerId: targetLayerId } : p
    )
    const textAnnotations = (pidLayer.value.textAnnotations || []).map(t =>
      textIds.includes(t.id) ? { ...t, layerId: targetLayerId } : t
    )
    pidLayer.value = { ...pidLayer.value, symbols, pipes, textAnnotations }
  }

  function pidReorderLayers(fromIndex: number, toIndex: number) {
    const infos = ensureLayerInfos()
    const sorted = [...infos].sort((a, b) => a.order - b.order)
    const [moved] = sorted.splice(fromIndex, 1)
    if (!moved) return
    sorted.splice(toIndex, 0, moved)
    const reordered = sorted.map((l, i) => ({ ...l, order: i }))
    pidLayer.value = { ...pidLayer.value, layerInfos: reordered }
  }

  function isLayerLocked(layerId: string | undefined): boolean {
    const infos = pidLayer.value.layerInfos
    if (!infos || infos.length === 0) return false
    const info = infos.find(l => l.id === (layerId || 'main'))
    return info?.locked ?? false
  }

  // ========================================================================
  // ENHANCED P&ID SYMBOL/PIPE ACTIONS (with Undo support)
  // ========================================================================

  /**
   * Add symbol with undo support
   */
  function addPidSymbolWithUndo(symbol: Omit<PidSymbol, 'id'>): string {
    const beforeState = createPidStateSnapshot()
    const id = addPidSymbol(symbol)
    pushPidCommand('add', `Add ${symbol.type} symbol`, beforeState)
    return id
  }

  /**
   * Update symbol with undo support
   */
  function updatePidSymbolWithUndo(id: string, updates: Partial<PidSymbol>) {
    const beforeState = createPidStateSnapshot()
    updatePidSymbol(id, updates)
    pushPidCommand('modify', 'Update symbol', beforeState)
  }

  /**
   * Remove symbol with undo support
   */
  function removePidSymbolWithUndo(id: string) {
    const beforeState = createPidStateSnapshot()
    removePidSymbol(id)
    pushPidCommand('delete', 'Delete symbol', beforeState)
  }

  /**
   * Add pipe with undo support
   */
  function addPidPipeWithUndo(pipe: Omit<PidPipe, 'id'>): string {
    const beforeState = createPidStateSnapshot()
    const id = addPidPipe(pipe)
    pushPidCommand('add', 'Add pipe', beforeState)
    return id
  }

  /**
   * Update pipe with undo support
   */
  function updatePidPipeWithUndo(id: string, updates: Partial<PidPipe>) {
    const beforeState = createPidStateSnapshot()
    updatePidPipe(id, updates)
    pushPidCommand('modify', 'Update pipe', beforeState)
  }

  /**
   * Remove pipe with undo support
   */
  function removePidPipeWithUndo(id: string) {
    const beforeState = createPidStateSnapshot()
    removePidPipe(id)
    pushPidCommand('delete', 'Delete pipe', beforeState)
  }

  /**
   * Batch update multiple symbols with a single undo command
   */
  function updatePidSymbolsBatch(ids: string[], updates: Partial<PidSymbol>) {
    if (ids.length === 0) return
    const beforeState = createPidStateSnapshot()
    for (const id of ids) {
      updatePidSymbol(id, updates)
    }
    pushPidCommand('modify', `Update ${ids.length} symbols`, beforeState)
  }

  /**
   * Auto-match selected symbol labels to channel names.
   * Returns number of symbols matched.
   * Matching strategy (in priority order):
   * 1. Exact match: symbol.label === channel.name (case-insensitive)
   * 2. Tag prefix match: symbol.label starts with channel tag prefix (e.g., "TC-001" matches "TC-001_PV")
   * 3. Fuzzy substring: channel.name contains symbol.label or vice versa
   */
  function pidAutoMatchChannels(symbolIds?: string[]): { matched: number; total: number } {
    const ids = symbolIds || pidSelectedIds.value.symbolIds
    const targetSymbols = pidLayer.value.symbols.filter(s => ids.includes(s.id))
    if (targetSymbols.length === 0) return { matched: 0, total: 0 }

    const chNames = Object.keys(channels.value)
    if (chNames.length === 0) return { matched: 0, total: targetSymbols.length }

    const beforeState = createPidStateSnapshot()
    let matched = 0

    for (const sym of targetSymbols) {
      const label = (sym.label || '').trim()
      if (!label) continue
      if (sym.channel) continue // skip already bound

      const labelLower = label.toLowerCase()

      // 1. Exact match
      let match = chNames.find(ch => ch.toLowerCase() === labelLower)

      // 2. Tag prefix — label is a prefix of channel name (e.g., "TC-001" → "TC-001_PV")
      if (!match) {
        match = chNames.find(ch => ch.toLowerCase().startsWith(labelLower + '_') || ch.toLowerCase().startsWith(labelLower + '/'))
      }

      // 3. Channel contains label or label contains channel
      if (!match) {
        match = chNames.find(ch => ch.toLowerCase().includes(labelLower) || labelLower.includes(ch.toLowerCase()))
      }

      if (match) {
        updatePidSymbol(sym.id, { channel: match })
        matched++
      }
    }

    if (matched > 0) {
      pushPidCommand('modify', `Auto-match ${matched} channels`, beforeState)
    }

    return { matched, total: targetSymbols.length }
  }

  // ========================================================================
  // P&ID TEMPLATE MANAGEMENT
  // ========================================================================

  /**
   * Create a template from selected elements
   */
  function createPidTemplate(name: string, description?: string, category?: string): string | null {
    if (!hasPidSelection.value) return null

    // Get selected elements
    const selectedSymbols = pidLayer.value.symbols.filter(s =>
      pidSelectedIds.value.symbolIds.includes(s.id)
    )
    const selectedPipes = pidLayer.value.pipes.filter(p =>
      pidSelectedIds.value.pipeIds.includes(p.id)
    )
    const selectedTextAnnotations = (pidLayer.value.textAnnotations || []).filter(t =>
      pidSelectedIds.value.textAnnotationIds.includes(t.id)
    )

    if (selectedSymbols.length === 0 && selectedPipes.length === 0 && selectedTextAnnotations.length === 0) {
      return null
    }

    // Calculate bounding box
    let minX = Infinity, minY = Infinity
    selectedSymbols.forEach(s => {
      minX = Math.min(minX, s.x)
      minY = Math.min(minY, s.y)
    })
    selectedPipes.forEach(p => {
      p.points.forEach(pt => {
        minX = Math.min(minX, pt.x)
        minY = Math.min(minY, pt.y)
      })
    })
    selectedTextAnnotations.forEach(t => {
      minX = Math.min(minX, t.x)
      minY = Math.min(minY, t.y)
    })

    // Create template with relative positions
    const template: PidTemplate = {
      id: `template-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
      name,
      description,
      category,
      symbols: selectedSymbols.map(({ id: _id, ...rest }) => ({
        ...rest,
        offsetX: rest.x - minX,
        offsetY: rest.y - minY
      })),
      pipes: selectedPipes.map(({ id: _id, ...rest }) => ({
        ...rest,
        offsetPoints: rest.points.map(pt => ({ x: pt.x - minX, y: pt.y - minY }))
      })),
      textAnnotations: selectedTextAnnotations.map(({ id: _id, ...rest }) => ({
        ...rest,
        offsetX: rest.x - minX,
        offsetY: rest.y - minY
      })),
      createdAt: new Date().toISOString()
    }

    pidTemplates.value.push(template)
    savePidTemplates()

    return template.id
  }

  /**
   * Instantiate a template at a given position
   */
  function instantiatePidTemplate(templateId: string, x: number, y: number): string[] {
    const template = pidTemplates.value.find(t => t.id === templateId)
    if (!template) return []

    const beforeState = createPidStateSnapshot()
    const newIds: string[] = []

    // Create new symbols
    for (const symbolDef of template.symbols) {
      const newId = `pid-symbol-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`
      const { offsetX, offsetY, ...symbolProps } = symbolDef
      const newSymbol: PidSymbol = {
        ...symbolProps,
        id: newId,
        x: x + offsetX,
        y: y + offsetY
      }

      pidLayer.value = {
        ...pidLayer.value,
        symbols: [...pidLayer.value.symbols, newSymbol]
      }
      newIds.push(newId)
    }

    // Create new pipes
    for (const pipeDef of template.pipes) {
      const newId = `pid-pipe-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`
      const { offsetPoints, ...pipeProps } = pipeDef
      const newPipe: PidPipe = {
        ...pipeProps,
        id: newId,
        points: offsetPoints.map(pt => ({ x: x + pt.x, y: y + pt.y }))
      }

      pidLayer.value = {
        ...pidLayer.value,
        pipes: [...pidLayer.value.pipes, newPipe]
      }
      newIds.push(newId)
    }

    // Create new text annotations
    for (const textDef of template.textAnnotations) {
      const newId = `pid-text-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`
      const { offsetX, offsetY, ...textProps } = textDef
      const newText: PidTextAnnotation = {
        ...textProps,
        id: newId,
        x: x + offsetX,
        y: y + offsetY
      }

      pidLayer.value = {
        ...pidLayer.value,
        textAnnotations: [...(pidLayer.value.textAnnotations || []), newText]
      }
      newIds.push(newId)
    }

    pushPidCommand('add', `Instantiate template: ${template.name}`, beforeState)
    saveLayoutToStorage()

    return newIds
  }

  /**
   * Delete a template from the library
   */
  function deletePidTemplate(templateId: string): boolean {
    const index = pidTemplates.value.findIndex(t => t.id === templateId)
    if (index === -1) return false

    pidTemplates.value.splice(index, 1)
    savePidTemplates()
    return true
  }

  // ========================================================================
  // LAYOUT PERSISTENCE (with multi-page support)
  // ========================================================================

  function getLayout(): LayoutConfig {
    return {
      system_id: systemId.value,
      widgets: currentPage.value?.widgets || [],  // Legacy: current page widgets
      gridColumns: gridColumns.value,
      rowHeight: rowHeight.value,
      pages: pages.value,
      currentPageId: currentPageId.value
    }
  }

  function setLayout(layout: LayoutConfig) {
    console.log('[DASHBOARD STORE] setLayout called with:', {
      gridColumns: layout.gridColumns,
      rowHeight: layout.rowHeight,
      hasPages: !!layout.pages && layout.pages.length > 0,
      pageCount: layout.pages?.length || 0,
      hasLegacyWidgets: !!layout.widgets && layout.widgets.length > 0,
      legacyWidgetCount: layout.widgets?.length || 0
    })

    gridColumns.value = layout.gridColumns
    rowHeight.value = layout.rowHeight

    // Handle multi-page layouts
    if (layout.pages && layout.pages.length > 0) {
      console.log('[DASHBOARD STORE] Setting multi-page layout with', layout.pages.length, 'pages')
      // Deep clone to ensure Vue's reactivity system properly tracks all nested widget properties
      // This fixes issues where widget props (like label) weren't being reactive on initial load
      pages.value = JSON.parse(JSON.stringify(layout.pages))

      // Log each page
      layout.pages.forEach((page, idx) => {
        console.log(`[DASHBOARD STORE] Page ${idx}: ${page.name} (id: ${page.id}, widgets: ${page.widgets?.length || 0})`)
      })

      // Always start on Page 1 (first page by order), not last viewed page
      const firstPage = [...layout.pages].sort((a, b) => (a.order ?? 0) - (b.order ?? 0))[0]
      currentPageId.value = firstPage?.id || layout.pages[0]!.id
      console.log('[DASHBOARD STORE] Current page set to:', currentPageId.value)
    } else if (layout.widgets && layout.widgets.length > 0) {
      // Legacy single-page layout - migrate to multi-page
      console.log('[DASHBOARD STORE] Migrating legacy single-page layout to multi-page (widgets:', layout.widgets.length, ')')
      // Deep clone widgets to ensure Vue's reactivity properly tracks all nested properties
      pages.value = [{
        id: 'default',
        name: 'Page 1',
        widgets: JSON.parse(JSON.stringify(layout.widgets)),
        order: 0
      }]
      currentPageId.value = 'default'
    } else {
      // No pages and no widgets - create empty default page
      console.warn('[DASHBOARD STORE] ⚠️ No pages or widgets provided - creating empty default page')
      ensureDefaultPage()
    }

    console.log('[DASHBOARD STORE] ✅ Layout set successfully. Total pages:', pages.value.length)
    console.log('[DASHBOARD STORE] Current page widgets:', widgets.value.length)

    // Validation: Ensure we always have at least one page
    if (pages.value.length === 0) {
      console.error('[DASHBOARD STORE] ❌ CRITICAL: No pages after setLayout! Creating default page...')
      ensureDefaultPage()
    }

    // Increment layout version to force widget re-render
    layoutVersion.value++
    console.log('[DASHBOARD STORE] Layout version:', layoutVersion.value)
  }

  function saveLayoutToStorage() {
    try {
      const layout = getLayout()
      localStorage.setItem(`nisystem-layout-${systemId.value}`, JSON.stringify(layout))
    } catch (e) {
      console.error('[DASHBOARD STORE] Failed to save layout to localStorage:', e)
    }
  }

  function loadLayoutFromStorage(): boolean {
    const stored = localStorage.getItem(`nisystem-layout-${systemId.value}`)
    if (stored) {
      try {
        const layout = JSON.parse(stored) as LayoutConfig
        // Migration: Remove boolean props that default to true when set to false
        // This fixes checkboxes that saved false instead of leaving undefined
        const migrateWidgets = (widgetList: WidgetConfig[]) => {
          const propsToClean: (keyof WidgetConfig)[] = [
            'showLabel', 'showUnit', 'showUnits', 'showValue',
            'showGrid', 'showLegend', 'yAxisAuto', 'showDate',
            'showAckButton'
          ]
          widgetList.forEach(w => {
            propsToClean.forEach(prop => {
              if (w[prop] === false) {
                delete w[prop]
              }
            })
          })
        }

        if (layout.pages) {
          layout.pages.forEach(p => migrateWidgets(p.widgets))
        }
        if (layout.widgets) {
          migrateWidgets(layout.widgets)
        }

        setLayout(layout)
        return true
      } catch (e) {
        console.error('Failed to load layout:', e)
      }
    }
    return false
  }

  // Auto-generate layout from channel config
  function generateDefaultLayout() {
    // Ensure we have a default page
    ensureDefaultPage()

    // Clear current page widgets
    const page = pages.value.find(p => p.id === currentPageId.value)
    if (page) {
      page.widgets = []
    }

    const groups = channelsByGroup.value
    let currentY = 0

    Object.entries(groups).forEach(([_groupName, groupChannels]) => {
      let x = 0
      let maxH = 1

      groupChannels.forEach(channel => {
        const widgetType = inferWidgetType(channel)
        const defaults = getWidgetDefaults(widgetType)

        // Wrap to next row if needed
        if (x + defaults.w > gridColumns.value) {
          x = 0
          currentY += maxH
          maxH = 1
        }

        addWidget({
          channel: channel.name,
          type: widgetType,
          x,
          y: currentY,
          w: defaults.w,
          h: defaults.h,
          label: channel.name  // TAG is the only identifier
        })

        x += defaults.w
        maxH = Math.max(maxH, defaults.h)
      })

      currentY += maxH
    })

    // Add one chart if there are chartable channels
    const chartableChannels = Object.values(channels.value)
      .filter(ch => ch.chartable || ch.channel_type === 'thermocouple' || ch.channel_type === 'voltage')
      .slice(0, 4)
      .map(ch => ch.name)

    if (chartableChannels.length > 0) {
      addWidget({
        type: 'chart',
        channels: chartableChannels,
        x: 8,
        y: 0,
        w: 4,
        h: 4,
        timeRange: 300
      })
    }
  }

  function inferWidgetType(channel: ChannelConfig): WidgetType {
    // Use explicit widget type if specified
    if (channel.widget) return channel.widget

    // Infer from channel type
    switch (channel.channel_type) {
      case 'digital_input':
        return 'led'
      case 'digital_output':
        return 'toggle'
      case 'analog_output':
        return 'setpoint'
      default:
        return 'numeric'
    }
  }

  // Widget defaults for 24-column grid (double the old 12-column values)
  // Row height is now 30px (was 60px), so h values stay same for same pixel height
  function getWidgetDefaults(type: WidgetType): { w: number; h: number } {
    const defaults: Record<WidgetType, { w: number; h: number }> = {
      numeric: { w: 2, h: 2 },      // 1 old cell = 2 new units
      gauge: { w: 4, h: 4 },        // 2 old cells = 4 new units
      led: { w: 2, h: 2 },          // 1 old cell
      chart: { w: 8, h: 6 },        // 4 old cells wide
      pid_loop: { w: 4, h: 6 },      // 2 old cells wide
      setpoint: { w: 3, h: 2 },     // 1.5 old cells - the sweet spot!
      toggle: { w: 2, h: 2 },       // 1 old cell
      title: { w: 4, h: 2 },        // 2 old cells
      sparkline: { w: 4, h: 2 },    // 2 old cells
      alarm_summary: { w: 4, h: 4 },
      recording_status: { w: 4, h: 4 },
      system_status: { w: 4, h: 4 },
      interlock_status: { w: 4, h: 4 },
      action_button: { w: 2, h: 2 },
      clock: { w: 4, h: 2 },
      divider: { w: 6, h: 2 },
      bar_graph: { w: 4, h: 2 },
      scheduler_status: { w: 4, h: 4 },
      svg_symbol: { w: 2, h: 2 },
      value_table: { w: 6, h: 8 },
      script_monitor: { w: 6, h: 8 },
      crio_status: { w: 4, h: 4 },
      latch_switch: { w: 2, h: 2 },
      heater_zone: { w: 4, h: 4 },
      python_console: { w: 8, h: 6 },
      script_output: { w: 8, h: 6 },
      variable_explorer: { w: 6, h: 8 },
      variable_input: { w: 4, h: 6 },
      status_messages: { w: 6, h: 4 },
      image: { w: 4, h: 4 },
      gc_chromatogram: { w: 8, h: 8 },
      gc_overview: { w: 12, h: 8 },
      small_multiples: { w: 8, h: 6 }
    }
    return defaults[type] || { w: 2, h: 2 }
  }

  // Load preset layout from JSON file
  async function loadPresetLayout(layoutName: string): Promise<boolean> {
    try {
      // Fetch layout from config directory
      const response = await fetch(`/config/${layoutName}.json`)
      if (!response.ok) {
        console.error(`Failed to load preset layout: ${layoutName}`)
        return false
      }

      const layoutData = await response.json()

      // Validate required fields
      if (!layoutData.widgets || !Array.isArray(layoutData.widgets)) {
        console.error('Invalid layout format: missing widgets array')
        return false
      }

      // Apply the layout
      const layout: LayoutConfig = {
        system_id: layoutData.system_id || 'default',
        widgets: layoutData.widgets,
        gridColumns: layoutData.gridColumns || 24,
        rowHeight: layoutData.rowHeight || 30
      }

      setLayout(layout)
      saveLayoutToStorage()

      console.log(`Loaded preset layout: ${layoutData.name || layoutName}`)
      return true
    } catch (error) {
      console.error('Error loading preset layout:', error)
      return false
    }
  }

  // Widget style update
  function updateWidgetStyle(widgetId: string, style: Partial<WidgetStyle>) {
    const widget = widgets.value.find(w => w.id === widgetId)
    if (widget) {
      widget.style = { ...widget.style, ...style }
    }
  }

  // Chart channel management
  function addChannelToChart(chartId: string, channelName: string) {
    const chart = widgets.value.find(w => w.id === chartId && w.type === 'chart')
    if (chart) {
      if (!chart.channels) chart.channels = []
      if (!chart.channels.includes(channelName)) {
        chart.channels.push(channelName)
      }
    }
  }

  function removeChannelFromChart(chartId: string, channelName: string) {
    const chart = widgets.value.find(w => w.id === chartId && w.type === 'chart')
    if (chart && chart.channels) {
      const index = chart.channels.indexOf(channelName)
      if (index !== -1) {
        chart.channels.splice(index, 1)
      }
    }
  }

  // Rename channel references in all widgets
  function renameChannelInWidgets(oldName: string, newName: string) {
    for (const widget of widgets.value) {
      // Single-channel widgets
      if (widget.channel === oldName) {
        widget.channel = newName
      }
      // Multi-channel widgets (charts)
      if (widget.channels && Array.isArray(widget.channels)) {
        const idx = widget.channels.indexOf(oldName)
        if (idx !== -1) {
          widget.channels[idx] = newName
        }
      }
    }
  }

  // Find widgets that reference non-existent channels
  function findOrphanedWidgets(): WidgetConfig[] {
    const channelNames = new Set(Object.keys(channels.value))
    return widgets.value.filter(widget => {
      // Single-channel widgets
      if (widget.channel && !channelNames.has(widget.channel)) {
        return true
      }
      // Multi-channel widgets (charts) - orphaned if ALL channels are missing
      if (widget.channels && widget.channels.length > 0) {
        const allMissing = widget.channels.every(ch => !channelNames.has(ch))
        return allMissing
      }
      return false
    })
  }

  // Remove widget references to a deleted channel
  function handleChannelDeleted(channelName: string) {
    // Remove from single-channel widgets
    const toRemove: string[] = []

    for (const widget of widgets.value) {
      if (widget.channel === channelName) {
        toRemove.push(widget.id)
      }
      // Remove from multi-channel widgets (charts)
      if (widget.channels && Array.isArray(widget.channels)) {
        const idx = widget.channels.indexOf(channelName)
        if (idx !== -1) {
          widget.channels.splice(idx, 1)
          // If chart has no channels left, mark for removal
          if (widget.channels.length === 0) {
            toRemove.push(widget.id)
          }
        }
      }
    }

    // Remove orphaned widgets
    for (const id of toRemove) {
      removeWidget(id)
    }

    // Also remove from channel values
    if (values.value[channelName]) {
      delete values.value[channelName]
    }

    return toRemove.length
  }

  // Clean up all orphaned widgets
  function cleanupOrphanedWidgets(): number {
    const orphans = findOrphanedWidgets()
    for (const widget of orphans) {
      removeWidget(widget.id)
    }
    return orphans.length
  }

  // Clear all values (reset to boot state with "--" displays)
  function clearValues() {
    values.value = {}
  }

  // ========================================================================
  // RECORDING CONFIGURATION ACTIONS (Data tab)
  // ========================================================================

  const RECORDING_CONFIG_KEY = 'nisystem-recording-config'
  const RECORDING_CHANNELS_KEY = 'nisystem-recording-channels'

  function setRecordingConfig(config: Partial<RecordingConfig>) {
    Object.assign(recordingConfig.value, config)
  }

  function setSelectedRecordingChannels(channelNames: string[]) {
    selectedRecordingChannels.value = channelNames
  }

  function setSelectAllRecordingChannels(selectAll: boolean) {
    selectAllRecordingChannels.value = selectAll
  }

  function loadRecordingConfigFromStorage() {
    try {
      const savedConfig = localStorage.getItem(RECORDING_CONFIG_KEY)
      if (savedConfig) {
        const parsed = JSON.parse(savedConfig)
        Object.assign(recordingConfig.value, parsed)
      }

      const savedChannels = localStorage.getItem(RECORDING_CHANNELS_KEY)
      if (savedChannels) {
        selectedRecordingChannels.value = JSON.parse(savedChannels)
      }
    } catch (e) {
      console.error('[STORE] Failed to load recording config from localStorage:', e)
    }
  }

  function saveRecordingConfigToStorage() {
    try {
      localStorage.setItem(RECORDING_CONFIG_KEY, JSON.stringify(recordingConfig.value))
      localStorage.setItem(RECORDING_CHANNELS_KEY, JSON.stringify(selectedRecordingChannels.value))
    } catch (e) {
      console.error('[STORE] Failed to save recording config to localStorage:', e)
    }
  }

  // Auto-persist recording config changes (debounced)
  let recordingConfigPersistTimer: ReturnType<typeof setTimeout> | null = null

  function persistRecordingConfigDebounced() {
    if (recordingConfigPersistTimer) clearTimeout(recordingConfigPersistTimer)
    recordingConfigPersistTimer = setTimeout(() => {
      saveRecordingConfigToStorage()
    }, 500)
  }

  // Watch for changes and auto-persist
  watch(recordingConfig, persistRecordingConfigDebounced, { deep: true })
  watch(selectedRecordingChannels, persistRecordingConfigDebounced, { deep: true })
  watch(selectAllRecordingChannels, persistRecordingConfigDebounced)

  // Load on store creation
  loadRecordingConfigFromStorage()

  // Ensure there's always a default page (Page 1) even with no project loaded
  ensureDefaultPage()

  return {
    // State
    systemId,
    systemName,
    mqttPrefix,
    channels,
    values,
    status,
    widgets,
    gridColumns,
    rowHeight,
    editMode,
    maxCharts,

    // Multi-page state
    pages,
    currentPageId,
    currentPage,
    sortedPages,
    layoutVersion,

    // Computed
    channelsByGroup,
    visibleChannels,
    visibleChannelsByGroup,
    chartWidgets,
    canAddChart,
    isAcquiring,
    isRecording,
    isSchedulerEnabled,
    isConnected,

    // Actions
    setChannels,
    updateValues,
    updateScriptValues,
    clearValues,
    setStatus,
    setSystemInfo,

    // Page management
    ensureDefaultPage,
    addPage,
    removePage,
    renamePage,
    switchPage,
    duplicatePage,
    movePage,
    setPageHierarchyLevel,
    setPageParent,
    getPagesByLevel,
    getChildPages,

    // Layout
    addWidget,
    removeWidget,
    moveWidgetToPage,
    copyWidgetToPage,
    updateWidget,
    updateWidgetPosition,
    updateWidgetStyle,
    setEditMode,
    toggleEditMode,
    autoGenerateWidgets,
    getLayout,
    setLayout,
    saveLayoutToStorage,
    loadLayoutFromStorage,
    generateDefaultLayout,
    loadPresetLayout,

    // Chart
    addChannelToChart,
    removeChannelFromChart,
    renameChannelInWidgets,

    // Channel lifecycle
    findOrphanedWidgets,
    handleChannelDeleted,
    cleanupOrphanedWidgets,

    // Pipes (Legacy grid-based P&ID connections)
    pipes,
    pipeDrawingMode,
    pipeDrawingStart,
    addPipe,
    updatePipe,
    removePipe,
    setPipeDrawingMode,
    startPipeDrawing,
    finishPipeDrawing,
    cancelPipeDrawing,

    // P&ID Canvas Layer (Free-form, pixel-based)
    pidLayer,
    pidEditMode,
    pidDrawingMode,
    pidGridSnapEnabled,
    pidGridSize,
    pidShowGrid,
    setPidEditMode,
    setPidDrawingMode,
    togglePidGridSnap,
    setPidGridSize,
    pidColorScheme,
    togglePidColorScheme,
    setPidColorScheme,
    pidOrthogonalPipes,
    pidZoom,
    pidPanX,
    pidPanY,
    pidSymbolPanelOpen,
    pidShowMinimap,
    pidShowRulers,
    pidAutoRoute,
    pidPropertiesPanelOpen,

    // P&ID Nozzle stubs
    pidShowNozzleStubs,

    // P&ID Panel collapse & resize
    pidCustomSymbols,
    pidAddCustomSymbol,
    pidRemoveCustomSymbol,
    pidFavoriteSymbols,
    pidRecentSymbols,
    pidToggleFavorite,
    pidTrackRecentSymbol,
    pidSymbolPanelCollapsed,
    pidPropertiesPanelCollapsed,
    pidSymbolPanelWidth,
    pidPropertiesPanelWidth,
    togglePidSymbolPanelCollapse,
    togglePidPropertiesPanelCollapse,

    // P&ID Focus mode
    pidFocusMode,
    pidToolbarCompact,
    togglePidFocusMode,
    setPidZoom,
    setPidPan,
    pidFitToContent,
    pidResetZoom,
    addPidSymbol,
    updatePidSymbol,
    removePidSymbol,
    addPidPipe,
    updatePidPipe,
    removePidPipe,
    updatePidLayer,
    clearPidLayer,
    setPidBackgroundImage,
    updatePidBackgroundImage,
    removePidBackgroundImage,

    // P&ID Undo/Redo
    pidUndoStack,
    pidRedoStack,
    canPidUndo,
    canPidRedo,
    pidUndo,
    pidRedo,
    clearPidHistory,
    pushPidCommand,
    createPidStateSnapshot,

    // P&ID Copy/Paste/Duplicate
    pidClipboard,
    hasPidClipboard,
    pidCopy,
    pidPaste,
    pidDuplicate,
    pidCut,

    // P&ID Selection
    pidSelectedIds,
    hasPidSelection,
    pidSelectItems,
    pidAddToSelection,
    pidRemoveFromSelection,
    pidToggleSelection,
    pidClearSelection,
    pidSelectAll,
    pidDeleteSelected,
    pidMoveSelected,
    pidBringToFront,
    pidSendToBack,

    // P&ID Alignment
    pidAlignLeft,
    pidAlignCenterH,
    pidAlignRight,
    pidAlignTop,
    pidAlignCenterV,
    pidAlignBottom,
    pidDistributeH,
    pidDistributeV,

    // P&ID Grouping
    pidGroup,
    pidUngroup,
    pidGetGroup,
    pidSelectGroup,

    // P&ID Text Annotations
    addPidTextAnnotation,
    updatePidTextAnnotation,
    removePidTextAnnotation,

    // P&ID Guide Lines
    addPidGuide,
    removePidGuide,
    updatePidGuide,

    // P&ID Named Layers
    pidActiveLayerId,
    pidAddLayer,
    pidRemoveLayer,
    pidRenameLayer,
    pidToggleLayerVisibility,
    pidToggleLayerLock,
    pidSetLayerOpacity,
    pidMoveToLayer,
    pidReorderLayers,
    isLayerLocked,

    // P&ID Enhanced Actions (with Undo)
    addPidSymbolWithUndo,
    updatePidSymbolWithUndo,
    updatePidSymbolsBatch,
    pidAutoMatchChannels,
    removePidSymbolWithUndo,
    addPidPipeWithUndo,
    updatePidPipeWithUndo,
    removePidPipeWithUndo,

    // P&ID Templates
    pidTemplates,
    createPidTemplate,
    instantiatePidTemplate,
    deletePidTemplate,

    // P&ID Operator Notes
    pidOperatorNotes,
    pidAddOperatorNote,
    pidUpdateOperatorNote,
    pidRemoveOperatorNote,
    pidClearOperatorNotes,

    // P&ID Pipe Drawing Defaults
    pidPipeColor,
    pidPipeDashed,
    pidPipeAnimated,
    pidStyleClipboard,
    pidCopyStyle,
    pidPasteStyle,

    // Recording configuration (Data tab)
    recordingConfig,
    selectedRecordingChannels,
    selectAllRecordingChannels,
    setRecordingConfig,
    setSelectedRecordingChannels,
    setSelectAllRecordingChannels,
    loadRecordingConfigFromStorage,
    saveRecordingConfigToStorage
  }
})
