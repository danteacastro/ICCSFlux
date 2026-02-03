<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, inject } from 'vue'
import { useDashboardStore } from '../stores/dashboard'
import { useMqtt } from '../composables/useMqtt'
import { usePythonScripts } from '../composables/usePythonScripts'
import { useProjectFiles } from '../composables/useProjectFiles'
import { useAzureIot } from '../composables/useAzureIot'

const store = useDashboardStore()
const mqtt = useMqtt()
const pythonScripts = usePythonScripts()
const projectFiles = useProjectFiles()
const azureIot = useAzureIot()

// Azure IoT configuration state
const showAzureConfig = ref(false)
const azureConnectionString = ref('')
const azureChannels = ref<string[]>([])
const azureBatchSize = ref(10)
const azureBatchInterval = ref(1000)

// PostgreSQL configuration state
const showPostgresConfig = ref(false)
const dbTestStatus = ref<{ testing: boolean, result: string | null, success: boolean | null }>({
  testing: false, result: null, success: null
})

// Permission-based edit control (injected from App.vue)
const hasEditPermission = inject<{ value: boolean }>('canEditData', ref(true))
const showLoginDialogFn = inject<() => void>('showLoginDialog', () => {})

// Use store's recording config (auto-persisted to localStorage)
const recordingConfig = computed(() => store.recordingConfig)
const selectedChannels = computed({
  get: () => store.selectedRecordingChannels,
  set: (val) => store.setSelectedRecordingChannels(val)
})
const selectAllChannels = computed({
  get: () => store.selectAllRecordingChannels,
  set: (val) => store.setSelectAllRecordingChannels(val)
})

// Recording State (from backend)
const isRecording = computed(() => store.status?.recording || false)
const recordingFile = computed(() => store.status?.recording_filename || '')
const recordingDuration = computed(() => store.status?.recording_duration || '00:00:00')
const recordingSize = computed(() => store.status?.recording_bytes || 0)
const recordingSamples = computed(() => store.status?.recording_samples || 0)
const recordingMode = computed(() => store.status?.recording_mode || 'manual')

// Configuration is locked while recording (industrial standard)
const configLocked = computed(() => isRecording.value)

// File browser state
const showFileBrowser = ref(false)
const selectedFile = ref<string | null>(null)

// Feedback
const feedbackMessage = ref<{ type: 'success' | 'error' | 'info', text: string } | null>(null)

function showFeedback(type: 'success' | 'error' | 'info', text: string, duration = 3000) {
  feedbackMessage.value = { type, text }
  setTimeout(() => {
    feedbackMessage.value = null
  }, duration)
}

// Available tags from store (channels + script-published values)
const availableChannels = computed(() => {
  // Hardware channels
  const hwChannels = Object.entries(store.channels).map(([name, config]) => ({
    name,  // TAG is the only identifier
    type: config.channel_type,
    unit: config.unit,
    group: config.group || 'Ungrouped',
    physical_channel: config.physical_channel || ''  // For module-based sorting
  }))

  // Script-published values (prefixed with py.)
  const scriptChannels = pythonScripts.getPublishedChannelNames().map(name => ({
    name,  // e.g., "py.Efficiency"
    type: 'computed',
    unit: pythonScripts.getPublishedUnits()[name] || '',
    group: 'Python Scripts'
  }))

  return [...hwChannels, ...scriptChannels]
})

// Natural sort comparator for alphanumeric strings
// Handles: tag_1, tag_2, tag_10 (not tag_1, tag_10, tag_2)
function naturalSort(a: string, b: string): number {
  const regex = /(\d+)|(\D+)/g
  const aParts = a.match(regex) || []
  const bParts = b.match(regex) || []

  for (let i = 0; i < Math.max(aParts.length, bParts.length); i++) {
    const aPart = aParts[i] || ''
    const bPart = bParts[i] || ''

    const aNum = parseInt(aPart, 10)
    const bNum = parseInt(bPart, 10)

    if (!isNaN(aNum) && !isNaN(bNum)) {
      // Both are numbers - compare numerically
      if (aNum !== bNum) return aNum - bNum
    } else {
      // At least one is text - compare alphabetically
      const cmp = aPart.localeCompare(bPart)
      if (cmp !== 0) return cmp
    }
  }
  return 0
}

// Sort by module first, then by channel index within module
// This ensures channels are grouped by physical hardware module
// E.g., Mod1/ai0, Mod1/ai1, Mod2/ai0, Mod2/ai1, Mod5/ai0, etc.
function moduleSort(a: { name: string, physical_channel?: string }, b: { name: string, physical_channel?: string }): number {
  const aPhys = a.physical_channel || ''
  const bPhys = b.physical_channel || ''

  // Extract module number (e.g., "Mod1/ai0" -> 1, "cDAQ1Mod2/ai3" -> 2)
  const aModMatch = aPhys.match(/Mod(\d+)/i)
  const bModMatch = bPhys.match(/Mod(\d+)/i)
  const aMod = aModMatch ? parseInt(aModMatch[1]!, 10) : 999
  const bMod = bModMatch ? parseInt(bModMatch[1]!, 10) : 999

  // Sort by module first
  if (aMod !== bMod) return aMod - bMod

  // Then by channel index (ai0, ai1, ... ai10, etc.)
  const aChMatch = aPhys.match(/[/]([a-z]+)(\d+)$/i)
  const bChMatch = bPhys.match(/[/]([a-z]+)(\d+)$/i)
  if (aChMatch && bChMatch) {
    // Same channel type prefix (ai, di, ao, do)
    if (aChMatch[1]! === bChMatch[1]!) {
      return parseInt(aChMatch[2]!, 10) - parseInt(bChMatch[2]!, 10)
    }
    // Different type, sort alphabetically (ai before ao before di before do)
    return aChMatch[1]!.localeCompare(bChMatch[1]!)
  }

  // Fallback to natural sort on name
  return naturalSort(a.name, b.name)
}

// Sorted channels: DAQ tags first (by module/channel), then Python script tags
// DAQ: Mod1/ai0, Mod1/ai1, ... Mod2/ai0, Mod2/ai1, ... Mod5/ai0, etc.
// Python: py.Efficiency, py.FlowRate, etc.
const sortedChannels = computed(() => {
  const daqChannels = availableChannels.value.filter(ch => !ch.name.startsWith('py.'))
  const pythonChannels = availableChannels.value.filter(ch => ch.name.startsWith('py.'))

  return [
    ...daqChannels.sort(moduleSort),
    ...pythonChannels.sort((a, b) => naturalSort(a.name, b.name))
  ]
})

// Check if we have both DAQ and Python channels (for separator display)
const hasPythonChannels = computed(() =>
  availableChannels.value.some(ch => ch.name.startsWith('py.'))
)

// Toggle channel selection
function toggleChannel(channelName: string) {
  const current = [...store.selectedRecordingChannels]
  const idx = current.indexOf(channelName)
  if (idx >= 0) {
    current.splice(idx, 1)
    store.setSelectedRecordingChannels(current)
    store.setSelectAllRecordingChannels(false)
  } else {
    current.push(channelName)
    store.setSelectedRecordingChannels(current)
    if (current.length === availableChannels.value.length) {
      store.setSelectAllRecordingChannels(true)
    }
  }
}

function toggleAllChannels() {
  if (selectAllChannels.value) {
    store.setSelectedRecordingChannels(availableChannels.value.map(ch => ch.name))
  } else {
    store.setSelectedRecordingChannels([])
  }
}

// Toggle schedule day
function toggleScheduleDay(day: string) {
  const days = [...store.recordingConfig.scheduleDays]
  const idx = days.indexOf(day)
  if (idx >= 0) {
    days.splice(idx, 1)
  } else {
    days.push(day)
  }
  store.setRecordingConfig({ scheduleDays: days })
}

// Effective sample rate in Hz
const effectiveSampleRate = computed(() => {
  let intervalSeconds = recordingConfig.value.sampleInterval
  if (recordingConfig.value.sampleIntervalUnit === 'milliseconds') {
    intervalSeconds = recordingConfig.value.sampleInterval / 1000
  }
  const baseRate = intervalSeconds > 0 ? 1 / intervalSeconds : 0
  return baseRate / recordingConfig.value.decimation
})

