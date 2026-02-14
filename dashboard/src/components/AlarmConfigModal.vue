<script setup lang="ts">
/**
 * Alarm Configuration Modal
 *
 * Full ISA-18.2 compliant alarm configuration editor with 4 tabs:
 * - General: Enable, severity, group, priority, latch behavior
 * - Thresholds: HiHi, Hi, Lo, LoLo with deadband
 * - Timing: On-delay, off-delay, rate-of-change, digital input alarms
 * - Actions: Logging, sound, recording, script, safety action
 */
import { ref, computed, watch } from 'vue'
import { useDashboardStore } from '../stores/dashboard'
import { useSafety } from '../composables/useSafety'
import { useBackendScripts } from '../composables/useBackendScripts'
import type {
  AlarmConfig,
  AlarmSeverityLevel,
  AlarmBehavior
} from '../types'

const props = defineProps<{
  visible: boolean
  channel: string | null
  isNew?: boolean
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'save', config: AlarmConfig): void
}>()

const store = useDashboardStore()
const safety = useSafety()
const backendScripts = useBackendScripts()

// Active tab
const activeTab = ref<'general' | 'thresholds' | 'timing' | 'actions'>('general')

// Local form state
const formData = ref<AlarmConfig>({
  id: '',
  channel: '',
  name: '',
  description: '',
  enabled: false,
  severity: 'medium',
  high_high: undefined,
  high: undefined,
  low: undefined,
  low_low: undefined,
  high_alarm: undefined,
  low_alarm: undefined,
  high_warning: undefined,
  low_warning: undefined,
  deadband: 0,
  on_delay_s: 0,
  off_delay_s: 0,
  delay_seconds: 0,
  rate_limit: undefined,
  rate_window_s: undefined,
  behavior: 'auto_clear',
  timed_latch_s: 60,
  log_to_file: true,
  play_sound: true,
  start_recording: false,
  run_script: undefined,
  group: '',
  priority: 0,
  max_shelve_time_s: 3600,
  shelve_allowed: true,
  safety_action: undefined,
  // Digital alarm fields
  digital_alarm_enabled: false,
  digital_expected_state: true,
  digital_invert: false,
  digital_debounce_ms: 100
})

// Rate-of-change enabled toggle
const rateOfChangeEnabled = ref(false)

// Channel config for display
const channelConfig = computed(() => {
  if (!props.channel) return null
  return store.channels[props.channel]
})

// Is this a digital input channel?
const isDigitalInput = computed(() => {
  return channelConfig.value?.channel_type === 'digital_input'
})

// Available safety actions
const safetyActionList = computed(() => {
  return Object.values(safety.safetyActions.value)
})

// Available scripts (from backend)
const availableScripts = computed(() => {
  return backendScripts.scriptsList.value.map(s => s.id)
})

// Watch for channel changes and load config
watch(() => [props.visible, props.channel], ([visible, channel]) => {
  if (visible && channel) {
    loadConfig(channel as string)
  }
}, { immediate: true })

function loadConfig(channel: string) {
  const existing = safety.getAlarmConfig(channel)
  const chConfig = store.channels[channel]

  if (existing) {
    // Deep clone existing config
    formData.value = JSON.parse(JSON.stringify(existing))
  } else {
    // Create default config - thresholds come from channel config
    formData.value = {
      id: `alarm-${channel}`,
      channel,
      name: channel,
      description: '',
      enabled: false,
      severity: 'medium',
      // Thresholds are sourced from channel config (ISA-18.2 fields)
      high_high: chConfig?.hihi_limit,
      high: chConfig?.hi_limit,
      low: chConfig?.lo_limit,
      low_low: chConfig?.lolo_limit,
      high_alarm: chConfig?.hihi_limit,
      low_alarm: chConfig?.lolo_limit,
      high_warning: chConfig?.hi_limit,
      low_warning: chConfig?.lo_limit,
      deadband: 0,
      on_delay_s: 0,
      off_delay_s: 0,
      delay_seconds: 0,
      behavior: 'auto_clear',
      timed_latch_s: 60,
      log_to_file: true,
      play_sound: true,
      start_recording: false,
      group: chConfig?.group || '',
      priority: 0,
      max_shelve_time_s: 3600,
      shelve_allowed: true,
      digital_alarm_enabled: false,
      digital_expected_state: true,
      digital_invert: false,
      digital_debounce_ms: 100
    }
  }

  // Set rate of change toggle
  rateOfChangeEnabled.value = !!(formData.value.rate_limit && formData.value.rate_limit > 0)

  // Reset to first tab
  activeTab.value = 'general'
}

