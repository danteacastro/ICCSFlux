<script setup lang="ts">
/**
 * HmiAlarmAnnunciator — ISA-18.2 Alarm Tile
 *
 * Shows channel alarm state. Gray when normal, colored on alarm.
 * Click to acknowledge via MQTT. Flashes when in alarm.
 */
import { computed } from 'vue'
import { useDashboardStore } from '../../stores/dashboard'
import { useMqtt } from '../../composables/useMqtt'
import type { PidSymbol } from '../../types'

const props = defineProps<{
  symbol: PidSymbol
  editMode: boolean
}>()

const store = useDashboardStore()
const mqtt = useMqtt('nisystem')

const channelValue = computed(() => {
  if (!props.symbol.channel) return null
  return store.values[props.symbol.channel] ?? null
})

const alarmState = computed<'normal' | 'alarm' | 'warning' | 'disconnected'>(() => {
  if (!channelValue.value) return 'disconnected'
  // Channel-level alarm flags (set by backend alarm manager)
  if (channelValue.value.alarm) return 'alarm'
  if (channelValue.value.warning) return 'warning'
  // Check HMI thresholds
  if (typeof channelValue.value.value === 'number') {
    const v = channelValue.value.value
    if (props.symbol.hmiAlarmHigh !== undefined && v >= props.symbol.hmiAlarmHigh) return 'alarm'
    if (props.symbol.hmiAlarmLow !== undefined && v <= props.symbol.hmiAlarmLow) return 'alarm'
    if (props.symbol.hmiWarningHigh !== undefined && v >= props.symbol.hmiWarningHigh) return 'warning'
    if (props.symbol.hmiWarningLow !== undefined && v <= props.symbol.hmiWarningLow) return 'warning'
  }
  return 'normal'
})

const isInAlarm = computed(() => {
  return alarmState.value === 'alarm' || alarmState.value === 'warning'
})

const stateLabel = computed(() => {
  switch (alarmState.value) {
    case 'alarm': return 'ALARM'
    case 'warning': return 'WARNING'
    case 'disconnected': return 'N/A'
    default: return 'NORMAL'
  }
})

function acknowledge() {
  if (props.editMode || !isInAlarm.value || !props.symbol.channel) return
  // Acknowledge all alarms for this channel
  mqtt.acknowledgeAlarm(props.symbol.channel)
}
</script>

<template>
  <div
    class="hmi-annunciator"
    :class="[alarmState, { flash: isInAlarm }]"
    @click.stop="acknowledge"
  >
    <div class="hmi-ann-tag">{{ symbol.label || symbol.channel || 'TAG' }}</div>
    <div class="hmi-ann-state">{{ stateLabel }}</div>
  </div>
</template>

<style scoped>
.hmi-annunciator {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
  background: #808080;
  border: 1px solid #666;
  border-radius: 2px;
  font-family: 'Segoe UI', Arial, sans-serif;
  user-select: none;
  cursor: default;
  padding: 2px;
}

/* Normal — dark gray, visually quiet */
.hmi-annunciator.normal {
  background: #808080;
  border-color: #666;
}

/* Disconnected */
.hmi-annunciator.disconnected {
  background: #555;
  border-color: #444;
}

/* Alarm — red */
.hmi-annunciator.alarm {
  background: #CC0000;
  border-color: #990000;
  cursor: pointer;
}

/* Warning — gold */
.hmi-annunciator.warning {
  background: #CC9900;
  border-color: #997300;
  cursor: pointer;
}

/* Flash for active alarm/warning */
.hmi-annunciator.flash {
  animation: ann-flash 1s step-end infinite;
}

@keyframes ann-flash {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

.hmi-ann-tag {
  color: rgba(255,255,255,0.85);
  font-size: clamp(7px, 22%, 10px);
  font-weight: 600;
  text-transform: uppercase;
  text-align: center;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 100%;
}

.hmi-ann-state {
  color: white;
  font-size: clamp(9px, 30%, 14px);
  font-weight: 700;
  text-transform: uppercase;
  text-align: center;
}

.normal .hmi-ann-tag,
.normal .hmi-ann-state,
.disconnected .hmi-ann-tag,
.disconnected .hmi-ann-state {
  color: rgba(255,255,255,0.6);
}
</style>
