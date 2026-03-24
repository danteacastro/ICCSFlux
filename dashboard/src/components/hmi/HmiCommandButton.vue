<script setup lang="ts">
/**
 * HmiCommandButton — ISA-101 Command Push Button
 *
 * Supports full ButtonAction system (7 action types):
 *   digital_output, mqtt_publish, script_run, script_oneshot,
 *   variable_set, variable_reset, system_command
 *
 * Falls back to simple channel write if no hmiButtonAction configured.
 */
import { computed, ref } from 'vue'
import { useDashboardStore } from '../../stores/dashboard'
import { useMqtt } from '../../composables/useMqtt'
import { useSafety } from '../../composables/useSafety'
import { useScripts } from '../../composables/useScripts'
import { useBackendScripts } from '../../composables/useBackendScripts'
import type { PidSymbol, ButtonAction } from '../../types'

const props = defineProps<{
  symbol: PidSymbol
  editMode: boolean
}>()

const store = useDashboardStore()
const mqtt = useMqtt('nisystem')
const safety = useSafety()
const scripts = useScripts()
const backendScripts = useBackendScripts()

const isExecuting = ref(false)

// Resolve action: prefer hmiButtonAction, fall back to legacy hmiButtonValue channel write
const action = computed<ButtonAction | null>(() => {
  if (props.symbol.hmiButtonAction) return props.symbol.hmiButtonAction
  // Legacy fallback: simple channel write
  if (props.symbol.channel) {
    return {
      type: 'digital_output',
      channel: props.symbol.channel,
      setValue: props.symbol.hmiButtonValue ?? 1
    }
  }
  return null
})

const isBlocked = computed(() => {
  if (!props.symbol.channel) return false
  return safety.isOutputBlocked(props.symbol.channel).blocked
})

const canOperate = computed(() => {
  if (props.editMode) return false
  if (!action.value) return false
  if (!store.isConnected) return false
  if (isBlocked.value) return false
  // digital_output and mqtt_publish need acquisition running
  const t = action.value.type
  if ((t === 'digital_output' || t === 'mqtt_publish') && !store.isAcquiring) return false
  return true
})

async function press() {
  if (!canOperate.value || !action.value) return
  isExecuting.value = true

  try {
    const a = action.value

    switch (a.type) {
      case 'digital_output':
        if (a.channel) {
          const value = a.setValue ?? 1
          mqtt.setOutput(a.channel, value)
          if (a.pulseMs && a.pulseMs > 0) {
            setTimeout(() => {
              mqtt.setOutput(a.channel!, value === 1 ? 0 : 1)
            }, a.pulseMs)
          }
        }
        break

      case 'mqtt_publish':
        if (a.topic && a.payload !== undefined) {
          mqtt.sendCommand(a.topic, a.payload)
        }
        break

      case 'script_run':
        if (a.sequenceId) {
          scripts.startSequence(a.sequenceId)
        }
        break

      case 'script_oneshot':
        if (a.scriptName) {
          backendScripts.startScript(a.scriptName)
        }
        break

      case 'variable_set':
        if (a.variableId && a.variableValue !== undefined) {
          mqtt.sendCommand('variables/set', {
            id: a.variableId,
            value: a.variableValue
          })
        }
        break

      case 'variable_reset':
        if (a.variableId) {
          mqtt.sendCommand('variables/reset', { id: a.variableId })
        }
        break

      case 'system_command':
        if (a.command) {
          switch (a.command) {
            case 'acquisition_start': mqtt.startAcquisition(); break
            case 'acquisition_stop': mqtt.stopAcquisition(); break
            case 'recording_start': mqtt.startRecording(); break
            case 'recording_stop': mqtt.stopRecording(); break
            case 'alarm_acknowledge_all': safety.acknowledgeAll(); break
            case 'latch_reset_all': safety.resetAllLatched(); break
          }
        }
        break
    }
  } catch (err) {
    console.error('HMI button action failed:', err)
  } finally {
    setTimeout(() => { isExecuting.value = false }, 300)
  }
}

const buttonLabel = computed(() => {
  return props.symbol.label || 'CMD'
})

const actionHint = computed(() => {
  if (!action.value) return 'Not configured'
  switch (action.value.type) {
    case 'digital_output': return `DO: ${action.value.channel || '?'}`
    case 'mqtt_publish': return `MQTT: ${action.value.topic || '?'}`
    case 'script_run': return `Seq: ${action.value.sequenceId || '?'}`
    case 'script_oneshot': return `Script: ${action.value.scriptName || '?'}`
    case 'variable_set': return `Var Set: ${action.value.variableId || '?'}`
    case 'variable_reset': return `Var Reset: ${action.value.variableId || '?'}`
    case 'system_command': return action.value.command?.replace(/_/g, ' ') || '?'
    default: return ''
  }
})
</script>

<template>
  <div class="hmi-button" :class="{ blocked: isBlocked, disabled: !canOperate, executing: isExecuting }">
    <button
      class="hmi-btn-push"
      @click.stop="press"
      :disabled="!canOperate"
      :title="actionHint"
    >{{ buttonLabel }}</button>
  </div>
</template>

<style scoped>
.hmi-button {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 3px;
  background: var(--hmi-panel-bg, #D4D4D4);
  border: 1px solid var(--hmi-panel-border, #A0A0A4);
  border-radius: 2px;
  font-family: 'Segoe UI', Arial, sans-serif;
  user-select: none;
}

.hmi-button.blocked {
  border-color: var(--hmi-alarm, #FF0000);
}

.hmi-button.disabled {
  opacity: 0.5;
}

.hmi-button.executing .hmi-btn-push {
  background: var(--hmi-pressed-bg, #BBB);
  border-color: var(--hmi-accent, #4169E1);
}

.hmi-btn-push {
  width: 100%;
  height: 100%;
  border: 1px solid var(--hmi-muted-text, #888);
  border-radius: 2px;
  background: var(--hmi-inactive-bg, #E8E8E8);
  color: var(--hmi-label-text, #333);
  font-size: clamp(8px, 30%, 13px);
  font-weight: 700;
  font-family: 'Segoe UI', Arial, sans-serif;
  text-transform: uppercase;
  cursor: pointer;
  transition: all 0.1s;
}

.hmi-btn-push:not(:disabled):hover {
  border-color: var(--hmi-accent, #4169E1);
  background: var(--hmi-hover-bg, #DDD);
}

.hmi-btn-push:not(:disabled):active {
  background: var(--hmi-pressed-bg, #BBB);
  border-color: var(--hmi-accent, #4169E1);
  transform: scale(0.97);
}

.hmi-btn-push:disabled {
  cursor: default;
}
</style>