// Sync on_delay_s with legacy delay_seconds field
watch(() => formData.value.on_delay_s, (val) => {
  formData.value.delay_seconds = val
})

function handleSave() {
  // Clear rate fields if disabled
  if (!rateOfChangeEnabled.value) {
    formData.value.rate_limit = undefined
    formData.value.rate_window_s = undefined
  }

  // Sync thresholds from channel config (single source of truth)
  const chConfig = channelConfig.value
  const config = { ...formData.value }
  if (chConfig) {
    config.high_high = chConfig.hihi_limit
    config.high = chConfig.hi_limit
    config.low = chConfig.lo_limit
    config.low_low = chConfig.lolo_limit
    // Also sync legacy field names
    config.high_alarm = chConfig.hihi_limit
    config.low_alarm = chConfig.lolo_limit
    config.high_warning = chConfig.hi_limit
    config.low_warning = chConfig.lo_limit
  }

  emit('save', config)
  emit('close')
}

function handleClose() {
  emit('close')
}

// Severity options
const severityOptions: { value: AlarmSeverityLevel; label: string; color: string }[] = [
  { value: 'critical', label: 'Critical', color: '#dc2626' },
  { value: 'high', label: 'High', color: '#f97316' },
  { value: 'medium', label: 'Medium', color: '#eab308' },
  { value: 'low', label: 'Low', color: '#22c55e' }
]

// Behavior options
const behaviorOptions: { value: AlarmBehavior; label: string; description: string }[] = [
  { value: 'auto_clear', label: 'Auto Clear', description: 'Alarm clears automatically when value returns to normal' },
  { value: 'latch', label: 'Latch', description: 'Alarm requires manual reset even after value normalizes' },
  { value: 'timed_latch', label: 'Timed Latch', description: 'Alarm auto-clears after specified time if value is normal' }
]

// Format number for display
</script>

