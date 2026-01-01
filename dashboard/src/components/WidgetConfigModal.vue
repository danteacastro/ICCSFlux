<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useDashboardStore } from '../stores/dashboard'
import { useScripts } from '../composables/useScripts'
import type { WidgetConfig, WidgetStyle, ButtonAction, ButtonActionType, SystemCommandType } from '../types'
import { WIDGET_COLORS } from '../types'

const props = defineProps<{
  widgetId: string | null
}>()

const emit = defineEmits<{
  (e: 'close'): void
}>()

const store = useDashboardStore()
const scripts = useScripts()

// Local copy of widget for editing
const localWidget = ref<Partial<WidgetConfig>>({})

// Get the current widget
const widget = computed(() => {
  if (!props.widgetId) return null
  return store.widgets.find(w => w.id === props.widgetId) || null
})

// Initialize local copy when widget changes
watch(() => props.widgetId, () => {
  if (widget.value) {
    localWidget.value = { ...widget.value }
  }
}, { immediate: true })

// Widget type info
const widgetType = computed(() => widget.value?.type || 'numeric')

// Available channels based on widget type
const availableChannels = computed(() => {
  const wt = widgetType.value
  return Object.entries(store.channels).filter(([_, ch]) => {
    if (wt === 'toggle') return ch.channel_type === 'digital_output'
    if (wt === 'led') return true // LEDs can work with any channel
    return true
  })
})

// Digital output channels for button action
const digitalOutputChannels = computed(() => {
  return Object.entries(store.channels).filter(([_, ch]) =>
    ch.channel_type === 'digital_output'
  )
})

// Available sequences for script_run action
const availableSequences = computed(() => scripts.sequences.value)

// Button action type options
const buttonActionTypes: { value: ButtonActionType; label: string }[] = [
  { value: 'mqtt_publish', label: 'MQTT Publish' },
  { value: 'digital_output', label: 'Digital Output' },
  { value: 'script_run', label: 'Run Sequence' },
  { value: 'system_command', label: 'System Command' }
]

// System command options
const systemCommands: { value: SystemCommandType; label: string }[] = [
  { value: 'acquisition_start', label: 'Start Acquisition' },
  { value: 'acquisition_stop', label: 'Stop Acquisition' },
  { value: 'recording_start', label: 'Start Recording' },
  { value: 'recording_stop', label: 'Stop Recording' },
  { value: 'alarm_acknowledge_all', label: 'Acknowledge All Alarms' },
  { value: 'latch_reset_all', label: 'Reset All Latched' }
]

// Initialize button action if not present
function ensureButtonAction(): ButtonAction {
  if (!localWidget.value.buttonAction) {
    localWidget.value.buttonAction = { type: 'system_command' }
  }
  return localWidget.value.buttonAction
}

// Update button action property
function updateButtonAction<K extends keyof ButtonAction>(key: K, value: ButtonAction[K]) {
  const action = ensureButtonAction()
  action[key] = value
}

// Save changes
function save() {
  if (!props.widgetId || !localWidget.value) return
  store.updateWidget(props.widgetId, localWidget.value)
  emit('close')
}

// Cancel without saving
function cancel() {
  emit('close')
}

// Update style property
function updateStyle(key: keyof WidgetStyle, value: string) {
  if (!localWidget.value.style) {
    localWidget.value.style = {}
  }
  ;(localWidget.value.style as Record<string, string>)[key] = value
}
</script>

