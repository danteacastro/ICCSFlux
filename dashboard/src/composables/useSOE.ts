/**
 * SOE (Sequence of Events) & Event Correlation Composable
 *
 * Provides centralized management of:
 * - SOE events with microsecond precision timestamps
 * - Event correlation rules and detected correlations
 * - SOE buffer with filtering and export capabilities
 *
 * Works with backend's alarm_manager.py correlation engine.
 */

import { ref, computed, readonly } from 'vue'
import type {
  SOEEvent,
  SOEEventType,
  SOEQueryFilters,
  CorrelationRule,
  EventCorrelation
} from '../types'

// ============================================
// Singleton State (shared across all instances)
// ============================================

// SOE Buffer (mirrors backend's soe_buffer)
const soeEvents = ref<SOEEvent[]>([])
const maxSoeEvents = 1000  // Frontend limit (backend has 10000)

// Correlation Rules (synced from backend)
const correlationRules = ref<CorrelationRule[]>([])

// Active Correlations (detected by backend)
const activeCorrelations = ref<EventCorrelation[]>([])

// MQTT publish callback (set by useMqtt)
let mqttPublish: ((topic: string, payload: any) => void) | null = null

// Track if already initialized
let initialized = false

// ============================================
// Composable Factory
// ============================================

export function useSOE() {

  // ============================================
  // MQTT Integration
  // ============================================

  function setMqttPublish(publish: (topic: string, payload: any) => void) {
    mqttPublish = publish
  }

  // ============================================
  // SOE Event Handling
  // ============================================

  /**
   * Add an SOE event (called when receiving from MQTT)
   */
  function addSoeEvent(event: SOEEvent) {
    soeEvents.value.unshift(event)  // Most recent first

    // Trim to max size
    if (soeEvents.value.length > maxSoeEvents) {
      soeEvents.value = soeEvents.value.slice(0, maxSoeEvents)
    }
  }

  /**
   * Handle incoming SOE event from MQTT
   */
  function handleSoeEvent(payload: any) {
    try {
      const event: SOEEvent = {
        eventId: payload.event_id || payload.eventId,
        timestampUs: payload.timestamp_us || payload.timestampUs,
        timestampIso: payload.timestamp_iso || payload.timestampIso,
        eventType: payload.event_type || payload.eventType,
        sourceChannel: payload.source_channel || payload.sourceChannel,
        value: payload.value,
        previousValue: payload.previous_value ?? payload.previousValue,
        severity: payload.severity,
        message: payload.message,
        nodeId: payload.node_id ?? payload.nodeId,
        alarmId: payload.alarm_id ?? payload.alarmId,
        correlationId: payload.correlation_id ?? payload.correlationId
      }
      addSoeEvent(event)
    } catch (e) {
      console.error('Error parsing SOE event:', e)
    }
  }

  /**
   * Query SOE events with filters
   */
  function querySoeEvents(filters?: SOEQueryFilters): SOEEvent[] {
    let events = [...soeEvents.value]

    if (filters?.startTimeUs !== undefined) {
      events = events.filter(e => e.timestampUs >= filters.startTimeUs!)
    }
    if (filters?.endTimeUs !== undefined) {
      events = events.filter(e => e.timestampUs <= filters.endTimeUs!)
    }
    if (filters?.eventTypes && filters.eventTypes.length > 0) {
      events = events.filter(e => filters.eventTypes!.includes(e.eventType))
    }
    if (filters?.channels && filters.channels.length > 0) {
      events = events.filter(e => filters.channels!.includes(e.sourceChannel))
    }
    if (filters?.limit !== undefined) {
      events = events.slice(0, filters.limit)
    }

    return events
  }

  /**
   * Clear SOE buffer
   */
  function clearSoeBuffer() {
    soeEvents.value = []
  }

  /**
   * Export SOE events to CSV string
   */
  function exportSoeToCsv(filters?: SOEQueryFilters): string {
    const events = querySoeEvents(filters)
    const headers = [
      'timestamp_us', 'timestamp_iso', 'event_type', 'source_channel',
      'value', 'previous_value', 'severity', 'message', 'alarm_id',
      'correlation_id', 'node_id'
    ]

    const rows = events.map(e => [
      e.timestampUs,
      e.timestampIso,
      e.eventType,
      e.sourceChannel,
      e.value,
      e.previousValue ?? '',
      e.severity ?? '',
      `"${(e.message || '').replace(/"/g, '""')}"`,
      e.alarmId ?? '',
      e.correlationId ?? '',
      e.nodeId ?? ''
    ].join(','))

    return [headers.join(','), ...rows].join('\n')
  }

  // ============================================
  // Correlation Rule Management
  // ============================================

  /**
   * Add or update a correlation rule
   */
  function addCorrelationRule(rule: CorrelationRule) {
    const existingIndex = correlationRules.value.findIndex(r => r.id === rule.id)
    if (existingIndex >= 0) {
      correlationRules.value[existingIndex] = rule
    } else {
      correlationRules.value.push(rule)
    }

    // Notify backend
    mqttPublish?.('correlation/rules/add', {
      id: rule.id,
      name: rule.name,
      trigger_alarm: rule.triggerAlarm,
      related_alarms: rule.relatedAlarms,
      time_window_ms: rule.timeWindowMs,
      root_cause_hint: rule.rootCauseHint,
      enabled: rule.enabled,
      description: rule.description
    })
  }

  /**
   * Remove a correlation rule
   */
  function removeCorrelationRule(ruleId: string) {
    correlationRules.value = correlationRules.value.filter(r => r.id !== ruleId)
    mqttPublish?.('correlation/rules/remove', { rule_id: ruleId })
  }

  /**
   * Toggle rule enabled status
   */
  function toggleCorrelationRule(ruleId: string) {
    const rule = correlationRules.value.find(r => r.id === ruleId)
    if (rule) {
      rule.enabled = !rule.enabled
      addCorrelationRule(rule)  // Re-sync to backend
    }
  }

  /**
   * Handle correlation rules list from backend
   */
  function handleCorrelationRulesSync(payload: any[]) {
    correlationRules.value = payload.map(r => ({
      id: r.id,
      name: r.name,
      triggerAlarm: r.trigger_alarm || r.triggerAlarm,
      relatedAlarms: r.related_alarms || r.relatedAlarms || [],
      timeWindowMs: r.time_window_ms || r.timeWindowMs || 1000,
      rootCauseHint: r.root_cause_hint ?? r.rootCauseHint,
      enabled: r.enabled ?? true,
      description: r.description
    }))
  }

  // ============================================
  // Active Correlations
  // ============================================

  /**
   * Handle correlation detected event from backend
   */
  function handleCorrelationDetected(payload: any) {
    try {
      const correlation: EventCorrelation = {
        correlationId: payload.correlation_id || payload.correlationId,
        triggerAlarmId: payload.trigger_alarm_id || payload.triggerAlarmId,
        relatedAlarmIds: payload.related_alarm_ids || payload.relatedAlarmIds || [],
        timestamp: payload.timestamp,
        rootCauseAlarmId: payload.root_cause_alarm_id || payload.rootCauseAlarmId,
        ruleId: payload.correlation_rule_id || payload.ruleId,
        nodeId: payload.node_id ?? payload.nodeId
      }

      // Add to active correlations (avoid duplicates)
      const existingIndex = activeCorrelations.value.findIndex(
        c => c.correlationId === correlation.correlationId
      )
      if (existingIndex >= 0) {
        activeCorrelations.value[existingIndex] = correlation
      } else {
        activeCorrelations.value.unshift(correlation)
      }

      // Keep only recent correlations (last 100)
      if (activeCorrelations.value.length > 100) {
        activeCorrelations.value = activeCorrelations.value.slice(0, 100)
      }
    } catch (e) {
      console.error('Error parsing correlation event:', e)
    }
  }

  /**
   * Clear a correlation (when all related alarms cleared)
   */
  function clearCorrelation(correlationId: string) {
    activeCorrelations.value = activeCorrelations.value.filter(
      c => c.correlationId !== correlationId
    )
  }

  /**
   * Get correlation by ID
   */
  function getCorrelation(correlationId: string): EventCorrelation | undefined {
    return activeCorrelations.value.find(c => c.correlationId === correlationId)
  }

  /**
   * Get correlations involving a specific alarm
   */
  function getCorrelationsForAlarm(alarmId: string): EventCorrelation[] {
    return activeCorrelations.value.filter(
      c => c.triggerAlarmId === alarmId || c.relatedAlarmIds.includes(alarmId)
    )
  }

  // ============================================
  // Computed Properties
  // ============================================

  const soeEventCount = computed(() => soeEvents.value.length)
  const activeCorrelationCount = computed(() => activeCorrelations.value.length)
  const enabledRuleCount = computed(() =>
    correlationRules.value.filter(r => r.enabled).length
  )

  // Event type counts
  const soeEventCounts = computed(() => {
    const counts: Record<SOEEventType, number> = {
      alarm_triggered: 0,
      alarm_cleared: 0,
      alarm_acknowledged: 0,
      state_change: 0,
      digital_edge: 0,
      setpoint_change: 0
    }
    for (const event of soeEvents.value) {
      if (counts[event.eventType] !== undefined) {
        counts[event.eventType]++
      }
    }
    return counts
  })

  // Recent events (last 5 minutes)
  const recentEvents = computed(() => {
    const fiveMinutesAgo = Date.now() * 1000 - (5 * 60 * 1000 * 1000)  // microseconds
    return soeEvents.value.filter(e => e.timestampUs >= fiveMinutesAgo)
  })

  // ============================================
  // Initialization
  // ============================================

  function initialize() {
    if (initialized) return
    initialized = true

    // Request initial correlation rules from backend
    mqttPublish?.('correlation/rules/list', {})
  }

  // ============================================
  // Return Public API
  // ============================================

  return {
    // MQTT integration
    setMqttPublish,

    // SOE events
    soeEvents: readonly(soeEvents),
    soeEventCount,
    soeEventCounts,
    recentEvents,
    addSoeEvent,
    handleSoeEvent,
    querySoeEvents,
    clearSoeBuffer,
    exportSoeToCsv,

    // Correlation rules
    correlationRules: readonly(correlationRules),
    enabledRuleCount,
    addCorrelationRule,
    removeCorrelationRule,
    toggleCorrelationRule,
    handleCorrelationRulesSync,

    // Active correlations
    activeCorrelations: readonly(activeCorrelations),
    activeCorrelationCount,
    handleCorrelationDetected,
    clearCorrelation,
    getCorrelation,
    getCorrelationsForAlarm,

    // Initialization
    initialize
  }
}