<template>
  <div v-if="visible" class="modal-overlay" @click.self="handleClose">
    <div class="modal-container alarm-config-modal">
      <!-- Header -->
      <div class="modal-header">
        <h3>
          <span class="header-icon">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
              <path d="M12 2L1 21h22L12 2zm0 3.5l8.5 14.5H3.5L12 5.5zM11 10v4h2v-4h-2zm0 6v2h2v-2h-2z"/>
            </svg>
          </span>
          Alarm Configuration: <span class="channel-name">{{ channel }}</span>
        </h3>
        <button class="close-btn" @click="handleClose">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M18 6L6 18M6 6l12 12"/>
          </svg>
        </button>
      </div>

      <!-- Tab Navigation -->
      <div class="tab-nav">
        <button
          class="tab-btn"
          :class="{ active: activeTab === 'general' }"
          @click="activeTab = 'general'"
        >
          General
        </button>
        <button
          class="tab-btn"
          :class="{ active: activeTab === 'thresholds' }"
          @click="activeTab = 'thresholds'"
        >
          Thresholds
        </button>
        <button
          class="tab-btn"
          :class="{ active: activeTab === 'timing' }"
          @click="activeTab = 'timing'"
        >
          Timing
          <span v-if="isDigitalInput" class="tab-badge">DI</span>
        </button>
        <button
          class="tab-btn"
          :class="{ active: activeTab === 'actions' }"
          @click="activeTab = 'actions'"
        >
          Actions
        </button>
      </div>

      <!-- Tab Content -->
      <div class="modal-body">
        <!-- GENERAL TAB -->
        <div v-if="activeTab === 'general'" class="tab-content">
          <!-- Enable/Disable -->
          <div class="form-row enable-row">
            <label class="form-label">Alarm Enabled</label>
            <label class="toggle-switch large">
              <input type="checkbox" v-model="formData.enabled" />
              <span class="slider"></span>
            </label>
            <span class="toggle-label">{{ formData.enabled ? 'Enabled' : 'Disabled' }}</span>
          </div>

          <!-- Name (read-only TAG) -->
          <div class="form-row">
            <label class="form-label">Channel TAG</label>
            <input
              type="text"
              :value="formData.channel"
              class="form-input"
              readonly
              disabled
            />
          </div>

          <!-- Description -->
          <div class="form-row">
            <label class="form-label">Description</label>
            <textarea
              v-model="formData.description"
              class="form-input textarea"
              placeholder="Optional alarm description..."
              rows="2"
            ></textarea>
          </div>

          <!-- Severity -->
          <div class="form-row">
            <label class="form-label">Severity</label>
            <div class="severity-options">
              <label
                v-for="opt in severityOptions"
                :key="opt.value"
                class="severity-option"
                :class="{ selected: formData.severity === opt.value }"
                :style="{ '--severity-color': opt.color }"
              >
                <input
                  type="radio"
                  :value="opt.value"
                  v-model="formData.severity"
                />
                <span class="severity-label">{{ opt.label }}</span>
              </label>
            </div>
          </div>

          <!-- Group -->
          <div class="form-row">
            <label class="form-label">Group</label>
            <input
              type="text"
              v-model="formData.group"
              class="form-input"
              placeholder="e.g., Zone1, Coolant, Safety"
            />
          </div>

          <!-- Priority -->
          <div class="form-row">
            <label class="form-label">Priority (0-100)</label>
            <input
              type="number"
              v-model.number="formData.priority"
              class="form-input small"
              min="0"
              max="100"
            />
            <span class="form-hint">Higher priority = earlier in first-out sequence</span>
          </div>

          <!-- Latch Behavior -->
          <div class="form-row">
            <label class="form-label">Latch Behavior</label>
            <div class="behavior-options">
              <label
                v-for="opt in behaviorOptions"
                :key="opt.value"
                class="behavior-option"
                :class="{ selected: formData.behavior === opt.value }"
              >
                <input
                  type="radio"
                  :value="opt.value"
                  v-model="formData.behavior"
                />
                <span class="behavior-content">
                  <span class="behavior-label">{{ opt.label }}</span>
                  <span class="behavior-desc">{{ opt.description }}</span>
                </span>
              </label>
            </div>
          </div>

          <!-- Timed Latch Duration (conditional) -->
          <div v-if="formData.behavior === 'timed_latch'" class="form-row indent">
            <label class="form-label">Auto-Reset After</label>
            <div class="input-with-unit">
              <input
                type="number"
                v-model.number="formData.timed_latch_s"
                class="form-input small"
                min="1"
              />
              <span class="unit">seconds</span>
            </div>
          </div>
        </div>

        <!-- THRESHOLDS TAB -->
        <div v-if="activeTab === 'thresholds'" class="tab-content">
          <!-- Digital input notice -->
          <div v-if="isDigitalInput" class="digital-alarm-notice">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
              <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-6h2v6zm0-8h-2V7h2v2z"/>
            </svg>
            <span>Digital inputs use state-based alarms only. Configure in the <strong>Timing</strong> tab under <strong>Digital Input Alarm</strong>.</span>
          </div>

          <!-- Analog threshold content (hidden for digital inputs) -->
          <template v-if="!isDigitalInput">
            <!-- Info banner -->
            <div class="info-banner">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-6h2v6zm0-8h-2V7h2v2z"/>
              </svg>
              <span>Alarm thresholds are defined in <strong>Configuration Tab → Channel Settings</strong>. This shows the current limits for reference.</span>
            </div>

            <div class="threshold-diagram">
              <div class="threshold-bar">
                <div class="zone critical-high" :style="{ height: channelConfig?.hihi_limit != null ? '20%' : '0' }">
                  <span v-if="channelConfig?.hihi_limit != null">HiHi: {{ channelConfig.hihi_limit }}</span>
                </div>
                <div class="zone warning-high" :style="{ height: channelConfig?.hi_limit != null ? '15%' : '0' }">
                  <span v-if="channelConfig?.hi_limit != null">Hi: {{ channelConfig.hi_limit }}</span>
                </div>
                <div class="zone normal">Normal</div>
                <div class="zone warning-low" :style="{ height: channelConfig?.lo_limit != null ? '15%' : '0' }">
                  <span v-if="channelConfig?.lo_limit != null">Lo: {{ channelConfig.lo_limit }}</span>
                </div>
                <div class="zone critical-low" :style="{ height: channelConfig?.lolo_limit != null ? '20%' : '0' }">
                  <span v-if="channelConfig?.lolo_limit != null">LoLo: {{ channelConfig.lolo_limit }}</span>
                </div>
              </div>
            </div>

            <div class="threshold-display">
              <!-- Channel Limits (Read-only) -->
              <div class="section-header">Channel Alarm Limits (Read-only)</div>

              <div class="limits-grid">
                <!-- HiHi (Critical High) -->
                <div class="limit-item critical">
                  <span class="threshold-badge critical">HiHi</span>
                  <span class="limit-label">Critical High</span>
                  <span class="limit-value">
                    {{ channelConfig?.hihi_limit != null ? `${channelConfig.hihi_limit} ${channelConfig?.unit || ''}` : 'Not set' }}
                  </span>
                </div>

                <!-- Hi (Warning High) -->
                <div class="limit-item warning">
                  <span class="threshold-badge warning">Hi</span>
                  <span class="limit-label">High Warning</span>
                  <span class="limit-value">
                    {{ channelConfig?.hi_limit != null ? `${channelConfig.hi_limit} ${channelConfig?.unit || ''}` : 'Not set' }}
                  </span>
                </div>

                <!-- Lo (Warning Low) -->
                <div class="limit-item warning">
                  <span class="threshold-badge warning">Lo</span>
                  <span class="limit-label">Low Warning</span>
                  <span class="limit-value">
                    {{ channelConfig?.lo_limit != null ? `${channelConfig.lo_limit} ${channelConfig?.unit || ''}` : 'Not set' }}
                  </span>
                </div>

                <!-- LoLo (Critical Low) -->
                <div class="limit-item critical">
                  <span class="threshold-badge critical">LoLo</span>
                  <span class="limit-label">Critical Low</span>
                  <span class="limit-value">
                    {{ channelConfig?.lolo_limit != null ? `${channelConfig.lolo_limit} ${channelConfig?.unit || ''}` : 'Not set' }}
                  </span>
                </div>
              </div>

              <div class="divider"></div>

              <!-- Deadband (Editable - this is alarm behavior, not threshold) -->
              <div class="section-header">Alarm Behavior</div>

              <div class="form-row">
                <label class="form-label">
                  Deadband / Hysteresis
                  <span class="info-icon" title="Prevents alarm chatter at threshold boundary">?</span>
                </label>
                <div class="input-with-unit">
                  <input
                    type="number"
                    v-model.number="formData.deadband"
                    class="form-input"
                    min="0"
                    step="0.1"
                  />
                  <span class="unit">{{ channelConfig?.unit || '' }}</span>
                </div>
                <span class="form-hint">
                  Value must drop below (threshold - deadband) before alarm clears
                </span>
              </div>
            </div>
          </template>
        </div>

        <!-- TIMING TAB -->
        <div v-if="activeTab === 'timing'" class="tab-content">
          <!-- Time Delays -->
          <div class="section-header">Time-Based Filtering</div>

          <div class="form-row">
            <label class="form-label">
              On-Delay
              <span class="info-icon" title="Value must exceed threshold for this duration before alarm triggers">?</span>
            </label>
            <div class="input-with-unit">
              <input
                type="number"
                v-model.number="formData.on_delay_s"
                class="form-input"
                min="0"
                step="0.1"
              />
              <span class="unit">seconds</span>
            </div>
            <span class="form-hint">Filters transient spikes</span>
          </div>

          <div class="form-row">
            <label class="form-label">
              Off-Delay
              <span class="info-icon" title="Value must be within limits for this duration before alarm clears">?</span>
            </label>
            <div class="input-with-unit">
              <input
                type="number"
                v-model.number="formData.off_delay_s"
                class="form-input"
                min="0"
                step="0.1"
              />
              <span class="unit">seconds</span>
            </div>
            <span class="form-hint">Prevents rapid alarm toggling</span>
          </div>

          <div class="divider"></div>

          <!-- Rate-of-Change -->
          <div class="section-header">
            <label class="toggle-inline">
              <input type="checkbox" v-model="rateOfChangeEnabled" />
              <span>Rate-of-Change Alarm</span>
            </label>
          </div>

          <div v-if="rateOfChangeEnabled" class="rate-of-change-section">
            <div class="form-row">
              <label class="form-label">Rate Limit</label>
              <div class="input-with-unit">
                <input
                  type="number"
                  v-model.number="formData.rate_limit"
                  class="form-input"
                  min="0"
                  step="0.01"
                />
                <span class="unit">{{ channelConfig?.unit || 'units' }}/sec</span>
              </div>
              <span class="form-hint">Maximum allowed rate of change</span>
            </div>

            <div class="form-row">
              <label class="form-label">Rate Window</label>
              <div class="input-with-unit">
                <input
                  type="number"
                  v-model.number="formData.rate_window_s"
                  class="form-input"
                  min="0.1"
                  step="0.1"
                />
                <span class="unit">seconds</span>
              </div>
              <span class="form-hint">Time window for rate calculation</span>
            </div>
          </div>

          <!-- Digital Input Alarm (conditional) -->
          <template v-if="isDigitalInput">
            <div class="divider"></div>

            <div class="section-header">
              <label class="toggle-inline">
                <input type="checkbox" v-model="formData.digital_alarm_enabled" />
                <span>Digital Input Alarm</span>
              </label>
            </div>

            <div v-if="formData.digital_alarm_enabled" class="digital-alarm-section">
              <div class="form-row">
                <label class="form-label">Expected State</label>
                <div class="state-options">
                  <label class="state-option" :class="{ selected: formData.digital_expected_state === true }">
                    <input type="radio" :value="true" v-model="formData.digital_expected_state" />
                    <span class="state-high">HIGH (1)</span>
                  </label>
                  <label class="state-option" :class="{ selected: formData.digital_expected_state === false }">
                    <input type="radio" :value="false" v-model="formData.digital_expected_state" />
                    <span class="state-low">LOW (0)</span>
                  </label>
                </div>
                <span class="form-hint">Alarm triggers when input != expected state</span>
              </div>

              <div class="form-row">
                <label class="form-label">
                  <label class="toggle-inline small">
                    <input type="checkbox" v-model="formData.digital_invert" />
                    <span>Invert Input</span>
                  </label>
                </label>
                <span class="form-hint">For normally-closed (NC) sensors: ON when signal is LOW</span>
              </div>

              <div class="form-row">
                <label class="form-label">Debounce Time</label>
                <div class="input-with-unit">
                  <input
                    type="number"
                    v-model.number="formData.digital_debounce_ms"
                    class="form-input"
                    min="0"
                    step="10"
                  />
                  <span class="unit">ms</span>
                </div>
                <span class="form-hint">Ignore state changes shorter than this duration</span>
              </div>
            </div>
          </template>
        </div>

        <!-- ACTIONS TAB -->
        <div v-if="activeTab === 'actions'" class="tab-content">
          <!-- Logging -->
          <div class="section-header">Logging & Recording</div>

          <div class="form-row checkbox-row">
            <label class="checkbox-label">
              <input type="checkbox" v-model="formData.log_to_file" />
              <span>Log to File</span>
            </label>
            <span class="form-hint">Record alarm events to audit log</span>
          </div>

          <div class="form-row checkbox-row">
            <label class="checkbox-label">
              <input type="checkbox" v-model="formData.play_sound" />
              <span>Play Sound</span>
            </label>
            <span class="form-hint">Audible alert when alarm triggers</span>
          </div>

          <div class="form-row checkbox-row">
            <label class="checkbox-label">
              <input type="checkbox" v-model="formData.start_recording" />
              <span>Start Recording</span>
            </label>
            <span class="form-hint">Automatically start data recording when alarm triggers</span>
          </div>

          <div class="divider"></div>

          <!-- Script -->
          <div class="section-header">Script Execution</div>

          <div class="form-row">
            <label class="form-label">Run Script</label>
            <select v-model="formData.run_script" class="form-select">
              <option :value="undefined">None</option>
              <option v-for="script in availableScripts" :key="script" :value="script">
                {{ script }}
              </option>
            </select>
            <span class="form-hint">Execute Python script when alarm triggers</span>
          </div>

          <div class="divider"></div>

          <!-- Safety Action -->
          <div class="section-header">Safety Action (ISA-18.2)</div>

          <div class="form-row">
            <label class="form-label">Linked Safety Action</label>
            <select v-model="formData.safety_action" class="form-select">
              <option :value="undefined">None</option>
              <option v-for="action in safetyActionList" :key="action.id" :value="action.id">
                {{ action.name }} ({{ action.type }})
              </option>
            </select>
            <span class="form-hint">Automatic response when alarm triggers</span>
          </div>

          <div class="divider"></div>

          <!-- Shelving -->
          <div class="section-header">Shelving Settings</div>

          <div class="form-row checkbox-row">
            <label class="checkbox-label">
              <input type="checkbox" v-model="formData.shelve_allowed" />
              <span>Allow Shelving</span>
            </label>
            <span class="form-hint">Permit operators to temporarily suppress this alarm</span>
          </div>

          <div v-if="formData.shelve_allowed" class="form-row indent">
            <label class="form-label">Max Shelve Time</label>
            <div class="input-with-unit">
              <input
                type="number"
                v-model.number="formData.max_shelve_time_s"
                class="form-input"
                min="60"
                step="60"
              />
              <span class="unit">seconds</span>
            </div>
            <span class="form-hint">Maximum duration alarm can be shelved (default: 1 hour)</span>
          </div>
        </div>
      </div>

      <!-- Footer -->
      <div class="modal-footer">
        <button class="btn btn-secondary" @click="handleClose">Cancel</button>
        <button class="btn btn-primary" @click="handleSave">
          Save Configuration
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.modal-overlay {
  position: fixed;
  inset: 0;
  background: var(--bg-overlay);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  padding: 20px;
}