<template>
  <Teleport to="body">
    <div v-if="widgetId" class="modal-overlay" @click.self="cancel">
      <div class="modal widget-config-modal">
        <div class="modal-header">
          <h3>Configure {{ widgetType }} Widget</h3>
          <button class="close-btn" @click="cancel">×</button>
        </div>

        <div class="modal-body">
          <!-- Common: Label -->
          <div class="form-group">
            <label>Label</label>
            <input
              type="text"
              v-model="localWidget.label"
              placeholder="Widget label"
            />
          </div>

          <!-- Channel selection (for single-channel widgets) -->
          <div v-if="['numeric', 'gauge', 'led', 'toggle', 'setpoint', 'sparkline'].includes(widgetType)" class="form-group">
            <label>Channel</label>
            <select v-model="localWidget.channel">
              <option value="">-- Select Channel --</option>
              <option v-for="[name, config] in availableChannels" :key="name" :value="name">
                {{ config.display_name || name }} ({{ config.unit || 'no unit' }})
              </option>
            </select>
          </div>

          <!-- Numeric/Gauge specific -->
          <template v-if="['numeric', 'gauge'].includes(widgetType)">
            <div class="form-group">
              <label>Decimal Places</label>
              <input
                type="number"
                v-model.number="localWidget.decimals"
                min="0"
                max="6"
              />
            </div>
            <div class="form-group checkbox">
              <label>
                <input
                  type="checkbox"
                  :checked="localWidget.showUnit !== false"
                  @change="localWidget.showUnit = ($event.target as HTMLInputElement).checked"
                />
                Show Unit
              </label>
            </div>
          </template>

          <!-- Chart specific -->
          <template v-if="widgetType === 'chart'">
            <!-- Update Mode (LabVIEW-style) -->
            <div class="config-section">
              <div class="section-header">Chart Mode</div>
              <div class="form-group">
                <label>Update Mode</label>
                <select v-model="localWidget.updateMode">
                  <option value="strip">Strip Chart (scrolling)</option>
                  <option value="scope">Scope Chart (clear & restart)</option>
                  <option value="sweep">Sweep Chart (moving line)</option>
                </select>
                <span class="hint">How data is displayed as it updates</span>
              </div>
            </div>

            <!-- X-Axis Settings -->
            <div class="config-section">
              <div class="section-header">X-Axis (Time)</div>
              <div class="form-group">
                <label>Time Range (seconds)</label>
                <input
                  type="number"
                  v-model.number="localWidget.timeRange"
                  min="10"
                  max="3600"
                />
                <span class="hint">How much history to display</span>
              </div>
              <div class="form-group">
                <label>History Buffer Size</label>
                <input
                  type="number"
                  v-model.number="localWidget.historySize"
                  min="100"
                  max="10000"
                  placeholder="1024"
                />
                <span class="hint">Max data points to keep (default 1024)</span>
              </div>
            </div>

            <!-- Y-Axis Settings -->
            <div class="config-section">
              <div class="section-header">Y-Axis</div>
              <div class="form-group checkbox">
                <label>
                  <input
                    type="checkbox"
                    :checked="localWidget.yAxisAuto !== false"
                    @change="localWidget.yAxisAuto = ($event.target as HTMLInputElement).checked"
                  />
                  Auto-scale
                </label>
              </div>
              <template v-if="localWidget.yAxisAuto === false">
                <div class="form-row">
                  <div class="form-group half">
                    <label>Min</label>
                    <input type="number" v-model.number="localWidget.yAxisMin" step="any" />
                  </div>
                  <div class="form-group half">
                    <label>Max</label>
                    <input type="number" v-model.number="localWidget.yAxisMax" step="any" />
                  </div>
                </div>
              </template>
            </div>

            <!-- Display Options -->
            <div class="config-section">
              <div class="section-header">Display Options</div>
              <div class="form-group checkbox">
                <label>
                  <input
                    type="checkbox"
                    :checked="localWidget.showGrid !== false"
                    @change="localWidget.showGrid = ($event.target as HTMLInputElement).checked"
                  />
                  Show Grid Lines
                </label>
              </div>
              <div class="form-group checkbox">
                <label>
                  <input
                    type="checkbox"
                    :checked="localWidget.showLegend !== false"
                    @change="localWidget.showLegend = ($event.target as HTMLInputElement).checked"
                  />
                  Show Legend
                </label>
              </div>
              <div class="form-group checkbox">
                <label>
                  <input
                    type="checkbox"
                    v-model="localWidget.showDigitalDisplay"
                  />
                  Show Digital Display
                </label>
                <span class="hint">Display current values in header</span>
              </div>
              <div class="form-group checkbox">
                <label>
                  <input
                    type="checkbox"
                    v-model="localWidget.showScrollbar"
                  />
                  Show History Scrollbar
                </label>
                <span class="hint">Navigate through historical data</span>
              </div>
            </div>

            <!-- Channels -->
            <div class="config-section">
              <div class="section-header">Channels</div>
              <div class="form-group">
                <div class="channel-checklist">
                  <label v-for="[name, config] in availableChannels" :key="name" class="channel-item">
                    <input
                      type="checkbox"
                      :checked="localWidget.channels?.includes(name as string)"
                      @change="(e) => {
                        const checked = (e.target as HTMLInputElement).checked
                        if (!localWidget.channels) localWidget.channels = []
                        if (checked && !localWidget.channels.includes(name as string)) {
                          localWidget.channels.push(name as string)
                        } else if (!checked) {
                          localWidget.channels = localWidget.channels.filter(c => c !== name)
                        }
                      }"
                    />
                    <span>{{ config.display_name || name }}</span>
                  </label>
                </div>
              </div>
            </div>
          </template>

          <!-- Multi Channel Table specific -->
          <template v-if="widgetType === 'multi_channel_table'">
            <div class="form-group">
              <label>Channels to Display</label>
              <div class="channel-checklist">
                <label v-for="[name, config] in availableChannels" :key="name" class="channel-item">
                  <input
                    type="checkbox"
                    :checked="localWidget.channels?.includes(name as string)"
                    @change="(e) => {
                      const checked = (e.target as HTMLInputElement).checked
                      if (!localWidget.channels) localWidget.channels = []
                      if (checked && !localWidget.channels.includes(name as string)) {
                        localWidget.channels.push(name as string)
                      } else if (!checked) {
                        localWidget.channels = localWidget.channels.filter(c => c !== name)
                      }
                    }"
                  />
                  <span>{{ config.display_name || name }} ({{ config.unit || '-' }})</span>
                </label>
              </div>
              <p class="hint">If no channels selected, displays first 10 analog channels</p>
            </div>
            <div class="form-group checkbox">
              <label>
                <input
                  type="checkbox"
                  :checked="localWidget.showUnit !== false"
                  @change="localWidget.showUnit = ($event.target as HTMLInputElement).checked"
                />
                Show Units
              </label>
            </div>
            <div class="form-group checkbox">
              <label>
                <input type="checkbox" v-model="localWidget.showAlarmStatus" />
                Show Alarm Status
              </label>
            </div>
          </template>

          <!-- LED specific -->
          <template v-if="widgetType === 'led'">
            <div class="form-group">
              <label>On Color</label>
              <div class="color-options">
                <button
                  v-for="color in WIDGET_COLORS.led.on"
                  :key="color"
                  class="color-btn"
                  :class="{ selected: localWidget.style?.onColor === color }"
                  :style="{ backgroundColor: color }"
                  @click="updateStyle('onColor', color)"
                />
              </div>
            </div>
            <div class="form-group">
              <label>Off Color</label>
              <div class="color-options">
                <button
                  v-for="color in WIDGET_COLORS.led.off"
                  :key="color"
                  class="color-btn"
                  :class="{ selected: localWidget.style?.offColor === color }"
                  :style="{ backgroundColor: color }"
                  @click="updateStyle('offColor', color)"
                />
              </div>
            </div>
          </template>

          <!-- Title specific -->
          <template v-if="widgetType === 'title'">
            <div class="form-group">
              <label>Font Size</label>
              <select v-model="localWidget.style!.fontSize" @change="updateStyle('fontSize', ($event.target as HTMLSelectElement).value)">
                <option value="small">Small</option>
                <option value="medium">Medium</option>
                <option value="large">Large</option>
                <option value="xlarge">Extra Large</option>
              </select>
            </div>
            <div class="form-group">
              <label>Text Align</label>
              <select @change="updateStyle('textAlign', ($event.target as HTMLSelectElement).value)">
                <option value="left" :selected="localWidget.style?.textAlign === 'left'">Left</option>
                <option value="center" :selected="localWidget.style?.textAlign === 'center'">Center</option>
                <option value="right" :selected="localWidget.style?.textAlign === 'right'">Right</option>
              </select>
            </div>
            <div class="form-group">
              <label>Text Color</label>
              <div class="color-options">
                <button
                  v-for="color in WIDGET_COLORS.text"
                  :key="color"
                  class="color-btn"
                  :class="{ selected: localWidget.style?.textColor === color }"
                  :style="{ backgroundColor: color }"
                  @click="updateStyle('textColor', color)"
                />
              </div>
            </div>
            <div class="form-group">
              <label>Background</label>
              <div class="color-options">
                <button
                  v-for="color in WIDGET_COLORS.background"
                  :key="color"
                  class="color-btn"
                  :class="{ selected: localWidget.style?.backgroundColor === color, transparent: color === 'transparent' }"
                  :style="{ backgroundColor: color === 'transparent' ? '#333' : color }"
                  @click="updateStyle('backgroundColor', color)"
                >
                  <span v-if="color === 'transparent'" class="transparent-icon">∅</span>
                </button>
              </div>
            </div>
          </template>

          <!-- Action Button specific -->
          <template v-if="widgetType === 'action_button'">
            <!-- Action Type -->
            <div class="form-group">
              <label>Action Type</label>
              <select
                :value="localWidget.buttonAction?.type || 'system_command'"
                @change="updateButtonAction('type', ($event.target as HTMLSelectElement).value as ButtonActionType)"
              >
                <option v-for="opt in buttonActionTypes" :key="opt.value" :value="opt.value">
                  {{ opt.label }}
                </option>
              </select>
            </div>

            <!-- MQTT Publish options -->
            <template v-if="localWidget.buttonAction?.type === 'mqtt_publish'">
              <div class="form-group">
                <label>Topic</label>
                <input
                  type="text"
                  :value="localWidget.buttonAction?.topic || ''"
                  @input="updateButtonAction('topic', ($event.target as HTMLInputElement).value)"
                  placeholder="nisystem/command/..."
                />
              </div>
              <div class="form-group">
                <label>Payload</label>
                <input
                  type="text"
                  :value="localWidget.buttonAction?.payload || ''"
                  @input="updateButtonAction('payload', ($event.target as HTMLInputElement).value)"
                  placeholder="Message payload"
                />
              </div>
            </template>

            <!-- Digital Output options -->
            <template v-if="localWidget.buttonAction?.type === 'digital_output'">
              <div class="form-group">
                <label>Output Channel</label>
                <select
                  :value="localWidget.buttonAction?.channel || ''"
                  @change="updateButtonAction('channel', ($event.target as HTMLSelectElement).value)"
                >
                  <option value="">-- Select Channel --</option>
                  <option v-for="[name, config] in digitalOutputChannels" :key="name" :value="name">
                    {{ config.display_name || name }}
                  </option>
                </select>
              </div>
              <div class="form-group">
                <label>Set Value</label>
                <select
                  :value="localWidget.buttonAction?.setValue ?? 1"
                  @change="updateButtonAction('setValue', Number(($event.target as HTMLSelectElement).value))"
                >
                  <option :value="1">ON (1)</option>
                  <option :value="0">OFF (0)</option>
                </select>
              </div>
              <div class="form-group">
                <label>Pulse Duration (ms)</label>
                <input
                  type="number"
                  :value="localWidget.buttonAction?.pulseMs || 0"
                  @input="updateButtonAction('pulseMs', Number(($event.target as HTMLInputElement).value))"
                  min="0"
                  placeholder="0 = stay on"
                />
                <p class="hint">0 = permanent, otherwise reverts after duration</p>
              </div>
            </template>

            <!-- Script Run options -->
            <template v-if="localWidget.buttonAction?.type === 'script_run'">
              <div class="form-group">
                <label>Sequence</label>
                <select
                  :value="localWidget.buttonAction?.sequenceId || ''"
                  @change="updateButtonAction('sequenceId', ($event.target as HTMLSelectElement).value)"
                >
                  <option value="">-- Select Sequence --</option>
                  <option v-for="seq in availableSequences" :key="seq.id" :value="seq.id">
                    {{ seq.name }}
                  </option>
                </select>
                <p v-if="availableSequences.length === 0" class="hint">No sequences defined yet</p>
              </div>
            </template>

            <!-- System Command options -->
            <template v-if="localWidget.buttonAction?.type === 'system_command'">
              <div class="form-group">
                <label>Command</label>
                <select
                  :value="localWidget.buttonAction?.command || ''"
                  @change="updateButtonAction('command', ($event.target as HTMLSelectElement).value as SystemCommandType)"
                >
                  <option value="">-- Select Command --</option>
                  <option v-for="cmd in systemCommands" :key="cmd.value" :value="cmd.value">
                    {{ cmd.label }}
                  </option>
                </select>
              </div>
            </template>

            <!-- Confirmation required -->
            <div class="form-group checkbox">
              <label>
                <input type="checkbox" v-model="localWidget.requireConfirmation" />
                Require Confirmation
              </label>
              <p class="hint">Shows YES/NO before executing</p>
            </div>

            <!-- Button Color -->
            <div class="form-group">
              <label>Button Color</label>
              <div class="color-options">
                <button
                  v-for="color in WIDGET_COLORS.button"
                  :key="color"
                  class="color-btn"
                  :class="{ selected: localWidget.buttonColor === color }"
                  :style="{ backgroundColor: color }"
                  @click="localWidget.buttonColor = color"
                />
              </div>
            </div>
          </template>

          <!-- Clock specific -->
          <template v-if="widgetType === 'clock'">
            <div class="form-group checkbox">
              <label>
                <input type="checkbox" v-model="localWidget.showDate" />
                Show Date
              </label>
            </div>
            <div class="form-group checkbox">
              <label>
                <input type="checkbox" v-model="localWidget.showElapsed" />
                Show Run Elapsed Time
              </label>
              <p class="hint">Shows elapsed time when acquisition is running</p>
            </div>
            <div class="form-group checkbox">
              <label>
                <input type="checkbox" v-model="localWidget.format24h" />
                24-Hour Format
              </label>
            </div>
          </template>

          <!-- Gauge specific -->
          <template v-if="widgetType === 'gauge'">
            <div class="form-group">
              <label>Min Value</label>
              <input
                type="number"
                v-model.number="localWidget.minValue"
                placeholder="Auto from channel limits"
              />
              <p class="hint">Leave empty to use channel low limit</p>
            </div>
            <div class="form-group">
              <label>Max Value</label>
              <input
                type="number"
                v-model.number="localWidget.maxValue"
                placeholder="Auto from channel limits"
              />
              <p class="hint">Leave empty to use channel high limit</p>
            </div>
          </template>

          <!-- Setpoint specific -->
          <template v-if="widgetType === 'setpoint'">
            <div class="form-group">
              <label>Min Value</label>
              <input type="number" v-model.number="localWidget.minValue" placeholder="0" />
            </div>
            <div class="form-group">
              <label>Max Value</label>
              <input type="number" v-model.number="localWidget.maxValue" placeholder="100" />
            </div>
            <div class="form-group">
              <label>Step Size</label>
              <input type="number" v-model.number="localWidget.step" placeholder="1" min="0.001" step="0.1" />
            </div>
          </template>

          <!-- Bar Graph specific -->
          <template v-if="widgetType === 'bar_graph'">
            <div class="form-group">
              <label>Orientation</label>
              <select v-model="localWidget.orientation">
                <option value="horizontal">Horizontal</option>
                <option value="vertical">Vertical</option>
              </select>
            </div>
            <div class="form-group">
              <label>Min Value</label>
              <input type="number" v-model.number="localWidget.minValue" placeholder="Auto" />
            </div>
            <div class="form-group">
              <label>Max Value</label>
              <input type="number" v-model.number="localWidget.maxValue" placeholder="Auto" />
            </div>
            <div class="form-group checkbox">
              <label>
                <input type="checkbox" v-model="localWidget.showValue" />
                Show Value
              </label>
            </div>
          </template>

          <!-- Divider specific -->
          <template v-if="widgetType === 'divider'">
            <div class="form-group">
              <label>Orientation</label>
              <select v-model="localWidget.orientation">
                <option value="horizontal">Horizontal</option>
                <option value="vertical">Vertical</option>
              </select>
            </div>
            <div class="form-group">
              <label>Line Style</label>
              <select v-model="localWidget.lineStyle">
                <option value="solid">Solid</option>
                <option value="dashed">Dashed</option>
                <option value="dotted">Dotted</option>
              </select>
            </div>
            <div class="form-group">
              <label>Line Color</label>
              <div class="color-options">
                <button
                  v-for="color in ['#3b82f6', '#22c55e', '#fbbf24', '#ef4444', '#888888', '#ffffff']"
                  :key="color"
                  class="color-btn"
                  :class="{ selected: localWidget.lineColor === color }"
                  :style="{ backgroundColor: color }"
                  @click="localWidget.lineColor = color"
                />
              </div>
            </div>
          </template>
        </div>

        <div class="modal-footer">
          <button class="btn btn-secondary" @click="cancel">Cancel</button>
          <button class="btn btn-primary" @click="save">Save</button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.7);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 10000;
}