// Generate preview filename based on naming pattern
const previewFilename = computed(() => {
  const config = recordingConfig.value
  let name = config.filePrefix
  const date = new Date()

  if (config.namingPattern === 'timestamp') {
    if (config.includeDate) {
      name += `_${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
    }
    if (config.includeTime) {
      name += `_${String(date.getHours()).padStart(2, '0')}-${String(date.getMinutes()).padStart(2, '0')}-${String(date.getSeconds()).padStart(2, '0')}`
    }
  } else if (config.namingPattern === 'sequential') {
    name += `_${String(config.sequentialStart).padStart(config.sequentialPadding, '0')}`
  }

  if (config.includeChannelsInName) {
    const channelCount = selectAllChannels.value ? availableChannels.value.length : selectedChannels.value.length
    name += `_${channelCount}ch`
  }

  if (config.customSuffix) {
    name += `_${config.customSuffix}`
  }

  name += `.${config.fileFormat}`
  return name
})

// Preview directory path based on organization
const previewDirectory = computed(() => {
  const config = recordingConfig.value
  let path = config.basePath
  const date = new Date()

  if (config.directoryStructure === 'daily') {
    path += `/${date.getFullYear()}/${String(date.getMonth() + 1).padStart(2, '0')}/${String(date.getDate()).padStart(2, '0')}`
  } else if (config.directoryStructure === 'monthly') {
    path += `/${date.getFullYear()}/${String(date.getMonth() + 1).padStart(2, '0')}`
  } else if (config.directoryStructure === 'experiment' && config.experimentName) {
    path += `/${config.experimentName}`
  }

  return path
})

// Estimated file size per hour
const estimatedSizePerHour = computed(() => {
  const channelCount = selectAllChannels.value ? availableChannels.value.length : selectedChannels.value.length
  const samplesPerSecond = effectiveSampleRate.value
  const bytesPerSample = 20 // Approximate: timestamp + value + comma
  const bytesPerHour = channelCount * samplesPerSecond * 3600 * bytesPerSample
  return bytesPerHour / (1024 * 1024) // MB
})

// Start Recording
function startRecording() {
  if (!mqtt.connected.value) {
    showFeedback('error', 'Not connected to MQTT broker')
    return
  }

  const cfg = recordingConfig.value

  // Build config for backend
  const config = {
    // File settings
    base_path: cfg.basePath,
    file_prefix: cfg.filePrefix,
    file_format: cfg.fileFormat,

    // Logging rate
    sample_interval: cfg.sampleInterval,
    sample_interval_unit: cfg.sampleIntervalUnit,
    decimation: cfg.decimation,

    // File Rotation Strategy
    rotation_mode: cfg.rotationMode,
    max_file_size_mb: cfg.maxFileSize,
    max_file_duration_s: cfg.maxFileDuration,
    max_file_samples: cfg.maxFileSamples,

    // Naming Convention
    naming_pattern: cfg.namingPattern,
    include_date: cfg.includeDate,
    include_time: cfg.includeTime,
    include_channels_in_name: cfg.includeChannelsInName,
    sequential_start: cfg.sequentialStart,
    sequential_padding: cfg.sequentialPadding,
    custom_suffix: cfg.customSuffix,

    // Directory Organization
    directory_structure: cfg.directoryStructure,
    experiment_name: cfg.experimentName,

    // Buffer/Write Strategy
    write_mode: cfg.writeMode,
    buffer_size: cfg.bufferSize,
    flush_interval_s: cfg.flushInterval,

    // On Limit Reached
    on_limit_reached: cfg.onLimitReached,
    circular_max_files: cfg.circularMaxFiles,

    // Recording Mode
    mode: cfg.mode,
    selected_channels: selectAllChannels.value ? [] : selectedChannels.value,
    include_scripts: true,

    // Triggered Mode
    trigger_channel: cfg.triggerChannel,
    trigger_condition: cfg.triggerCondition,
    trigger_value: cfg.triggerValue,
    pre_trigger_samples: cfg.preTriggerSamples,
    post_trigger_samples: cfg.postTriggerSamples,

    // Scheduled Mode
    schedule_start: cfg.scheduleStart,
    schedule_end: cfg.scheduleEnd,
    schedule_days: cfg.scheduleDays,

    // ALCOA+ Data Integrity Settings (FDA 21 CFR Part 11)
    append_only: cfg.appendOnly,
    verify_on_close: cfg.verifyOnClose,
    include_audit_metadata: cfg.includeAuditMetadata,

    // PostgreSQL Database Storage
    db_enabled: cfg.dbEnabled,
    db_host: cfg.dbHost,
    db_port: cfg.dbPort,
    db_name: cfg.dbName,
    db_user: cfg.dbUser,
    db_password: cfg.dbPassword,
    db_table: cfg.dbTable,
    db_batch_size: cfg.dbBatchSize,
    db_timescale: cfg.dbTimescale
  }

  // Update config then start recording
  mqtt.updateRecordingConfig(config)

  // Use the system command to start recording
  mqtt.startRecording()
  showFeedback('info', 'Starting recording...')
}

// Stop Recording
function stopRecording() {
  mqtt.stopRecording()
  showFeedback('info', 'Stopping recording...')
}

// Load recorded files list
function loadRecordedFiles() {
  mqtt.listRecordedFiles()
  showFileBrowser.value = true
}

// Delete recorded file
function deleteFile(filename: string) {
  if (confirm(`Delete ${filename}?`)) {
    mqtt.deleteRecordedFile(filename)
    showFeedback('info', `Deleting ${filename}...`)
  }
}

// Download recorded file
function downloadFile(filename: string) {
  // For now, show the file path - actual download would need HTTP endpoint
  const file = mqtt.recordedFiles.value.find(f => f.name === filename)
  if (file) {
    showFeedback('info', `File path: ${file.path}`)
  }
}

// Azure IoT Hub methods
function openAzureConfig() {
  // Load current config into form
  azureChannels.value = [...azureIot.config.value.channels]
  azureBatchSize.value = azureIot.config.value.batch_size
  azureBatchInterval.value = azureIot.config.value.batch_interval_ms
  showAzureConfig.value = true
}

function saveAzureConfig() {
  const config: Record<string, unknown> = {
    channels: azureChannels.value,
    batch_size: azureBatchSize.value,
    batch_interval_ms: azureBatchInterval.value,
    enabled: azureIot.isEnabled.value,
  }

  // Only include connection string if provided (non-empty)
  if (azureConnectionString.value.trim()) {
    config.connection_string = azureConnectionString.value.trim()
  }

  azureIot.updateConfig(config)
  showFeedback('info', 'Saving Azure IoT configuration...')
  showAzureConfig.value = false
  azureConnectionString.value = '' // Clear for security
}

function toggleAzureStreaming() {
  if (azureIot.isEnabled.value) {
    azureIot.stop()
    showFeedback('info', 'Stopping Azure IoT streaming...')
  } else {
    azureIot.start()
    showFeedback('info', 'Starting Azure IoT streaming...')
  }
}

function selectAllAzureChannels() {
  azureChannels.value = availableChannels.value.map(ch => ch.name)
}

function clearAzureChannels() {
  azureChannels.value = []
}

// PostgreSQL methods
function openPostgresConfig() {
  showPostgresConfig.value = true
  dbTestStatus.value = { testing: false, result: null, success: null }
}

function testPostgresConnection() {
  const cfg = recordingConfig.value
  dbTestStatus.value = { testing: true, result: null, success: null }

  mqtt.testDbConnection({
    host: cfg.dbHost,
    port: cfg.dbPort,
    dbname: cfg.dbName,
    user: cfg.dbUser,
    password: cfg.dbPassword,
  })

  // Listen for response
  const unsub = mqtt.onRecordingResponse((result: { success: boolean, message: string }) => {
    dbTestStatus.value = {
      testing: false,
      result: result.message,
      success: result.success
    }
    unsub()
  })

  // Timeout after 10 seconds
  setTimeout(() => {
    if (dbTestStatus.value.testing) {
      dbTestStatus.value = { testing: false, result: 'Connection test timed out', success: false }
    }
  }, 10000)
}

function togglePostgresEnabled() {
  store.setRecordingConfig({ dbEnabled: !recordingConfig.value.dbEnabled })
}

// Cleanup on unmount
let unsubscribeProjectLoaded: (() => void) | null = null

onUnmounted(() => {
  if (unsubscribeProjectLoaded) unsubscribeProjectLoaded()
})

// Format helpers
function formatFileSize(bytes: number): string {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  if (bytes < 1024 * 1024 * 1024) return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
  return (bytes / (1024 * 1024 * 1024)).toFixed(2) + ' GB'
}

function formatDuration(seconds: number): string {
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = Math.floor(seconds % 60)

  if (h > 0) return `${h}h ${m}m ${s}s`
  if (m > 0) return `${m}m ${s}s`
  return `${s}s`
}

// Initialize
onMounted(() => {
  // Select all channels by default if none selected
  if (store.selectedRecordingChannels.length === 0) {
    store.setSelectAllRecordingChannels(true)
    store.setSelectedRecordingChannels(availableChannels.value.map(ch => ch.name))
  }

  // Fetch recording config and file list from backend
  if (mqtt.connected.value) {
    mqtt.getRecordingConfig()
    mqtt.listRecordedFiles()
    azureIot.refreshConfig()
  }

  // Subscribe to project loaded events - reload config when a new project is loaded
  unsubscribeProjectLoaded = projectFiles.onProjectLoaded(() => {
    console.log('[DataTab] Project loaded, reloading recording config from store...')
    store.loadRecordingConfigFromStorage()
    // Re-select all channels if nothing selected
    if (store.selectedRecordingChannels.length === 0) {
      store.setSelectAllRecordingChannels(true)
      store.setSelectedRecordingChannels(availableChannels.value.map(ch => ch.name))
    }
  })

  // Listen for recording responses
  mqtt.onRecordingResponse((response) => {
    if (response.success) {
      showFeedback('success', response.message)
      // Refresh file list after operations
      if (response.message?.includes('Deleted') || response.message?.includes('stopped')) {
        mqtt.listRecordedFiles()
      }
    } else {
      showFeedback('error', response.message || 'Recording operation failed')
    }
  })
})

// Watch for recorded files updates from MQTT
const displayedFiles = computed(() => {
  return mqtt.recordedFiles.value.map(f => ({
    name: f.name,
    path: f.path,
    size: f.size,
    duration: f.duration,
    created: f.created,
    channels: f.channels?.length || 0
  }))
})

// Schedule days labels
const scheduleDayLabels = [
  { id: 'mon', label: 'M' },
  { id: 'tue', label: 'T' },
  { id: 'wed', label: 'W' },
  { id: 'thu', label: 'T' },
  { id: 'fri', label: 'F' },
  { id: 'sat', label: 'S' },
  { id: 'sun', label: 'S' },
]
</script>

<template>
  <div class="data-tab">
    <!-- View-only notice DISABLED during development -->
    <!-- <div v-if="!hasEditPermission.value" class="view-only-notice">
      <span class="lock-icon">🔒</span>
      <span>View Only - Operator access required to manage recordings</span>
      <button class="login-link" @click="showLoginDialogFn">Login</button>
    </div> -->

    <!-- Recording Status Bar -->
    <div class="status-bar" :class="{ recording: isRecording }">
      <div class="status-left">
        <div class="status-indicator" :class="{ active: isRecording }">
          <span class="pulse" v-if="isRecording"></span>
          <span class="dot"></span>
        </div>
        <span class="status-text">{{ isRecording ? 'RECORDING' : 'IDLE' }}</span>
        <template v-if="isRecording">
          <span class="status-divider">|</span>
          <span class="status-info">{{ recordingFile }}</span>
          <span class="status-divider">|</span>
          <span class="status-info">{{ recordingDuration }}</span>
          <span class="status-divider">|</span>
          <span class="status-info">{{ formatFileSize(recordingSize) }}</span>
          <span class="status-divider">|</span>
          <span class="status-info">{{ recordingSamples.toLocaleString() }} samples</span>
          <span class="status-divider">|</span>
          <span class="status-info mode-badge">{{ recordingMode.toUpperCase() }}</span>
        </template>
      </div>
      <div class="status-right">
        <button
          v-if="!isRecording"
          class="record-btn start"
          @click="startRecording"
          :disabled="!mqtt.connected.value"
        >
          <span class="record-icon"></span>
          Start Recording
        </button>
        <button
          v-else
          class="record-btn stop"
          @click="stopRecording"
        >
          <span class="stop-icon"></span>
          Stop Recording
        </button>
      </div>
    </div>

    <!-- Feedback Message -->
    <Transition name="fade">
      <div v-if="feedbackMessage" class="feedback-message" :class="feedbackMessage.type">
        {{ feedbackMessage.text }}
      </div>
    </Transition>

    <!-- Main Configuration -->
    <div class="config-layout">
      <!-- Left Panel: Channel Selection -->
      <div class="channel-panel" :class="{ locked: configLocked }">
        <div v-if="configLocked" class="locked-overlay">
          <span class="lock-icon">🔒</span>
          <span>Locked while recording</span>
        </div>
        <div class="panel-header">
          <h3>Tags to Record</h3>
          <label class="select-all">
            <input type="checkbox" v-model="selectAllChannels" @change="toggleAllChannels" :disabled="configLocked" />
            <span>All Tags</span>
          </label>
        </div>

        <div class="channel-list">
          <!-- Flat sorted list - DAQ tags first, then Python script tags -->
          <template v-for="(ch, index) in sortedChannels" :key="ch.name">
            <!-- Show separator before first Python channel -->
            <div
              v-if="ch.name.startsWith('py.') && (index === 0 || !sortedChannels[index - 1]?.name.startsWith('py.'))"
              class="channel-group-separator"
            >
              <span>Python Script Outputs</span>
            </div>

            <div
              class="channel-item"
              :class="{
                selected: selectAllChannels || selectedChannels.includes(ch.name),
                disabled: configLocked,
                'python-channel': ch.name.startsWith('py.')
              }"
              @click="!configLocked && toggleChannel(ch.name)"
            >
              <input
                type="checkbox"
                :checked="selectAllChannels || selectedChannels.includes(ch.name)"
                :disabled="configLocked"
                @click.stop
                @change="toggleChannel(ch.name)"
              />
              <div class="channel-info">
                <span class="channel-name">{{ ch.name.replace(/^py\./, '') }}</span>
                <span class="channel-meta">{{ ch.type }} {{ ch.unit ? `(${ch.unit})` : '' }}</span>
              </div>
            </div>
          </template>

          <div v-if="availableChannels.length === 0" class="no-channels">
            <p>No tags configured</p>
            <p class="hint">Configure tags in the Configuration tab or add script outputs</p>
          </div>
        </div>

        <div class="channel-summary">
          {{ selectAllChannels ? availableChannels.length : selectedChannels.length }} tags selected
        </div>
      </div>

      <!-- Center Panel: Recording Settings -->
      <div class="settings-panel" :class="{ locked: configLocked }">
        <div v-if="configLocked" class="locked-banner">
          <span class="lock-icon">🔒</span>
          <span>Configuration locked while recording - stop recording to edit</span>
        </div>
        <!-- Sample Rate Section -->
        <div class="settings-section">
          <h3>Sample Rate</h3>

          <div class="form-row">
            <div class="form-group" style="flex: 2;">
              <label>Sample Interval</label>
              <input type="number" v-model.number="recordingConfig.sampleInterval" min="0.001" step="0.1" :disabled="configLocked" />
            </div>
            <div class="form-group" style="flex: 1;">
              <label>Unit</label>
              <select v-model="recordingConfig.sampleIntervalUnit" :disabled="configLocked">
                <option value="seconds">Seconds</option>
                <option value="milliseconds">Milliseconds</option>
              </select>
            </div>
            <div class="form-group" style="flex: 1;">
              <label>Decimal Points</label>
              <input type="number" v-model.number="recordingConfig.decimation" min="1" max="100" :disabled="configLocked" title="Precision for recorded values" />
            </div>
          </div>

          <div class="rate-info">
            <div class="rate-row">
              <span>Effective rate:</span>
              <strong>{{ effectiveSampleRate.toFixed(3) }} Hz</strong>
              <span class="rate-detail">(1 sample every {{ recordingConfig.sampleIntervalUnit === 'milliseconds' ? (recordingConfig.sampleInterval * recordingConfig.decimation) + 'ms' : (recordingConfig.sampleInterval * recordingConfig.decimation).toFixed(2) + 's' }})</span>
            </div>
            <div class="rate-row">
              <span>Est. file size:</span>
              <strong>~{{ estimatedSizePerHour.toFixed(1) }} MB/hour</strong>
            </div>
          </div>
        </div>

        <!-- File Rotation Strategy Section -->
        <div class="settings-section">
          <h3>File Rotation Strategy</h3>

          <div class="rotation-selector">
            <button
              class="rotation-btn"
              :class="{ active: recordingConfig.rotationMode === 'single' }"
              :disabled="configLocked"
              @click="recordingConfig.rotationMode = 'single'"
              title="One continuous file until manually stopped"
            >
              Single File
            </button>
            <button
              class="rotation-btn"
              :class="{ active: recordingConfig.rotationMode === 'time' }"
              :disabled="configLocked"
              @click="recordingConfig.rotationMode = 'time'"
              title="Create new file after time limit"
            >
              Time-Based
            </button>
            <button
              class="rotation-btn"
              :class="{ active: recordingConfig.rotationMode === 'size' }"
              :disabled="configLocked"
              @click="recordingConfig.rotationMode = 'size'"
              title="Create new file after size limit"
            >
              Size-Based
            </button>
            <button
              class="rotation-btn"
              :class="{ active: recordingConfig.rotationMode === 'samples' }"
              :disabled="configLocked"
              @click="recordingConfig.rotationMode = 'samples'"
              title="Create new file after sample count"
            >
              Sample Count
            </button>
            <button
              class="rotation-btn"
              :class="{ active: recordingConfig.rotationMode === 'session' }"
              :disabled="configLocked"
              @click="recordingConfig.rotationMode = 'session'"
              title="New file each start/stop cycle"
            >
              Session
            </button>
          </div>

          <!-- Rotation mode specific options -->
          <div v-if="recordingConfig.rotationMode === 'time'" class="rotation-options">
            <div class="form-group">
              <label>Split every (seconds)</label>
              <input type="number" v-model.number="recordingConfig.maxFileDuration" min="60" max="86400" :disabled="configLocked" />
            </div>
            <div class="quick-presets">
              <button :disabled="configLocked" @click="recordingConfig.maxFileDuration = 3600">1 hour</button>
              <button :disabled="configLocked" @click="recordingConfig.maxFileDuration = 21600">6 hours</button>
              <button :disabled="configLocked" @click="recordingConfig.maxFileDuration = 43200">12 hours</button>
              <button :disabled="configLocked" @click="recordingConfig.maxFileDuration = 86400">24 hours</button>
            </div>
          </div>

          <div v-if="recordingConfig.rotationMode === 'size'" class="rotation-options">
            <div class="form-group">
              <label>Max file size (MB)</label>
              <input type="number" v-model.number="recordingConfig.maxFileSize" min="1" max="10000" :disabled="configLocked" />
            </div>
            <div class="quick-presets">
              <button :disabled="configLocked" @click="recordingConfig.maxFileSize = 50">50 MB</button>
              <button :disabled="configLocked" @click="recordingConfig.maxFileSize = 100">100 MB</button>
              <button :disabled="configLocked" @click="recordingConfig.maxFileSize = 500">500 MB</button>
              <button :disabled="configLocked" @click="recordingConfig.maxFileSize = 1000">1 GB</button>
            </div>
          </div>

          <div v-if="recordingConfig.rotationMode === 'samples'" class="rotation-options">
            <div class="form-group">
              <label>Max samples per file</label>
              <input type="number" v-model.number="recordingConfig.maxFileSamples" min="100" max="10000000" :disabled="configLocked" />
            </div>
            <div class="quick-presets">
              <button :disabled="configLocked" @click="recordingConfig.maxFileSamples = 1000">1K</button>
              <button :disabled="configLocked" @click="recordingConfig.maxFileSamples = 10000">10K</button>
              <button :disabled="configLocked" @click="recordingConfig.maxFileSamples = 100000">100K</button>
              <button :disabled="configLocked" @click="recordingConfig.maxFileSamples = 1000000">1M</button>
            </div>
          </div>

          <!-- On Limit Reached (for rotation modes except single/session) -->
          <div v-if="['time', 'size', 'samples'].includes(recordingConfig.rotationMode)" class="limit-action">
            <label class="section-label">When limit reached:</label>
            <div class="limit-selector">
              <label class="radio-label">
                <input type="radio" v-model="recordingConfig.onLimitReached" value="new_file" :disabled="configLocked" />
                <span>Start new file (continuous)</span>
              </label>
              <label class="radio-label">
                <input type="radio" v-model="recordingConfig.onLimitReached" value="stop" :disabled="configLocked" />
                <span>Stop recording</span>
              </label>
              <label class="radio-label">
                <input type="radio" v-model="recordingConfig.onLimitReached" value="circular" :disabled="configLocked" />
                <span>Circular (keep last N files)</span>
              </label>
            </div>
            <div v-if="recordingConfig.onLimitReached === 'circular'" class="form-group" style="margin-top: 8px;">
              <label>Keep last N files</label>
              <input type="number" v-model.number="recordingConfig.circularMaxFiles" min="2" max="1000" :disabled="configLocked" />
            </div>
          </div>
        </div>

        <!-- Naming Convention Section -->
        <div class="settings-section">
          <h3>Naming Convention</h3>

          <div class="naming-selector">
            <button
              class="naming-btn"
              :class="{ active: recordingConfig.namingPattern === 'timestamp' }"
              :disabled="configLocked"
              @click="recordingConfig.namingPattern = 'timestamp'"
            >
              Timestamp
            </button>
            <button
              class="naming-btn"
              :class="{ active: recordingConfig.namingPattern === 'sequential' }"
              :disabled="configLocked"
              @click="recordingConfig.namingPattern = 'sequential'"
            >
              Sequential
            </button>
            <button
              class="naming-btn"
              :class="{ active: recordingConfig.namingPattern === 'custom' }"
              :disabled="configLocked"
              @click="recordingConfig.namingPattern = 'custom'"
            >
              Custom Only
            </button>
          </div>

          <div class="form-row">
            <div class="form-group">
              <label>File Prefix</label>
              <input type="text" v-model="recordingConfig.filePrefix" placeholder="recording" :disabled="configLocked" />
            </div>
            <div class="form-group" style="flex: 0.5;">
              <label>Format</label>
              <select v-model="recordingConfig.fileFormat" :disabled="configLocked">
                <option value="csv">CSV</option>
                <option value="tdms">TDMS</option>
              </select>
            </div>
          </div>

          <!-- Timestamp naming options -->
          <div v-if="recordingConfig.namingPattern === 'timestamp'" class="naming-options">
            <div class="form-row checkboxes">
              <label class="checkbox-label">
                <input type="checkbox" v-model="recordingConfig.includeDate" :disabled="configLocked" />
                Include Date
              </label>
              <label class="checkbox-label">
                <input type="checkbox" v-model="recordingConfig.includeTime" :disabled="configLocked" />
                Include Time
              </label>
              <label class="checkbox-label">
                <input type="checkbox" v-model="recordingConfig.includeChannelsInName" :disabled="configLocked" />
                Include Tag Count
              </label>
            </div>
          </div>

          <!-- Sequential naming options -->
          <div v-if="recordingConfig.namingPattern === 'sequential'" class="naming-options">
            <div class="form-row">
              <div class="form-group">
                <label>Start Number</label>
                <input type="number" v-model.number="recordingConfig.sequentialStart" min="0" :disabled="configLocked" />
              </div>
              <div class="form-group">
                <label>Zero Padding</label>
                <select v-model.number="recordingConfig.sequentialPadding" :disabled="configLocked">
                  <option :value="2">2 digits (01)</option>
                  <option :value="3">3 digits (001)</option>
                  <option :value="4">4 digits (0001)</option>
                  <option :value="5">5 digits (00001)</option>
                </select>
              </div>
            </div>
          </div>

          <div class="form-group">
            <label>Custom Suffix (optional)</label>
            <input type="text" v-model="recordingConfig.customSuffix" placeholder="e.g., test_run_1" :disabled="configLocked" />
          </div>

          <div class="preview-filename">
            <label>Preview:</label>
            <code>{{ previewFilename }}</code>
          </div>
        </div>

        <!-- Directory Organization Section -->
        <div class="settings-section">
          <h3>Directory Organization</h3>

          <div class="form-group">
            <label>Base Save Location</label>
            <input
              type="text"
              v-model="recordingConfig.basePath"
              placeholder="/path/to/data"
              class="path-input"
              :disabled="configLocked"
            />
          </div>

          <div class="directory-selector">
            <button
              class="dir-btn"
              :class="{ active: recordingConfig.directoryStructure === 'flat' }"
              :disabled="configLocked"
              @click="recordingConfig.directoryStructure = 'flat'"
            >
              Flat
            </button>
            <button
              class="dir-btn"
              :class="{ active: recordingConfig.directoryStructure === 'daily' }"
              :disabled="configLocked"
              @click="recordingConfig.directoryStructure = 'daily'"
            >
              Daily Folders
            </button>
            <button
              class="dir-btn"
              :class="{ active: recordingConfig.directoryStructure === 'monthly' }"
              :disabled="configLocked"
              @click="recordingConfig.directoryStructure = 'monthly'"
            >
              Monthly Folders
            </button>
            <button
              class="dir-btn"
              :class="{ active: recordingConfig.directoryStructure === 'experiment' }"
              :disabled="configLocked"
              @click="recordingConfig.directoryStructure = 'experiment'"
            >
              Experiment
            </button>
          </div>

          <div v-if="recordingConfig.directoryStructure === 'experiment'" class="form-group">
            <label>Experiment Name</label>
            <input type="text" v-model="recordingConfig.experimentName" placeholder="experiment_1" :disabled="configLocked" />
          </div>

          <div class="preview-path">
            <label>Full Path Preview:</label>
            <code>{{ previewDirectory }}/{{ previewFilename }}</code>
          </div>
        </div>

        <!-- Buffer/Write Strategy Section -->
        <div class="settings-section">
          <h3>Write Strategy</h3>

          <div class="write-selector">
            <label class="radio-card" :class="{ active: recordingConfig.writeMode === 'immediate', disabled: configLocked }">
              <input type="radio" v-model="recordingConfig.writeMode" value="immediate" :disabled="configLocked" />
              <div class="radio-content">
                <strong>Immediate</strong>
                <span>Write each sample instantly - slower but safer</span>
              </div>
            </label>
            <label class="radio-card" :class="{ active: recordingConfig.writeMode === 'buffered', disabled: configLocked }">
              <input type="radio" v-model="recordingConfig.writeMode" value="buffered" :disabled="configLocked" />
              <div class="radio-content">
                <strong>Buffered</strong>
                <span>Batch writes for better performance</span>
              </div>
            </label>
          </div>

          <div v-if="recordingConfig.writeMode === 'buffered'" class="buffer-options">
            <div class="form-row">
              <div class="form-group">
                <label>Buffer Size (samples)</label>
                <input type="number" v-model.number="recordingConfig.bufferSize" min="10" max="10000" :disabled="configLocked" />
              </div>
              <div class="form-group">
                <label>Max Flush Interval (sec)</label>
                <input type="number" v-model.number="recordingConfig.flushInterval" min="1" max="60" step="0.5" :disabled="configLocked" />
              </div>
            </div>
            <div class="buffer-info">
              Writes to disk every {{ recordingConfig.bufferSize }} samples or {{ recordingConfig.flushInterval }}s, whichever comes first
            </div>
          </div>
        </div>

        <!-- ALCOA+ Data Integrity Section (FDA 21 CFR Part 11 Compliance) -->
        <div class="settings-section alcoa-section">
          <h3>
            <span>Data Integrity (ALCOA+)</span>
            <span class="compliance-badge">FDA 21 CFR Part 11</span>
          </h3>
          <p class="section-description">
            Ensures data is Attributable, Legible, Contemporaneous, Original, and Accurate.
          </p>

          <div class="alcoa-options">
            <label class="toggle-card" :class="{ active: recordingConfig.appendOnly, disabled: configLocked }">
              <div class="toggle-header">
                <input type="checkbox" v-model="recordingConfig.appendOnly" :disabled="configLocked" />
                <div class="toggle-content">
                  <strong>Append-Only Mode</strong>
                  <span>Files become read-only after recording stops</span>
                </div>
              </div>
              <div class="toggle-details" v-if="recordingConfig.appendOnly">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <rect x="3" y="11" width="18" height="11" rx="2" ry="2"/>
                  <path d="M7 11V7a5 5 0 0 1 10 0v4"/>
                </svg>
                <span>Data cannot be modified after recording - enforces "Original" requirement</span>
              </div>
            </label>

            <label class="toggle-card" :class="{ active: recordingConfig.verifyOnClose, disabled: configLocked }">
              <div class="toggle-header">
                <input type="checkbox" v-model="recordingConfig.verifyOnClose" :disabled="configLocked" />
                <div class="toggle-content">
                  <strong>Verify on Close</strong>
                  <span>Create SHA-256 checksum when file closes</span>
                </div>
              </div>
              <div class="toggle-details" v-if="recordingConfig.verifyOnClose">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
                </svg>
                <span>Creates companion .sha256 file for data integrity verification</span>
              </div>
            </label>

            <label class="toggle-card" :class="{ active: recordingConfig.includeAuditMetadata, disabled: configLocked }">
              <div class="toggle-header">
                <input type="checkbox" v-model="recordingConfig.includeAuditMetadata" :disabled="configLocked" />
                <div class="toggle-content">
                  <strong>Include Audit Metadata</strong>
                  <span>Embed operator, timestamps, and session info</span>
                </div>
              </div>
              <div class="toggle-details" v-if="recordingConfig.includeAuditMetadata">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/>
                  <circle cx="12" cy="7" r="4"/>
                </svg>
                <span>Records who started/stopped recording for audit trail</span>
              </div>
            </label>
          </div>

          <div class="alcoa-summary" v-if="recordingConfig.appendOnly || recordingConfig.verifyOnClose || recordingConfig.includeAuditMetadata">
            <div class="summary-header">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <polyline points="20 6 9 17 4 12"/>
              </svg>
              <span>ALCOA+ Compliance Features Enabled</span>
            </div>
            <div class="summary-items">
              <span v-if="recordingConfig.appendOnly" class="summary-item">Read-only after close</span>
              <span v-if="recordingConfig.verifyOnClose" class="summary-item">SHA-256 integrity</span>
              <span v-if="recordingConfig.includeAuditMetadata" class="summary-item">Audit attribution</span>
            </div>
          </div>
        </div>

        <div class="settings-section">
          <h3>Recording Mode</h3>

          <div class="mode-selector">
            <button
              class="mode-btn"
              :class="{ active: recordingConfig.mode === 'manual' }"
              :disabled="configLocked"
              @click="recordingConfig.mode = 'manual'"
            >
              Manual
            </button>
            <button
              class="mode-btn"
              :class="{ active: recordingConfig.mode === 'triggered' }"
              :disabled="configLocked"
              @click="recordingConfig.mode = 'triggered'"
            >
              Triggered
            </button>
            <button
              class="mode-btn"
              :class="{ active: recordingConfig.mode === 'scheduled' }"
              :disabled="configLocked"
              @click="recordingConfig.mode = 'scheduled'"
            >
              Scheduled
            </button>
          </div>

          <!-- Triggered Mode Options -->
          <div v-if="recordingConfig.mode === 'triggered'" class="mode-options">
            <div class="form-row">
              <div class="form-group">
                <label>Trigger Tag</label>
                <select v-model="recordingConfig.triggerChannel" :disabled="configLocked">
                  <option value="">Select tag...</option>
                  <option v-for="ch in availableChannels" :key="ch.name" :value="ch.name">
                    {{ ch.name.replace(/^py\./, '') }}
                  </option>
                </select>
              </div>
              <div class="form-group">
                <label>Condition</label>
                <select v-model="recordingConfig.triggerCondition" :disabled="configLocked">
                  <option value="above">Above</option>
                  <option value="below">Below</option>
                  <option value="change">Change</option>
                </select>
              </div>
            </div>
            <div class="form-row">
              <div class="form-group">
                <label>Trigger Value</label>
                <input type="number" v-model.number="recordingConfig.triggerValue" step="0.1" :disabled="configLocked" />
              </div>
              <div class="form-group">
                <label>Pre-trigger Samples</label>
                <input type="number" v-model.number="recordingConfig.preTriggerSamples" min="0" :disabled="configLocked" />
              </div>
              <div class="form-group">
                <label>Post-trigger Samples</label>
                <input type="number" v-model.number="recordingConfig.postTriggerSamples" min="0" :disabled="configLocked" />
              </div>
            </div>
          </div>

          <!-- Scheduled Mode Options -->
          <div v-if="recordingConfig.mode === 'scheduled'" class="mode-options">
            <div class="form-row">
              <div class="form-group">
                <label>Start Time</label>
                <input type="time" v-model="recordingConfig.scheduleStart" :disabled="configLocked" />
              </div>
              <div class="form-group">
                <label>End Time</label>
                <input type="time" v-model="recordingConfig.scheduleEnd" :disabled="configLocked" />
              </div>
            </div>
            <div class="form-group">
              <label>Days</label>
              <div class="day-selector">
                <button
                  v-for="day in scheduleDayLabels"
                  :key="day.id"
                  class="day-btn"
                  :class="{ active: recordingConfig.scheduleDays.includes(day.id) }"
                  :disabled="configLocked"
                  @click="toggleScheduleDay(day.id)"
                >
                  {{ day.label }}
                </button>
              </div>
            </div>
          </div>
        </div>

        <!-- Cloud Streaming Section -->
        <div class="settings-section cloud-section">
          <h3>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10z"/>
            </svg>
            Cloud Streaming
          </h3>

          <div class="cloud-destinations">
            <!-- CSV Recording -->
            <div class="destination-item">
              <div class="destination-header">
                <label class="destination-toggle">
                  <input
                    type="checkbox"
                    :checked="recordingConfig.csvEnabled"
                    :disabled="configLocked"
                    @change="store.setRecordingConfig({ csvEnabled: !recordingConfig.csvEnabled })"
                  />
                  <span class="toggle-label">CSV Recording</span>
                </label>
                <span
                  class="destination-status"
                  :class="recordingConfig.csvEnabled ? 'active' : 'inactive'"
                >
                  {{ recordingConfig.csvEnabled ? 'Enabled' : 'Disabled' }}
                </span>
              </div>
              <p class="destination-desc">Local file recording (configured above)</p>
            </div>

            <!-- Azure IoT Hub -->
            <div class="destination-item" :class="{ unavailable: !azureIot.available.value }">
              <div class="destination-header">
                <label class="destination-toggle">
                  <input
                    type="checkbox"
                    :checked="azureIot.isEnabled.value"
                    :disabled="!azureIot.hasConnectionString.value || configLocked"
                    @change="toggleAzureStreaming"
                  />
                  <span class="toggle-label">Azure IoT Hub</span>
                </label>
                <span
                  class="destination-status"
                  :class="{
                    active: azureIot.isConnected.value,
                    warning: azureIot.hasConnectionString.value && !azureIot.isConnected.value,
                    inactive: !azureIot.hasConnectionString.value
                  }"
                >
                  {{ azureIot.isConnected.value ? 'Connected' : (azureIot.hasConnectionString.value ? 'Disconnected' : 'Not Configured') }}
                </span>
              </div>
              <p class="destination-desc">
                Real-time telemetry to Azure IoT Hub
                <span v-if="!azureIot.available.value" class="sdk-warning">(SDK not installed)</span>
              </p>
              <button
                class="btn btn-sm btn-secondary"
                @click="openAzureConfig"
                :disabled="!azureIot.available.value"
              >
                Configure
              </button>
            </div>

            <!-- PostgreSQL Database -->
            <div class="destination-item">
              <div class="destination-header">
                <label class="destination-toggle">
                  <input
                    type="checkbox"
                    :checked="recordingConfig.dbEnabled"
                    :disabled="configLocked || !recordingConfig.dbHost"
                    @change="togglePostgresEnabled"
                  />
                  <span class="toggle-label">PostgreSQL</span>
                </label>
                <span
                  class="destination-status"
                  :class="{
                    active: recordingConfig.dbEnabled && store.status?.db_connected,
                    warning: recordingConfig.dbEnabled && !store.status?.db_connected,
                    inactive: !recordingConfig.dbEnabled
                  }"
                >
                  {{ recordingConfig.dbEnabled
                    ? (store.status?.db_connected ? 'Connected' : 'Enabled')
                    : 'Disabled' }}
                </span>
              </div>
              <p class="destination-desc">
                Store recording data in a PostgreSQL database
              </p>
              <button
                class="btn btn-sm btn-secondary"
                @click="openPostgresConfig"
              >
                Configure
              </button>
            </div>
          </div>
        </div>

        <div class="settings-actions">
          <button class="btn btn-secondary" @click="loadRecordedFiles">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
            </svg>
            Browse Files
          </button>
          <span class="auto-save-indicator">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <polyline points="20 6 9 17 4 12"/>
            </svg>
            Auto-saved
          </span>
        </div>
      </div>

      <!-- Right Panel: Quick Info -->
      <div class="info-panel">
        <div class="info-section">
          <h3>Recording Summary</h3>
          <div class="info-item">
            <span class="info-label">Tags:</span>
            <span class="info-value">{{ selectAllChannels ? availableChannels.length : selectedChannels.length }}</span>
          </div>
          <div class="info-item">
            <span class="info-label">Interval:</span>
            <span class="info-value">{{ recordingConfig.sampleInterval }} {{ recordingConfig.sampleIntervalUnit === 'milliseconds' ? 'ms' : 's' }}</span>
          </div>
          <div class="info-item">
            <span class="info-label">Effective Rate:</span>
            <span class="info-value">{{ effectiveSampleRate.toFixed(3) }} Hz</span>
          </div>
          <div class="info-item">
            <span class="info-label">Est. Size/Hour:</span>
            <span class="info-value">~{{ estimatedSizePerHour.toFixed(1) }} MB</span>
          </div>
          <div class="info-item">
            <span class="info-label">Rotation:</span>
            <span class="info-value rotation-badge" :class="recordingConfig.rotationMode">
              {{ recordingConfig.rotationMode }}
            </span>
          </div>
          <div class="info-item">
            <span class="info-label">Mode:</span>
            <span class="info-value mode-badge" :class="recordingConfig.mode">
              {{ recordingConfig.mode }}
            </span>
          </div>
        </div>

        <div class="info-section">
          <h3>Data Integrity</h3>
          <div class="alcoa-status" :class="{ enabled: recordingConfig.appendOnly || recordingConfig.verifyOnClose || recordingConfig.includeAuditMetadata }">
            <div class="alcoa-status-header">
              <span class="alcoa-label">ALCOA+</span>
              <span class="alcoa-badge" v-if="recordingConfig.appendOnly || recordingConfig.verifyOnClose || recordingConfig.includeAuditMetadata">
                Enabled
              </span>
              <span class="alcoa-badge off" v-else>
                Off
              </span>
            </div>
            <div class="alcoa-features" v-if="recordingConfig.appendOnly || recordingConfig.verifyOnClose || recordingConfig.includeAuditMetadata">
              <span v-if="recordingConfig.appendOnly" class="feature-dot" title="Append-Only">A</span>
              <span v-if="recordingConfig.verifyOnClose" class="feature-dot" title="Verify on Close">V</span>
              <span v-if="recordingConfig.includeAuditMetadata" class="feature-dot" title="Audit Metadata">M</span>
            </div>
          </div>
        </div>

        <div class="info-section">
          <h3>Connection</h3>
          <div class="connection-status" :class="{ connected: mqtt.connected.value }">
            {{ mqtt.connected.value ? 'MQTT Connected' : 'MQTT Disconnected' }}
          </div>
        </div>

        <div class="info-section" v-if="store.status">
          <h3>System Status</h3>
          <div class="info-item">
            <span class="info-label">Acquiring:</span>
            <span class="info-value" :class="{ active: store.status.acquiring }">
              {{ store.status.acquiring ? 'Yes' : 'No' }}
            </span>
          </div>
          <div class="info-item">
            <span class="info-label">Sample Rate:</span>
            <span class="info-value">{{ store.status.scan_rate_hz || '--' }} Hz</span>
          </div>
        </div>

        <!-- Azure IoT Hub Status -->
        <div class="info-section" v-if="azureIot.available.value && azureIot.hasConnectionString.value">
          <h3>Azure IoT Hub</h3>
          <div class="info-item">
            <span class="info-label">Status:</span>
            <span class="info-value" :class="{ active: azureIot.isConnected.value }">
              {{ azureIot.isConnected.value ? 'Connected' : 'Disconnected' }}
            </span>
          </div>
          <div class="info-item">
            <span class="info-label">Messages:</span>
            <span class="info-value">{{ azureIot.stats.value.messages_sent.toLocaleString() }}</span>
          </div>
          <div class="info-item">
            <span class="info-label">Samples:</span>
            <span class="info-value">{{ azureIot.stats.value.samples_sent.toLocaleString() }}</span>
          </div>
          <div class="info-item" v-if="azureIot.stats.value.last_error">
            <span class="info-label">Error:</span>
            <span class="info-value error">{{ azureIot.stats.value.last_error }}</span>
          </div>
        </div>

        <!-- PostgreSQL Status -->
        <div class="info-section" v-if="recordingConfig.dbEnabled">
          <h3>PostgreSQL</h3>
          <div class="info-item">
            <span class="info-label">Status:</span>
            <span class="info-value" :class="{ active: store.status?.db_connected }">
              {{ store.status?.db_connected ? 'Connected' : (isRecording ? 'Disconnected' : 'Idle') }}
            </span>
          </div>
          <div class="info-item" v-if="store.status?.db_rows_written">
            <span class="info-label">Rows:</span>
            <span class="info-value">{{ (store.status?.db_rows_written || 0).toLocaleString() }}</span>
          </div>
          <div class="info-item">
            <span class="info-label">Target:</span>
            <span class="info-value" style="font-size: 0.7rem;">{{ recordingConfig.dbHost }}:{{ recordingConfig.dbPort }}/{{ recordingConfig.dbName }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- File Browser Modal -->
    <Transition name="modal">
      <div v-if="showFileBrowser" class="modal-overlay" @click.self="showFileBrowser = false">
        <div class="file-browser-modal">
          <div class="modal-header">
            <h3>Recorded Files</h3>
            <button class="close-btn" @click="showFileBrowser = false">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
              </svg>
            </button>
          </div>

          <div class="modal-content">
            <div class="file-path">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
              </svg>
              {{ recordingConfig.basePath }}
            </div>

            <div v-if="displayedFiles.length > 0" class="file-list">
              <div
                v-for="file in displayedFiles"
                :key="file.name"
                class="file-item"
                :class="{ selected: selectedFile === file.name }"
                @click="selectedFile = file.name"
              >
                <div class="file-icon">
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                    <polyline points="14 2 14 8 20 8"/>
                  </svg>
                </div>
                <div class="file-info">
                  <span class="file-name">{{ file.name }}</span>
                  <span class="file-meta">
                    {{ formatFileSize(file.size) }} |
                    {{ formatDuration(file.duration) }} |
                    {{ file.channels }} channels |
                    {{ file.created }}
                  </span>
                </div>
                <div class="file-actions">
                  <button class="icon-btn" @click.stop="downloadFile(file.name)" title="Download">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                      <polyline points="7 10 12 15 17 10"/>
                      <line x1="12" y1="15" x2="12" y2="3"/>
                    </svg>
                  </button>
                  <button class="icon-btn danger" @click.stop="deleteFile(file.name)" title="Delete">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <polyline points="3 6 5 6 21 6"/>
                      <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
                    </svg>
                  </button>
                </div>
              </div>
            </div>

            <div v-else class="no-files">
              <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1">
                <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
              </svg>
              <p>No recorded files found</p>
              <p class="hint">Start a recording to create data files</p>
            </div>
          </div>

          <div class="modal-footer">
            <button class="btn btn-secondary" @click="showFileBrowser = false">Close</button>
          </div>
        </div>
      </div>
    </Transition>

    <!-- Azure IoT Configuration Modal -->
    <Transition name="modal">
      <div v-if="showAzureConfig" class="modal-overlay" @click.self="showAzureConfig = false">
        <div class="azure-config-modal">
          <div class="modal-header">
            <h3>
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10z"/>
              </svg>
              Azure IoT Hub Configuration
            </h3>
            <button class="close-btn" @click="showAzureConfig = false">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
              </svg>
            </button>
          </div>

          <div class="modal-content azure-config-content">
            <!-- Connection String -->
            <div class="form-group">
              <label>Device Connection String</label>
              <input
                type="password"
                v-model="azureConnectionString"
                placeholder="HostName=xxx.azure-devices.net;DeviceId=xxx;SharedAccessKey=xxx"
                class="connection-string-input"
              />
              <p class="field-hint">
                {{ azureIot.hasConnectionString.value ? 'Connection string configured. Enter new value to update.' : 'Get this from Azure Portal > IoT Hub > Devices > Your Device' }}
              </p>
            </div>

            <!-- Batch Settings -->
            <div class="form-row">
              <div class="form-group">
                <label>Batch Size</label>
                <input type="number" v-model.number="azureBatchSize" min="1" max="100" />
                <p class="field-hint">Samples per message</p>
              </div>
              <div class="form-group">
                <label>Batch Interval (ms)</label>
                <input type="number" v-model.number="azureBatchInterval" min="100" max="60000" step="100" />
                <p class="field-hint">Max time between sends</p>
              </div>
            </div>

            <!-- Channel Selection -->
            <div class="form-group">
              <label>
                Channels to Stream
                <span class="channel-count">({{ azureChannels.length }} selected)</span>
              </label>
              <div class="channel-actions">
                <button class="btn btn-xs" @click="selectAllAzureChannels">Select All</button>
                <button class="btn btn-xs" @click="clearAzureChannels">Clear</button>
              </div>
              <div class="azure-channel-list">
                <label
                  v-for="ch in availableChannels"
                  :key="ch.name"
                  class="azure-channel-item"
                >
                  <input
                    type="checkbox"
                    :checked="azureChannels.includes(ch.name)"
                    @change="azureChannels.includes(ch.name)
                      ? azureChannels.splice(azureChannels.indexOf(ch.name), 1)
                      : azureChannels.push(ch.name)"
                  />
                  <span>{{ ch.name }}</span>
                </label>
              </div>
            </div>

            <!-- Status Display -->
            <div class="azure-status-box" v-if="azureIot.hasConnectionString.value">
              <div class="status-row">
                <span class="status-label">Connection:</span>
                <span class="status-value" :class="{ connected: azureIot.isConnected.value }">
                  {{ azureIot.isConnected.value ? 'Connected' : 'Disconnected' }}
                </span>
              </div>
              <div class="status-row">
                <span class="status-label">Messages Sent:</span>
                <span class="status-value">{{ azureIot.stats.value.messages_sent.toLocaleString() }}</span>
              </div>
              <div class="status-row">
                <span class="status-label">Samples Sent:</span>
                <span class="status-value">{{ azureIot.stats.value.samples_sent.toLocaleString() }}</span>
              </div>
              <div class="status-row" v-if="azureIot.stats.value.samples_dropped > 0">
                <span class="status-label">Samples Dropped:</span>
                <span class="status-value error">{{ azureIot.stats.value.samples_dropped.toLocaleString() }}</span>
              </div>
              <div class="status-row" v-if="azureIot.stats.value.last_error">
                <span class="status-label">Last Error:</span>
                <span class="status-value error">{{ azureIot.stats.value.last_error }}</span>
              </div>
            </div>
          </div>

          <div class="modal-footer">
            <button class="btn btn-secondary" @click="showAzureConfig = false">Cancel</button>
            <button class="btn btn-primary" @click="saveAzureConfig" :disabled="azureIot.isLoading.value">
              {{ azureIot.isLoading.value ? 'Saving...' : 'Save Configuration' }}
            </button>
          </div>
        </div>
      </div>
    </Transition>

    <!-- PostgreSQL Configuration Modal -->
    <Transition name="modal">
      <div v-if="showPostgresConfig" class="modal-overlay" @click.self="showPostgresConfig = false">
        <div class="modal-dialog postgres-modal">
          <div class="modal-header">
            <h2>
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <ellipse cx="12" cy="5" rx="9" ry="3"/>
                <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/>
                <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/>
              </svg>
              PostgreSQL Configuration
            </h2>
            <button class="close-btn" @click="showPostgresConfig = false">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
              </svg>
            </button>
          </div>

          <div class="modal-body">
            <!-- Connection Settings -->
            <div class="form-group">
              <label>Host</label>
              <input
                type="text"
                :value="recordingConfig.dbHost"
                @input="store.setRecordingConfig({ dbHost: ($event.target as HTMLInputElement).value })"
                placeholder="localhost or IP address"
                :disabled="configLocked"
              />
            </div>

            <div class="form-row">
              <div class="form-group">
                <label>Port</label>
                <input
                  type="number"
                  :value="recordingConfig.dbPort"
                  @input="store.setRecordingConfig({ dbPort: parseInt(($event.target as HTMLInputElement).value) || 5432 })"
                  min="1" max="65535"
                  :disabled="configLocked"
                />
              </div>
              <div class="form-group">
                <label>Database Name</label>
                <input
                  type="text"
                  :value="recordingConfig.dbName"
                  @input="store.setRecordingConfig({ dbName: ($event.target as HTMLInputElement).value })"
                  placeholder="iccsflux"
                  :disabled="configLocked"
                />
              </div>
            </div>

            <div class="form-row">
              <div class="form-group">
                <label>Username</label>
                <input
                  type="text"
                  :value="recordingConfig.dbUser"
                  @input="store.setRecordingConfig({ dbUser: ($event.target as HTMLInputElement).value })"
                  placeholder="iccsflux"
                  :disabled="configLocked"
                />
              </div>
              <div class="form-group">
                <label>Password</label>
                <input
                  type="password"
                  :value="recordingConfig.dbPassword"
                  @input="store.setRecordingConfig({ dbPassword: ($event.target as HTMLInputElement).value })"
                  placeholder="Enter password"
                  :disabled="configLocked"
                />
              </div>
            </div>

            <div class="form-row">
              <div class="form-group">
                <label>Table Name</label>
                <input
                  type="text"
                  :value="recordingConfig.dbTable"
                  @input="store.setRecordingConfig({ dbTable: ($event.target as HTMLInputElement).value })"
                  placeholder="recording_data"
                  :disabled="configLocked"
                />
                <span class="form-hint">Table is auto-created if it doesn't exist</span>
              </div>
              <div class="form-group">
                <label>Batch Size</label>
                <input
                  type="number"
                  :value="recordingConfig.dbBatchSize"
                  @input="store.setRecordingConfig({ dbBatchSize: parseInt(($event.target as HTMLInputElement).value) || 50 })"
                  min="1" max="1000"
                  :disabled="configLocked"
                />
                <span class="form-hint">Rows per INSERT batch</span>
              </div>
            </div>

            <!-- TimescaleDB Option -->
            <div class="form-row">
              <div class="form-group checkbox-group">
                <label class="checkbox-label">
                  <input
                    type="checkbox"
                    :checked="recordingConfig.dbTimescale"
                    @change="store.setRecordingConfig({ dbTimescale: ($event.target as HTMLInputElement).checked })"
                    :disabled="configLocked"
                  />
                  Enable TimescaleDB hypertable
                </label>
                <span class="form-hint">Auto-creates hypertable if TimescaleDB extension is installed. Optimizes time-series queries.</span>
              </div>
            </div>

            <!-- Test Connection -->
            <div class="db-test-section">
              <button
                class="btn btn-sm btn-secondary"
                @click="testPostgresConnection"
                :disabled="dbTestStatus.testing || !recordingConfig.dbHost"
              >
                {{ dbTestStatus.testing ? 'Testing...' : 'Test Connection' }}
              </button>
              <span v-if="dbTestStatus.result" class="db-test-result" :class="{ success: dbTestStatus.success, error: !dbTestStatus.success }">
                {{ dbTestStatus.result }}
              </span>
            </div>

            <!-- Info -->
            <div class="postgres-info">
              <p>PostgreSQL records data alongside CSV files. Each recording session creates rows with JSONB-stored channel values.</p>
              <p>Schema: <code>ts (timestamptz) | session_id (text) | channel_values (jsonb)</code></p>
            </div>

            <!-- DB status when recording -->
            <div class="db-status-box" v-if="store.status?.db_enabled && isRecording">
              <div class="status-row">
                <span class="status-label">DB Connected:</span>
                <span class="status-value" :class="{ connected: store.status?.db_connected }">
                  {{ store.status?.db_connected ? 'Yes' : 'No' }}
                </span>
              </div>
              <div class="status-row">
                <span class="status-label">Rows Written:</span>
                <span class="status-value">{{ (store.status?.db_rows_written || 0).toLocaleString() }}</span>
              </div>
            </div>
          </div>

          <div class="modal-footer">
            <button class="btn btn-secondary" @click="showPostgresConfig = false">Close</button>
            <button
              class="btn btn-primary"
              @click="togglePostgresEnabled(); showPostgresConfig = false"
              :disabled="configLocked || !recordingConfig.dbHost"
            >
              {{ recordingConfig.dbEnabled ? 'Disable PostgreSQL' : 'Enable PostgreSQL' }}
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.data-tab {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #0a0a14;
}

/* View-only notice banner */
.view-only-notice {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  background: linear-gradient(90deg, #7f1d1d 0%, #451a03 100%);
  color: #fca5a5;
  font-size: 0.85rem;
  border-bottom: 1px solid #991b1b;
}

.view-only-notice .lock-icon {
  font-size: 0.9rem;
}

.view-only-notice .login-link {
  margin-left: auto;
  padding: 4px 12px;
  background: rgba(255, 255, 255, 0.1);
  border: 1px solid #f59e0b;
  border-radius: 4px;
  color: #f59e0b;
  font-size: 0.8rem;
  cursor: pointer;
  transition: all 0.2s;
}

.view-only-notice .login-link:hover {
  background: #f59e0b;
  color: #000;
}

/* Locked State Styles */
.locked-overlay {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 16px 24px;
  background: rgba(15, 15, 26, 0.95);
  border: 1px solid #ef4444;
  border-radius: 8px;
  z-index: 10;
  font-size: 0.8rem;
  color: #fca5a5;
}

.locked-overlay .lock-icon {
  font-size: 1.2rem;
}

.locked-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  margin-bottom: 16px;
  background: rgba(239, 68, 68, 0.1);
  border: 1px solid #ef4444;
  border-radius: 6px;
  font-size: 0.8rem;
  color: #fca5a5;
}

.locked-banner .lock-icon {
  font-size: 1rem;
}

.channel-panel.locked,
.settings-panel.locked {
  position: relative;
}

.channel-panel.locked::after,
.settings-panel.locked::after {
  content: '';
  position: absolute;
  inset: 0;
  background: rgba(10, 10, 20, 0.5);
  pointer-events: none;
  z-index: 5;
}

.channel-item.disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.radio-card.disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* Status Bar */
.status-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 20px;
  background: #0f0f1a;
  border-bottom: 1px solid #2a2a4a;
}

.status-bar.recording {
  background: linear-gradient(90deg, rgba(239, 68, 68, 0.1), #0f0f1a);
  border-bottom-color: #ef4444;
}

.status-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.status-indicator {
  position: relative;
  width: 12px;
  height: 12px;
}

.status-indicator .dot {
  position: absolute;
  width: 12px;
  height: 12px;
  background: #666;
  border-radius: 50%;
}

.status-indicator.active .dot {
  background: #ef4444;
}

.status-indicator .pulse {
  position: absolute;
  width: 12px;
  height: 12px;
  background: #ef4444;
  border-radius: 50%;
  animation: pulse 1.5s ease-out infinite;
}

@keyframes pulse {
  0% { transform: scale(1); opacity: 0.8; }
  100% { transform: scale(2.5); opacity: 0; }
}

.status-text {
  font-size: 0.85rem;
  font-weight: 600;
  color: #888;
  letter-spacing: 0.5px;
}

.status-bar.recording .status-text {
  color: #ef4444;
}

.status-divider {
  color: #333;
}

.status-info {
  font-size: 0.8rem;
  color: #888;
  font-family: 'JetBrains Mono', monospace;
}

.record-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  border: none;
  border-radius: 4px;
  font-size: 0.85rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}

.record-btn.start {
  background: #ef4444;
  color: #fff;
}

.record-btn.start:hover:not(:disabled) {
  background: #dc2626;
}

.record-btn.start:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.record-btn.stop {
  background: #374151;
  color: #fff;
}

.record-btn.stop:hover {
  background: #4b5563;
}

.record-icon {
  width: 10px;
  height: 10px;
  background: #fff;
  border-radius: 50%;
}

.stop-icon {
  width: 10px;
  height: 10px;
  background: #fff;
  border-radius: 2px;
}

/* Feedback Message */
.feedback-message {
  padding: 8px 16px;
  font-size: 0.8rem;
  font-weight: 500;
  text-align: center;
}

.feedback-message.success {
  background: #14532d;
  color: #22c55e;
}

.feedback-message.error {
  background: #7f1d1d;
  color: #fca5a5;
}

.feedback-message.info {
  background: #1e3a5f;
  color: #60a5fa;
}

.fade-enter-active, .fade-leave-active {
  transition: opacity 0.3s;
}

.fade-enter-from, .fade-leave-to {
  opacity: 0;
}

/* Config Layout */
.config-layout {
  display: flex;
  flex: 1;
  overflow: hidden;
}

/* Channel Panel */
.channel-panel {
  width: 280px;
  background: #0f0f1a;
  border-right: 1px solid #2a2a4a;
  display: flex;
  flex-direction: column;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px;
  border-bottom: 1px solid #2a2a4a;
}

.panel-header h3 {
  margin: 0;
  font-size: 0.9rem;
  color: #fff;
}

.select-all {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.75rem;
  color: #888;
  cursor: pointer;
}

.select-all input {
  accent-color: #3b82f6;
}

.channel-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}

.channel-group {
  margin-bottom: 12px;
}

.group-header {
  font-size: 0.7rem;
  font-weight: 600;
  color: #666;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  padding: 8px;
}

.channel-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  background: #1a1a2e;
  border: 1px solid transparent;
  border-radius: 4px;
  margin-bottom: 4px;
  cursor: pointer;
  transition: all 0.2s;
}

.channel-item:hover {
  background: #2a2a4a;
}

.channel-item.selected {
  border-color: #3b82f6;
  background: rgba(59, 130, 246, 0.1);
}

.channel-item input[type="checkbox"] {
  accent-color: #3b82f6;
}

.channel-item.python-channel {
  border-color: #7c3aed;
}

.channel-item.python-channel.selected {
  border-color: #7c3aed;
  background: rgba(124, 58, 237, 0.1);
}

.channel-group-separator {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 8px 6px;
  margin-top: 8px;
  color: #7c3aed;
  font-size: 0.7rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.channel-group-separator::before,
.channel-group-separator::after {
  content: '';
  flex: 1;
  height: 1px;
  background: linear-gradient(90deg, transparent, #7c3aed40, transparent);
}

.channel-info {
  flex: 1;
  min-width: 0;
}

.channel-name {
  display: block;
  font-size: 0.8rem;
  color: #fff;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.channel-meta {
  font-size: 0.65rem;
  color: #666;
}

.no-channels {
  text-align: center;
  padding: 40px 20px;
  color: #555;
}

.no-channels p {
  margin: 0 0 4px;
}

.no-channels .hint {
  font-size: 0.75rem;
  color: #444;
}

.channel-summary {
  padding: 12px 16px;
  border-top: 1px solid #2a2a4a;
  font-size: 0.75rem;
  color: #888;
  text-align: center;
}

/* Settings Panel */
.settings-panel {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
}

.settings-section {
  background: #0f0f1a;
  border: 1px solid #2a2a4a;
  border-radius: 6px;
  padding: 16px;
  margin-bottom: 16px;
}

.settings-section h3 {
  margin: 0 0 16px;
  font-size: 0.9rem;
  color: #fff;
}

.form-group {
  margin-bottom: 12px;
}

.form-group label {
  display: block;
  font-size: 0.75rem;
  color: #888;
  margin-bottom: 4px;
}

.form-group input,
.form-group select {
  width: 100%;
  padding: 8px 10px;
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 4px;
  color: #fff;
  font-size: 0.85rem;
}

.form-group input:focus,
.form-group select:focus {
  outline: none;
  border-color: #3b82f6;
}

.path-input {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.8rem !important;
}

.form-row {
  display: flex;
  gap: 12px;
}

.form-row .form-group {
  flex: 1;
}

.form-row.checkboxes {
  gap: 20px;
}

.checkbox-label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.8rem;
  color: #ccc;
  cursor: pointer;
}

.checkbox-label input {
  accent-color: #3b82f6;
}

.preview-filename {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 12px;
  padding: 10px;
  background: #1a1a2e;
  border-radius: 4px;
}

.preview-filename label {
  font-size: 0.75rem;
  color: #666;
}

.preview-filename code {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.8rem;
  color: #22c55e;
}

.rate-info {
  font-size: 0.75rem;
  color: #888;
  padding: 10px;
  background: #1a1a2e;
  border-radius: 4px;
  margin-top: 8px;
}

/* Mode Selector */
.mode-selector {
  display: flex;
  gap: 8px;
  margin-bottom: 16px;
}

.mode-btn {
  flex: 1;
  padding: 10px;
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 4px;
  color: #888;
  font-size: 0.8rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}

.mode-btn:hover {
  background: #2a2a4a;
  color: #fff;
}

.mode-btn.active {
  background: #1e3a5f;
  border-color: #3b82f6;
  color: #60a5fa;
}

.mode-options {
  padding: 16px;
  background: #1a1a2e;
  border-radius: 4px;
}

/* Rate Info Enhanced */
.rate-info .rate-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.rate-info .rate-row:last-child {
  margin-bottom: 0;
}

.rate-info .rate-detail {
  font-size: 0.7rem;
  color: #666;
}

/* Rotation Selector */
.rotation-selector {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 16px;
}

.rotation-btn {
  flex: 1;
  min-width: 90px;
  padding: 8px 12px;
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 4px;
  color: #888;
  font-size: 0.75rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}

.rotation-btn:hover {
  background: #2a2a4a;
  color: #fff;
}

.rotation-btn.active {
  background: #1e3a5f;
  border-color: #3b82f6;
  color: #60a5fa;
}

.rotation-options {
  padding: 12px;
  background: #1a1a2e;
  border-radius: 4px;
  margin-bottom: 12px;
}

.quick-presets {
  display: flex;
  gap: 6px;
  margin-top: 8px;
}

.quick-presets button {
  padding: 4px 10px;
  background: #2a2a4a;
  border: 1px solid #3a3a5a;
  border-radius: 3px;
  color: #888;
  font-size: 0.7rem;
  cursor: pointer;
  transition: all 0.2s;
}

.quick-presets button:hover {
  background: #3a3a5a;
  color: #fff;
}

.limit-action {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid #2a2a4a;
}

.section-label {
  display: block;
  font-size: 0.75rem;
  color: #888;
  margin-bottom: 8px;
}

.limit-selector {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.radio-label {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.8rem;
  color: #ccc;
  cursor: pointer;
}

.radio-label input[type="radio"] {
  accent-color: #3b82f6;
}

/* Naming Selector */
.naming-selector {
  display: flex;
  gap: 8px;
  margin-bottom: 16px;
}

.naming-btn {
  flex: 1;
  padding: 10px;
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 4px;
  color: #888;
  font-size: 0.8rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}

.naming-btn:hover {
  background: #2a2a4a;
  color: #fff;
}

.naming-btn.active {
  background: #1e3a5f;
  border-color: #3b82f6;
  color: #60a5fa;
}

.naming-options {
  padding: 12px;
  background: #1a1a2e;
  border-radius: 4px;
  margin-bottom: 12px;
}

/* Directory Selector */
.directory-selector {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}

.dir-btn {
  flex: 1;
  padding: 8px 12px;
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 4px;
  color: #888;
  font-size: 0.75rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}

.dir-btn:hover {
  background: #2a2a4a;
  color: #fff;
}

.dir-btn.active {
  background: #1e3a5f;
  border-color: #3b82f6;
  color: #60a5fa;
}

.preview-path {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-top: 12px;
  padding: 10px;
  background: #1a1a2e;
  border-radius: 4px;
}

.preview-path label {
  font-size: 0.7rem;
  color: #666;
}

.preview-path code {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.75rem;
  color: #22c55e;
  word-break: break-all;
}

/* Write Strategy Selector */
.write-selector {
  display: flex;
  gap: 12px;
  margin-bottom: 12px;
}

.radio-card {
  flex: 1;
  padding: 12px;
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s;
}

.radio-card:hover {
  background: #2a2a4a;
}

.radio-card.active {
  border-color: #3b82f6;
  background: rgba(59, 130, 246, 0.1);
}

.radio-card input[type="radio"] {
  display: none;
}

.radio-content {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.radio-content strong {
  font-size: 0.85rem;
  color: #fff;
}

.radio-content span {
  font-size: 0.7rem;
  color: #888;
}

.buffer-options {
  padding: 12px;
  background: #1a1a2e;
  border-radius: 4px;
}

.buffer-info {
  margin-top: 8px;
  font-size: 0.7rem;
  color: #666;
  font-style: italic;
}

/* Rotation Badge */
.rotation-badge {
  padding: 2px 6px;
  border-radius: 3px;
  font-size: 0.65rem;
  text-transform: uppercase;
}

.rotation-badge.single {
  background: #374151;
}

.rotation-badge.time {
  background: #0891b2;
}

.rotation-badge.size {
  background: #7c3aed;
}

.rotation-badge.samples {
  background: #059669;
}

.rotation-badge.session {
  background: #d97706;
}

/* Day Selector */
.day-selector {
  display: flex;
  gap: 6px;
}

.day-btn {
  width: 32px;
  height: 32px;
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 4px;
  color: #666;
  font-size: 0.75rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}

.day-btn:hover {
  background: #2a2a4a;
  color: #fff;
}

.day-btn.active {
  background: #3b82f6;
  border-color: #3b82f6;
  color: #fff;
}

/* Settings Actions */
.settings-actions {
  display: flex;
  gap: 12px;
  justify-content: flex-end;
  align-items: center;
}

.auto-save-indicator {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  font-size: 0.75rem;
  color: #22c55e;
  background: rgba(34, 197, 94, 0.1);
  border-radius: 4px;
}

.auto-save-indicator svg {
  stroke: #22c55e;
}

.btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 10px 16px;
  border: none;
  border-radius: 4px;
  font-size: 0.85rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-secondary {
  background: #374151;
  color: #fff;
}

.btn-secondary:hover {
  background: #4b5563;
}

.btn-primary {
  background: #3b82f6;
  color: #fff;
}

.btn-primary:hover {
  background: #2563eb;
}

/* Info Panel */
.info-panel {
  width: 240px;
  background: #0f0f1a;
  border-left: 1px solid #2a2a4a;
  padding: 16px;
  overflow-y: auto;
}

.info-section {
  margin-bottom: 24px;
}

.info-section h3 {
  margin: 0 0 12px;
  font-size: 0.8rem;
  color: #666;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.info-item {
  display: flex;
  justify-content: space-between;
  padding: 6px 0;
  border-bottom: 1px solid #1a1a2e;
}

.info-label {
  font-size: 0.75rem;
  color: #666;
}

.info-value {
  font-size: 0.75rem;
  color: #fff;
  font-weight: 500;
}

.info-value.active {
  color: #22c55e;
}

.mode-badge {
  padding: 2px 6px;
  border-radius: 3px;
  font-size: 0.65rem;
  text-transform: uppercase;
}

.mode-badge.manual {
  background: #374151;
}

.mode-badge.triggered {
  background: #7c3aed;
}

.mode-badge.scheduled {
  background: #0891b2;
}

.connection-status {
  padding: 8px 12px;
  border-radius: 4px;
  font-size: 0.75rem;
  font-weight: 500;
  text-align: center;
  background: #451a03;
  color: #fbbf24;
}

.connection-status.connected {
  background: #14532d;
  color: #22c55e;
}

/* Modal */
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.7);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.file-browser-modal {
  width: 700px;
  max-height: 80vh;
  background: #0f0f1a;
  border: 1px solid #2a2a4a;
  border-radius: 8px;
  display: flex;
  flex-direction: column;
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  border-bottom: 1px solid #2a2a4a;
}

.modal-header h3 {
  margin: 0;
  font-size: 1rem;
  color: #fff;
}

.close-btn {
  background: none;
  border: none;
  color: #666;
  cursor: pointer;
  padding: 4px;
}

.close-btn:hover {
  color: #fff;
}

.modal-content {
  flex: 1;
  overflow-y: auto;
  padding: 16px 20px;
}

.file-path {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px;
  background: #1a1a2e;
  border-radius: 4px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.8rem;
  color: #888;
  margin-bottom: 16px;
}

.file-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.file-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px;
  background: #1a1a2e;
  border: 1px solid transparent;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.2s;
}

.file-item:hover {
  background: #2a2a4a;
}

.file-item.selected {
  border-color: #3b82f6;
  background: rgba(59, 130, 246, 0.1);
}

.file-icon {
  color: #60a5fa;
}

.file-info {
  flex: 1;
  min-width: 0;
}

.file-name {
  display: block;
  font-size: 0.85rem;
  color: #fff;
  font-weight: 500;
}

.file-meta {
  font-size: 0.7rem;
  color: #666;
}

.file-actions {
  display: flex;
  gap: 4px;
}

.icon-btn {
  padding: 6px;
  background: transparent;
  border: 1px solid #2a2a4a;
  border-radius: 4px;
  color: #888;
  cursor: pointer;
  transition: all 0.2s;
}

.icon-btn:hover {
  background: #2a2a4a;
  color: #fff;
}

.icon-btn.danger:hover {
  background: #7f1d1d;
  border-color: #ef4444;
  color: #fca5a5;
}

.no-files {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 40px;
  color: #555;
}

.no-files p {
  margin: 8px 0 0;
}

.no-files .hint {
  font-size: 0.75rem;
  color: #444;
}

.modal-footer {
  display: flex;
  justify-content: flex-end;
  padding: 16px 20px;
  border-top: 1px solid #2a2a4a;
}

/* Modal transitions */
.modal-enter-active, .modal-leave-active {
  transition: opacity 0.3s;
}

.modal-enter-from, .modal-leave-to {
  opacity: 0;
}

/* ALCOA+ Data Integrity Section */
.alcoa-section h3 {
  display: flex;
  align-items: center;
  gap: 12px;
}

.compliance-badge {
  font-size: 0.6rem;
  font-weight: 500;
  padding: 3px 8px;
  background: rgba(34, 197, 94, 0.15);
  color: #22c55e;
  border: 1px solid rgba(34, 197, 94, 0.3);
  border-radius: 4px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.section-description {
  font-size: 0.75rem;
  color: #666;
  margin: 0 0 16px;
  line-height: 1.4;
}

.alcoa-options {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.toggle-card {
  display: flex;
  flex-direction: column;
  padding: 12px 14px;
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s;
}

.toggle-card:hover {
  background: #2a2a4a;
}

.toggle-card.active {
  border-color: #22c55e;
  background: rgba(34, 197, 94, 0.08);
}

.toggle-card.disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.toggle-header {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}

.toggle-header input[type="checkbox"] {
  margin-top: 2px;
  accent-color: #22c55e;
  width: 16px;
  height: 16px;
}

.toggle-content {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.toggle-content strong {
  font-size: 0.85rem;
  color: #fff;
}

.toggle-content span {
  font-size: 0.7rem;
  color: #888;
}

.toggle-details {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid #2a2a4a;
  font-size: 0.7rem;
  color: #22c55e;
}

.toggle-details svg {
  stroke: #22c55e;
  flex-shrink: 0;
}

.alcoa-summary {
  margin-top: 16px;
  padding: 12px;
  background: rgba(34, 197, 94, 0.1);
  border: 1px solid rgba(34, 197, 94, 0.2);
  border-radius: 6px;
}

.summary-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.75rem;
  font-weight: 600;
  color: #22c55e;
  margin-bottom: 8px;
}

.summary-header svg {
  stroke: #22c55e;
}

.summary-items {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.summary-item {
  font-size: 0.7rem;
  padding: 3px 8px;
  background: rgba(34, 197, 94, 0.15);
  border-radius: 3px;
  color: #86efac;
}

/* ALCOA Status in Info Panel */
.alcoa-status {
  padding: 10px 12px;
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 6px;
}

.alcoa-status.enabled {
  border-color: rgba(34, 197, 94, 0.4);
  background: rgba(34, 197, 94, 0.05);
}

.alcoa-status-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.alcoa-label {
  font-size: 0.75rem;
  font-weight: 600;
  color: #888;
}

.alcoa-badge {
  font-size: 0.6rem;
  font-weight: 600;
  padding: 2px 6px;
  border-radius: 3px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  background: #14532d;
  color: #22c55e;
}

.alcoa-badge.off {
  background: #374151;
  color: #666;
}

.alcoa-features {
  display: flex;
  gap: 6px;
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid #2a2a4a;
}

.feature-dot {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  background: rgba(34, 197, 94, 0.2);
  color: #22c55e;
  border-radius: 4px;
  font-size: 0.65rem;
  font-weight: 700;
}

/* Cloud Streaming Section */
.cloud-section h3 {
  display: flex;
  align-items: center;
  gap: 8px;
}

.cloud-section h3 svg {
  color: #3b82f6;
}

.cloud-destinations {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.destination-item {
  padding: 12px;
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 6px;
}

.destination-item.unavailable {
  opacity: 0.5;
}

.destination-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
}

.destination-toggle {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
}

.destination-toggle input {
  width: 16px;
  height: 16px;
  cursor: pointer;
}

.destination-toggle input:disabled {
  cursor: not-allowed;
}

.toggle-label {
  font-weight: 600;
  color: #e5e7eb;
  font-size: 0.9rem;
}

.destination-status {
  font-size: 0.7rem;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 10px;
  text-transform: uppercase;
}

.destination-status.active {
  background: rgba(34, 197, 94, 0.2);
  color: #22c55e;
}

.destination-status.warning {
  background: rgba(245, 158, 11, 0.2);
  color: #f59e0b;
}

.destination-status.inactive {
  background: rgba(107, 114, 128, 0.2);
  color: #9ca3af;
}

.destination-desc {
  font-size: 0.75rem;
  color: #9ca3af;
  margin-bottom: 8px;
}

.sdk-warning {
  color: #f59e0b;
  font-style: italic;
}

.destination-item .btn-sm {
  padding: 4px 10px;
  font-size: 0.75rem;
}

/* Azure Config Modal */
.azure-config-modal {
  background: #12121e;
  border: 1px solid #2a2a4a;
  border-radius: 8px;
  width: 90%;
  max-width: 600px;
  max-height: 85vh;
  display: flex;
  flex-direction: column;
}

.azure-config-modal .modal-header h3 {
  display: flex;
  align-items: center;
  gap: 8px;
}

.azure-config-modal .modal-header h3 svg {
  color: #3b82f6;
}

.azure-config-content {
  padding: 20px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.connection-string-input {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.8rem;
}

.field-hint {
  font-size: 0.7rem;
  color: #6b7280;
  margin-top: 4px;
}

.channel-count {
  font-size: 0.75rem;
  color: #6b7280;
  font-weight: 400;
}

.channel-actions {
  display: flex;
  gap: 8px;
  margin: 8px 0;
}

.btn-xs {
  padding: 2px 8px;
  font-size: 0.7rem;
}

.azure-channel-list {
  max-height: 200px;
  overflow-y: auto;
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 4px;
  padding: 8px;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 4px;
}

.azure-channel-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 6px;
  cursor: pointer;
  border-radius: 3px;
  font-size: 0.75rem;
  color: #9ca3af;
}

.azure-channel-item:hover {
  background: rgba(255, 255, 255, 0.05);
}

.azure-channel-item input {
  cursor: pointer;
}

.azure-status-box {
  padding: 12px;
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 6px;
}

.azure-status-box .status-row {
  display: flex;
  justify-content: space-between;
  padding: 4px 0;
  border-bottom: 1px solid #2a2a4a;
}

.azure-status-box .status-row:last-child {
  border-bottom: none;
}

.azure-status-box .status-label {
  font-size: 0.75rem;
  color: #9ca3af;
}

.azure-status-box .status-value {
  font-size: 0.75rem;
  font-weight: 600;
  color: #e5e7eb;
}

.azure-status-box .status-value.connected {
  color: #22c55e;
}

.azure-status-box .status-value.error {
  color: #ef4444;
}

/* Info panel error value */
.info-value.error {
  color: #ef4444;
  font-size: 0.7rem;
  word-break: break-word;
}

/* PostgreSQL Config Modal */
.postgres-modal {
  background: #12121e;
  border: 1px solid #2a2a4a;
  border-radius: 8px;
  width: 90%;
  max-width: 560px;
  max-height: 85vh;
  display: flex;
  flex-direction: column;
}

.postgres-modal .modal-body {
  padding: 20px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.postgres-modal .form-group {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.postgres-modal .form-group label {
  font-size: 0.75rem;
  font-weight: 600;
  color: #9ca3af;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.postgres-modal .form-group input {
  padding: 8px 10px;
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 4px;
  color: #e5e7eb;
  font-size: 0.85rem;
  font-family: 'JetBrains Mono', monospace;
}

.postgres-modal .form-group input:focus {
  outline: none;
  border-color: #6366f1;
}

.postgres-modal .form-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.form-hint {
  font-size: 0.65rem;
  color: #6b7280;
}

.db-test-section {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px;
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 6px;
}

.db-test-result {
  font-size: 0.8rem;
  font-family: 'JetBrains Mono', monospace;
}

.db-test-result.success {
  color: #22c55e;
}

.db-test-result.error {
  color: #ef4444;
}

.postgres-info {
  padding: 10px;
  background: rgba(99, 102, 241, 0.08);
  border: 1px solid rgba(99, 102, 241, 0.2);
  border-radius: 6px;
  font-size: 0.75rem;
  color: #9ca3af;
}

.postgres-info p {
  margin: 4px 0;
}

.postgres-info code {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.7rem;
  color: #a5b4fc;
  background: rgba(99, 102, 241, 0.15);
  padding: 1px 4px;
  border-radius: 3px;
}

.db-status-box {
  padding: 12px;
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 6px;
}

.db-status-box .status-row {
  display: flex;
  justify-content: space-between;
  padding: 4px 0;
  border-bottom: 1px solid #2a2a4a;
}

.db-status-box .status-row:last-child {
  border-bottom: none;
}

.db-status-box .status-label {
  font-size: 0.75rem;
  color: #9ca3af;
}

.db-status-box .status-value {
  font-size: 0.75rem;
  font-weight: 600;
  color: #e5e7eb;
}

.db-status-box .status-value.connected {
  color: #22c55e;
}
</style>