.modal-container {
  background: var(--bg-widget);
  border-radius: 8px;
  border: 1px solid var(--border-light);
  width: 100%;
  max-width: 650px;
  max-height: 90vh;
  display: flex;
  flex-direction: column;
  box-shadow: 0 10px 40px rgba(0, 0, 0, 0.5);
}

.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border-light);
}

.modal-header h3 {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0;
  font-size: 1.1rem;
  color: var(--text-primary);
}

.header-icon {
  color: var(--color-warning);
}

.channel-name {
  color: var(--color-accent-light);
  font-family: 'JetBrains Mono', monospace;
}

.close-btn {
  background: none;
  border: none;
  color: var(--text-secondary);
  cursor: pointer;
  padding: 4px;
  display: flex;
  border-radius: 4px;
}

.close-btn:hover {
  color: var(--text-primary);
  background: var(--border-light);
}

/* Tab Navigation */
.tab-nav {
  display: flex;
  gap: 2px;
  padding: 0 20px;
  background: var(--bg-primary);
  border-bottom: 1px solid var(--border-light);
}

.tab-btn {
  background: none;
  border: none;
  padding: 12px 20px;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 0.9rem;
  border-bottom: 2px solid transparent;
  transition: all 0.2s;
  display: flex;
  align-items: center;
  gap: 6px;
}