.widget-config-modal {
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 8px;
  min-width: 360px;
  max-width: 480px;
  max-height: 80vh;
  display: flex;
  flex-direction: column;
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid #2a2a4a;
}

.modal-header h3 {
  margin: 0;
  font-size: 1rem;
  color: #fff;
  text-transform: capitalize;
}

.modal-header .close-btn {
  background: none;
  border: none;
  color: #888;
  font-size: 1.5rem;
  cursor: pointer;
  padding: 0;
  line-height: 1;
}

.modal-header .close-btn:hover {
  color: #fff;
}

.modal-body {
  padding: 16px;
  overflow-y: auto;
  flex: 1;
}

.form-group {
  margin-bottom: 16px;
}

.form-group label {
  display: block;
  font-size: 0.8rem;
  color: #888;
  margin-bottom: 4px;
}

.form-group.checkbox label {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #ccc;
  cursor: pointer;
}

.form-group input[type="text"],
.form-group input[type="number"],
.form-group select {
  width: 100%;
  padding: 8px 12px;
  background: #0f0f1a;
  border: 1px solid #2a2a4a;
  border-radius: 4px;
  color: #fff;
  font-size: 0.9rem;
}

.form-group input:focus,
.form-group select:focus {
  outline: none;
  border-color: #3b82f6;
}