.tab-btn:hover {
  color: var(--text-primary);
}

.tab-btn.active {
  color: var(--color-accent-light);
  border-bottom-color: #60a5fa;
}

.tab-badge {
  background: var(--color-accent);
  color: var(--text-primary);
  font-size: 0.65rem;
  padding: 2px 5px;
  border-radius: 3px;
  font-weight: 600;
}

/* Modal Body */
.modal-body {
  padding: 20px;
  overflow-y: auto;
  flex: 1;
}

.tab-content {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* Form Elements */
.form-row {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.form-row.indent {
  margin-left: 24px;
}

.form-row.enable-row {
  flex-direction: row;
  align-items: center;
  gap: 12px;
}

.form-row.checkbox-row {
  flex-direction: row;
  align-items: center;
  gap: 12px;
}

.form-label {
  font-size: 0.85rem;
  color: var(--text-muted);
  display: flex;
  align-items: center;
  gap: 6px;
}

.form-input {
  background: var(--bg-primary);
  border: 1px solid var(--border-light);
  border-radius: 4px;
  padding: 8px 12px;
  color: var(--text-primary);
  font-size: 0.9rem;
}

.form-input:focus {
  outline: none;
  border-color: var(--color-accent);
}

.form-input:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.form-input.small {
  width: 100px;
}

.form-input.textarea {
  resize: vertical;
  min-height: 60px;
}

.form-select {
  background: var(--bg-primary);
  border: 1px solid var(--border-light);
  border-radius: 4px;
  padding: 8px 12px;
  color: var(--text-primary);
  font-size: 0.9rem;
  cursor: pointer;
}

.form-select:focus {
  outline: none;
  border-color: var(--color-accent);
}

.form-hint {
  font-size: 0.75rem;
  color: var(--text-muted);
}

.input-with-unit {
  display: flex;
  align-items: center;
  gap: 8px;
}

.input-with-unit .form-input {
  flex: 1;
  max-width: 150px;
}

.input-with-unit .unit {
  color: var(--text-secondary);
  font-size: 0.85rem;
}

.info-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  background: var(--border-light);
  border-radius: 50%;
  font-size: 0.7rem;
  color: var(--text-secondary);
  cursor: help;
}

/* Toggle Switch */
.toggle-switch {
  position: relative;
  display: inline-block;
  width: 44px;
  height: 24px;
}

.toggle-switch.large {
  width: 52px;
  height: 28px;
}

.toggle-switch input {
  opacity: 0;
  width: 0;
  height: 0;
}

.toggle-switch .slider {
  position: absolute;
  cursor: pointer;
  inset: 0;
  background: var(--border-light);
  border-radius: 24px;
  transition: 0.2s;
}

.toggle-switch .slider::before {
  content: '';
  position: absolute;
  height: 18px;
  width: 18px;
  left: 3px;
  bottom: 3px;
  background: #fff;
  border-radius: 50%;
  transition: 0.2s;
}

.toggle-switch.large .slider::before {
  height: 22px;
  width: 22px;
}

.toggle-switch input:checked + .slider {
  background: var(--color-success);
}

.toggle-switch input:checked + .slider::before {
  transform: translateX(20px);
}

.toggle-switch.large input:checked + .slider::before {
  transform: translateX(24px);
}

.toggle-label {
  font-size: 0.9rem;
  color: var(--text-secondary);
}

.toggle-inline {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
}

.toggle-inline input {
  width: 16px;
  height: 16px;
  cursor: pointer;
}

.toggle-inline.small input {
  width: 14px;
  height: 14px;
}

/* Checkbox */
.checkbox-label {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  color: var(--text-bright);
}

.checkbox-label input {
  width: 16px;
  height: 16px;
  cursor: pointer;
}

/* Severity Options */
.severity-options {
  display: flex;
  gap: 8px;
}

.severity-option {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  background: var(--bg-primary);
  border: 1px solid var(--border-light);
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s;
}

.severity-option input {
  display: none;
}

.severity-option:hover {
  border-color: var(--border-heavy);
}

.severity-option.selected {
  border-color: var(--severity-color);
  background: color-mix(in srgb, var(--severity-color) 15%, #0d0d1a);
}

.severity-label {
  font-size: 0.85rem;
  color: var(--text-bright);
}

.severity-option.selected .severity-label {
  color: var(--severity-color);
  font-weight: 600;
}

/* Behavior Options */
.behavior-options {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.behavior-option {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 12px;
  background: var(--bg-primary);
  border: 1px solid var(--border-light);
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s;
}

.behavior-option input {
  margin-top: 2px;
}

.behavior-option:hover {
  border-color: var(--border-heavy);
}

.behavior-option.selected {
  border-color: var(--color-accent);
  background: var(--color-accent-bg);
}

.behavior-content {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.behavior-label {
  font-size: 0.9rem;
  color: var(--text-primary);
  font-weight: 500;
}

.behavior-desc {
  font-size: 0.75rem;
  color: var(--text-secondary);
}

/* Threshold Diagram */
.threshold-diagram {
  display: flex;
  justify-content: center;
  margin-bottom: 16px;
}

.threshold-bar {
  width: 150px;
  height: 200px;
  display: flex;
  flex-direction: column;
  border: 1px solid var(--border-light);
  border-radius: 8px;
  overflow: hidden;
}

.zone {
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.7rem;
  padding: 4px;
  transition: height 0.3s;
}

.zone.critical-high {
  background: rgba(220, 38, 38, 0.3);
  color: #f87171;
  border-bottom: 1px dashed #dc2626;
}

.zone.warning-high {
  background: rgba(234, 179, 8, 0.2);
  color: #fbbf24;
  border-bottom: 1px dashed #eab308;
}

.zone.normal {
  background: rgba(34, 197, 94, 0.1);
  color: var(--color-success);
  flex: 1;
}

.zone.warning-low {
  background: rgba(234, 179, 8, 0.2);
  color: #fbbf24;
  border-top: 1px dashed #eab308;
}

.zone.critical-low {
  background: rgba(220, 38, 38, 0.3);
  color: #f87171;
  border-top: 1px dashed #dc2626;
}

/* Info Banner */
.info-banner {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 12px 16px;
  background: var(--color-accent-bg);
  border: 1px solid var(--color-accent-border);
  border-radius: 6px;
  margin-bottom: 16px;
}

.info-banner svg {
  color: var(--color-accent-light);
  flex-shrink: 0;
  margin-top: 2px;
}

.info-banner span {
  font-size: 0.85rem;
  color: var(--text-muted);
  line-height: 1.4;
}

.info-banner strong {
  color: var(--color-accent-light);
}

/* Threshold Display (Read-only) */
.threshold-display {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.limits-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.limit-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 12px;
  background: var(--bg-primary);
  border: 1px solid var(--border-light);
  border-radius: 6px;
}

.limit-item.critical {
  border-left: 3px solid #dc2626;
}

.limit-item.warning {
  border-left: 3px solid #eab308;
}

.limit-label {
  font-size: 0.75rem;
  color: var(--text-secondary);
}

.limit-value {
  font-size: 1rem;
  color: var(--text-primary);
  font-family: 'JetBrains Mono', monospace;
}

.limit-item .limit-value:has(+ .limit-value) {
  color: var(--text-muted);
}

/* Threshold Inputs (legacy) */
.threshold-inputs {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.threshold-row .form-label {
  display: flex;
  align-items: center;
  gap: 8px;
}

.threshold-badge {
  padding: 2px 6px;
  border-radius: 3px;
  font-size: 0.7rem;
  font-weight: 600;
  font-family: 'JetBrains Mono', monospace;
}

.threshold-badge.critical {
  background: rgba(220, 38, 38, 0.3);
  color: #f87171;
}

.threshold-badge.warning {
  background: rgba(234, 179, 8, 0.2);
  color: #fbbf24;
}

/* Section Headers */
.section-header {
  font-size: 0.85rem;
  font-weight: 600;
  color: var(--color-accent-light);
  padding-bottom: 8px;
  border-bottom: 1px solid var(--border-color);
  margin-top: 8px;
}

.divider {
  height: 1px;
  background: var(--border-color);
  margin: 8px 0;
}

/* Digital Alarm Notice (Thresholds tab) */
.digital-alarm-notice {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 16px 20px;
  background: rgba(234, 179, 8, 0.1);
  border: 1px solid rgba(234, 179, 8, 0.3);
  border-radius: 6px;
}

.digital-alarm-notice svg {
  color: #eab308;
  flex-shrink: 0;
  margin-top: 2px;
}

.digital-alarm-notice span {
  font-size: 0.9rem;
  color: var(--text-muted);
  line-height: 1.5;
}

.digital-alarm-notice strong {
  color: #eab308;
}

/* Digital Alarm Section */
.digital-alarm-section {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding-left: 24px;
}

.state-options {
  display: flex;
  gap: 12px;
}

.state-option {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  background: var(--bg-primary);
  border: 1px solid var(--border-light);
  border-radius: 6px;
  cursor: pointer;
}

.state-option input {
  display: none;
}

.state-option.selected {
  border-color: var(--color-accent);
}

.state-high {
  color: var(--color-success);
  font-weight: 500;
}

.state-low {
  color: var(--text-secondary);
  font-weight: 500;
}

/* Rate of Change Section */
.rate-of-change-section {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding-left: 24px;
}

/* Modal Footer */
.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  padding: 16px 20px;
  border-top: 1px solid var(--border-light);
}

.btn {
  padding: 10px 20px;
  border-radius: 6px;
  font-size: 0.9rem;
  font-weight: 500;
  cursor: pointer;
  border: none;
  transition: all 0.2s;
}

.btn-secondary {
  background: var(--border-light);
  color: var(--text-bright);
}

.btn-secondary:hover {
  background: var(--border-heavy);
}

.btn-primary {
  background: var(--color-accent);
  color: var(--text-primary);
}

.btn-primary:hover {
  background: var(--color-accent-dark);
}
</style>