.channel-checklist {
  max-height: 200px;
  overflow-y: auto;
  background: #0f0f1a;
  border: 1px solid #2a2a4a;
  border-radius: 4px;
  padding: 8px;
}

.channel-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 0;
  color: #ccc;
  cursor: pointer;
}

.channel-item:hover {
  color: #fff;
}

.color-options {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.color-btn {
  width: 32px;
  height: 32px;
  border: 2px solid transparent;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.2s;
}

.color-btn:hover {
  transform: scale(1.1);
}

.color-btn.selected {
  border-color: #3b82f6;
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.3);
}

.color-btn.transparent {
  background: repeating-linear-gradient(
    45deg,
    #333,
    #333 4px,
    #444 4px,
    #444 8px
  ) !important;
}

.transparent-icon {
  color: #888;
  font-size: 1rem;
}

.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 12px 16px;
  border-top: 1px solid #2a2a4a;
}

.btn {
  padding: 8px 16px;
  border: none;
  border-radius: 4px;
  font-size: 0.85rem;
  font-weight: 500;
  cursor: pointer;
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

.hint {
  font-size: 0.7rem;
  color: #666;
  margin-top: 4px;
  font-style: italic;
}

/* Config sections for organized settings */
.config-section {
  margin-bottom: 16px;
  padding-bottom: 12px;
  border-bottom: 1px solid #2a2a4a;
}

.config-section:last-child {
  border-bottom: none;
  margin-bottom: 0;
}

.section-header {
  font-size: 0.75rem;
  font-weight: 600;
  color: #60a5fa;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 12px;
}

/* Form row for side-by-side inputs */
.form-row {
  display: flex;
  gap: 12px;
}

.form-group.half {
  flex: 1;
  margin-bottom: 12px;
}
</style>
