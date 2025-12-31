<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useDashboardStore } from '../stores/dashboard'
import { useScripts } from '../composables/useScripts'
import type {
  CalculatedParam,
  Sequence,
  SequenceStep,
  SequenceStepType,
  SetVariableStep,
  Alarm,
  Transformation,
  AutomationTrigger,
  ScriptsSubTab,
  ScriptTemplate,
  FunctionBlock,
  FunctionBlockTemplate,
  FunctionBlockCategory
} from '../types/scripts'
import { SCRIPT_TEMPLATES as templates, FUNCTION_BLOCK_TEMPLATES } from '../types/scripts'

const store = useDashboardStore()
const scripts = useScripts()

// =============================================================================
// SUB-TAB NAVIGATION
// =============================================================================

const subTabs: { id: ScriptsSubTab; label: string; icon: string }[] = [
  { id: 'formulas', label: 'Formulas', icon: 'fx' },
  { id: 'functionBlocks', label: 'Blocks', icon: 'blocks' },
  { id: 'sequences', label: 'Sequences', icon: 'list' },
  { id: 'schedule', label: 'Schedule', icon: 'clock' },
  { id: 'alarms', label: 'Alarms', icon: 'bell' },
  { id: 'transformations', label: 'Transforms', icon: 'chart' },
  { id: 'triggers', label: 'Triggers', icon: 'zap' },
  { id: 'templates', label: 'Templates', icon: 'book' }
]

// =============================================================================
// FORMULAS TAB STATE
// =============================================================================

const showFormulaEditor = ref(false)
const selectedFormula = ref<string | null>(null)
const formulaForm = ref({
  id: '',
  name: '',
  displayName: '',
  formula: '',
  unit: ''
})

// =============================================================================
// SEQUENCES TAB STATE
// =============================================================================

const showSequenceEditor = ref(false)
const selectedSequence = ref<string | null>(null)
const sequenceForm = ref<Partial<Sequence>>({
  name: '',
  description: '',
  steps: [],
  enabled: true
})
const editingStepIndex = ref<number | null>(null)
const showStepEditor = ref(false)
const stepForm = ref<Partial<SequenceStep>>({})

// =============================================================================
// SCHEDULE TAB STATE
// =============================================================================

const showScheduleEditor = ref(false)
const selectedSchedule = ref<string | null>(null)
const scheduleForm = ref({
  name: '',
  description: '',
  enabled: true,
  startTime: '08:00',
  endTime: '',
  repeat: 'daily' as 'once' | 'daily' | 'weekly' | 'monthly',
  daysOfWeek: [] as number[],
  dayOfMonth: 1,
  date: '',
  startActions: [] as any[],
  endActions: [] as any[]
})

const dayNames = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']

function openScheduleEditor(schedule?: any) {
  if (schedule) {
    selectedSchedule.value = schedule.id
    scheduleForm.value = {
      name: schedule.name,
      description: schedule.description || '',
      enabled: schedule.enabled,
      startTime: schedule.startTime,
      endTime: schedule.endTime || '',
      repeat: schedule.repeat,
      daysOfWeek: schedule.daysOfWeek || [],
      dayOfMonth: schedule.dayOfMonth || 1,
      date: schedule.date || '',
      startActions: schedule.startActions || [],
      endActions: schedule.endActions || []
    }
  } else {
    selectedSchedule.value = null
    scheduleForm.value = {
      name: '',
      description: '',
      enabled: true,
      startTime: '08:00',
      endTime: '',
      repeat: 'daily',
      daysOfWeek: [],
      dayOfMonth: 1,
      date: '',
      startActions: [],
      endActions: []
    }
  }
  showScheduleEditor.value = true
}

function closeScheduleEditor() {
  showScheduleEditor.value = false
  selectedSchedule.value = null
}

function saveSchedule() {
  const data = {
    name: scheduleForm.value.name,
    description: scheduleForm.value.description,
    enabled: scheduleForm.value.enabled,
    startTime: scheduleForm.value.startTime,
    endTime: scheduleForm.value.endTime || undefined,
    repeat: scheduleForm.value.repeat,
    daysOfWeek: scheduleForm.value.repeat === 'weekly' ? scheduleForm.value.daysOfWeek : undefined,
    dayOfMonth: scheduleForm.value.repeat === 'monthly' ? scheduleForm.value.dayOfMonth : undefined,
    date: scheduleForm.value.repeat === 'once' ? scheduleForm.value.date : undefined,
    startActions: scheduleForm.value.startActions,
    endActions: scheduleForm.value.endActions
  }

  if (selectedSchedule.value) {
    scripts.updateSchedule(selectedSchedule.value, data)
  } else {
    scripts.addSchedule(data as any)
  }
  closeScheduleEditor()
}

function toggleDayOfWeek(day: number) {
  const idx = scheduleForm.value.daysOfWeek.indexOf(day)
  if (idx >= 0) {
    scheduleForm.value.daysOfWeek.splice(idx, 1)
  } else {
    scheduleForm.value.daysOfWeek.push(day)
  }
}

function formatNextRun(isoString?: string): string {
  if (!isoString) return 'Not scheduled'
  const date = new Date(isoString)
  return date.toLocaleString()
}

// =============================================================================
// ALARMS TAB STATE
// =============================================================================

const showAlarmEditor = ref(false)
const selectedAlarm = ref<string | null>(null)
const alarmForm = ref<Partial<Alarm>>({
  name: '',
  description: '',
  severity: 'warning',
  conditions: [],
  conditionLogic: 'AND',
  debounceMs: 1000,
  autoResetMs: 0,
  actions: [],
  enabled: true
})

// =============================================================================
// TRANSFORMATIONS TAB STATE
// =============================================================================

const showTransformEditor = ref(false)
const selectedTransform = ref<string | null>(null)
const transformForm = ref<Partial<Transformation>>({
  name: '',
  displayName: '',
  type: 'rollingAverage',
  inputChannel: '',
  outputUnit: '',
  enabled: true
})

// =============================================================================
// TRIGGERS TAB STATE
// =============================================================================

const showTriggerEditor = ref(false)
const selectedTrigger = ref<string | null>(null)
const triggerForm = ref<Partial<AutomationTrigger>>({
  name: '',
  description: '',
  enabled: true,
  oneShot: false,
  cooldownMs: 5000,
  trigger: {
    id: '',
    name: '',
    description: '',
    type: 'valueReached',
    enabled: true,
    oneShot: false,
    cooldownMs: 5000,
    channel: '',
    operator: '>',
    value: 0,
    hysteresis: 0
  } as any,
  actions: []
})

// =============================================================================
// TEMPLATES TAB STATE
// =============================================================================

const selectedTemplate = ref<ScriptTemplate | null>(null)
const templateParams = ref<Record<string, string | number>>({})

// =============================================================================
// FUNCTION BLOCKS TAB STATE
// =============================================================================

const showBlockEditor = ref(false)
const selectedBlock = ref<string | null>(null)
const selectedBlockTemplate = ref<FunctionBlockTemplate | null>(null)
const newBlockName = ref('')
const blockSearchQuery = ref('')

// Computed: group templates by category
const blockTemplatesByCategory = computed(() => {
  const groups: Record<FunctionBlockCategory, FunctionBlockTemplate[]> = {
    control: [],
    math: [],
    filter: [],
    statistics: [],
    thermal: [],
    logic: [],
    timing: [],
    custom: []
  }
  FUNCTION_BLOCK_TEMPLATES.forEach(t => {
    groups[t.category].push(t)
  })
  return groups
})

// Computed: filtered blocks by search
const filteredBlocks = computed(() => {
  if (!blockSearchQuery.value) return scripts.functionBlocks.value
  const q = blockSearchQuery.value.toLowerCase()
  return scripts.functionBlocks.value.filter(b =>
    b.displayName.toLowerCase().includes(q) ||
    b.name.toLowerCase().includes(q) ||
    b.category.toLowerCase().includes(q)
  )
})

// =============================================================================
// CHANNEL HELPERS
// =============================================================================

const channelVariables = computed(() => {
  return Object.entries(store.channels).map(([name, config]) => ({
    name,
    displayName: config.display_name || name,
    variable: `ch.${name.replace(/[^a-zA-Z0-9_]/g, '_')}`,
    type: config.channel_type,
    unit: config.unit
  }))
})

const outputChannels = computed(() => {
  return channelVariables.value.filter(ch =>
    ch.type === 'digital_output' || ch.type === 'analog_output'
  )
})

const inputChannels = computed(() => {
  return channelVariables.value.filter(ch =>
    ch.type !== 'digital_output' && ch.type !== 'analog_output'
  )
})

// =============================================================================
// FORMULA METHODS
// =============================================================================

function createFormula() {
  formulaForm.value = {
    id: `calc-${Date.now()}`,
    name: '',
    displayName: '',
    formula: '',
    unit: ''
  }
  selectedFormula.value = null
  showFormulaEditor.value = true
}

function editFormula(param: CalculatedParam) {
  formulaForm.value = {
    id: param.id,
    name: param.name,
    displayName: param.displayName,
    formula: param.formula,
    unit: param.unit
  }
  selectedFormula.value = param.id
  showFormulaEditor.value = true
}

function saveFormula() {
  const existing = scripts.calculatedParams.value.find(p => p.id === formulaForm.value.id)

  if (existing) {
    scripts.updateCalculatedParam(formulaForm.value.id, {
      name: formulaForm.value.name,
      displayName: formulaForm.value.displayName,
      formula: formulaForm.value.formula,
      unit: formulaForm.value.unit
    })
  } else {
    scripts.addCalculatedParam({
      name: formulaForm.value.name,
      displayName: formulaForm.value.displayName,
      formula: formulaForm.value.formula,
      unit: formulaForm.value.unit,
      enabled: true
    })
  }

  showFormulaEditor.value = false
}

function deleteFormula(id: string) {
  if (confirm('Delete this calculated parameter?')) {
    scripts.deleteCalculatedParam(id)
    if (selectedFormula.value === id) {
      selectedFormula.value = null
      showFormulaEditor.value = false
    }
  }
}

function toggleFormula(id: string) {
  const param = scripts.calculatedParams.value.find(p => p.id === id)
  if (param) {
    scripts.updateCalculatedParam(id, { enabled: !param.enabled })
  }
}

function insertVariable(variable: string) {
  formulaForm.value.formula += variable
}

// =============================================================================
// SEQUENCE METHODS
// =============================================================================

function createSequence() {
  sequenceForm.value = {
    name: '',
    description: '',
    steps: [],
    enabled: true
  }
  selectedSequence.value = null
  showSequenceEditor.value = true
}

function editSequence(seq: Sequence) {
  sequenceForm.value = { ...seq, steps: [...seq.steps] }
  selectedSequence.value = seq.id
  showSequenceEditor.value = true
}

function saveSequence() {
  if (selectedSequence.value) {
    scripts.updateSequence(selectedSequence.value, sequenceForm.value)
  } else {
    scripts.addSequence(sequenceForm.value as any)
  }
  showSequenceEditor.value = false
}

function deleteSequence(id: string) {
  if (confirm('Delete this sequence?')) {
    scripts.deleteSequence(id)
    if (selectedSequence.value === id) {
      selectedSequence.value = null
      showSequenceEditor.value = false
    }
  }
}

function addStep(type: SequenceStepType) {
  const step: SequenceStep = {
    id: `step-${Date.now()}`,
    type,
    enabled: true,
    label: ''
  } as any

  // Set defaults based on type
  switch (type) {
    case 'ramp':
      Object.assign(step, {
        targetChannel: '',
        monitorChannel: '',
        targetValue: 100,
        rampRate: 10,
        rampRateUnit: '°C/min',
        tolerance: 2
      })
      break
    case 'soak':
      Object.assign(step, { duration: 60 })
      break
    case 'wait':
      Object.assign(step, {
        condition: '',
        timeout: 0,
        timeoutAction: 'abort'
      })
      break
    case 'setOutput':
      Object.assign(step, { channel: '', value: 0 })
      break
    case 'loop':
      Object.assign(step, {
        iterations: 1,
        loopId: `loop-${Date.now()}`
      })
      break
    case 'endLoop':
      Object.assign(step, { loopId: '' })
      break
    case 'message':
      Object.assign(step, {
        message: '',
        severity: 'info',
        pauseExecution: false
      })
      break
    case 'setVariable':
      Object.assign(step, {
        variableName: '',
        value: 0,
        isFormula: false
      })
      break
  }

  sequenceForm.value.steps = [...(sequenceForm.value.steps || []), step]
}

function editStep(index: number) {
  editingStepIndex.value = index
  stepForm.value = { ...sequenceForm.value.steps![index] }
  showStepEditor.value = true
}

function saveStep() {
  if (editingStepIndex.value !== null && sequenceForm.value.steps) {
    sequenceForm.value.steps[editingStepIndex.value] = stepForm.value as SequenceStep
  }
  showStepEditor.value = false
  editingStepIndex.value = null
}

function removeStep(index: number) {
  sequenceForm.value.steps = sequenceForm.value.steps?.filter((_, i) => i !== index)
}

function moveStep(index: number, direction: 'up' | 'down') {
  if (!sequenceForm.value.steps) return
  const newIndex = direction === 'up' ? index - 1 : index + 1
  if (newIndex < 0 || newIndex >= sequenceForm.value.steps.length) return

  const steps = [...sequenceForm.value.steps]
  const temp = steps[index]!
  steps[index] = steps[newIndex]!
  steps[newIndex] = temp
  sequenceForm.value.steps = steps
}

function getStepIcon(type: SequenceStepType): string {
  const icons: Record<SequenceStepType, string> = {
    ramp: '📈',
    soak: '⏸️',
    wait: '⏳',
    setOutput: '🎚️',
    setVariable: '📝',
    loop: '🔄',
    endLoop: '↩️',
    message: '💬'
  }
  return icons[type] || '•'
}

function getStepDescription(step: SequenceStep): string {
  switch (step.type) {
    case 'ramp':
      return `Ramp to ${step.targetValue}${step.rampRateUnit?.replace('/min', '')} at ${step.rampRate} ${step.rampRateUnit}`
    case 'soak':
      return `Soak for ${step.duration}s`
    case 'wait':
      return `Wait: ${step.condition || '(no condition)'}`
    case 'setOutput':
      return `Set ${step.channel} = ${step.value}`
    case 'setVariable':
      const varStep = step as SetVariableStep
      if (varStep.isFormula) {
        return `${varStep.variableName} = ${varStep.value} (formula)`
      }
      return `${varStep.variableName} = ${varStep.value}`
    case 'loop':
      return `Loop ${step.iterations}x`
    case 'endLoop':
      return `End Loop`
    case 'message':
      return `Message: ${step.message || '(empty)'}`
  }
}

// =============================================================================
// ALARM METHODS
// =============================================================================

function createAlarm() {
  alarmForm.value = {
    name: '',
    description: '',
    severity: 'warning',
    conditions: [],
    conditionLogic: 'AND',
    debounceMs: 1000,
    autoResetMs: 0,
    actions: [],
    enabled: true
  }
  selectedAlarm.value = null
  showAlarmEditor.value = true
}

function editAlarm(alarm: Alarm) {
  alarmForm.value = { ...alarm, conditions: [...alarm.conditions], actions: [...alarm.actions] }
  selectedAlarm.value = alarm.id
  showAlarmEditor.value = true
}

function saveAlarm() {
  if (selectedAlarm.value) {
    scripts.updateAlarm(selectedAlarm.value, alarmForm.value)
  } else {
    scripts.addAlarm(alarmForm.value as any)
  }
  showAlarmEditor.value = false
}

function deleteAlarm(id: string) {
  if (confirm('Delete this alarm?')) {
    scripts.deleteAlarm(id)
    if (selectedAlarm.value === id) {
      selectedAlarm.value = null
      showAlarmEditor.value = false
    }
  }
}

function addCondition() {
  alarmForm.value.conditions = [
    ...(alarmForm.value.conditions || []),
    { channel: '', operator: '>', value: 0 }
  ]
}

function removeCondition(index: number) {
  alarmForm.value.conditions = alarmForm.value.conditions?.filter((_, i) => i !== index)
}

function addAction() {
  alarmForm.value.actions = [
    ...(alarmForm.value.actions || []),
    { type: 'notification', message: '' }
  ]
}

function removeAction(index: number) {
  alarmForm.value.actions = alarmForm.value.actions?.filter((_, i) => i !== index)
}

// =============================================================================
// TRANSFORMATION METHODS
// =============================================================================

function createTransform() {
  transformForm.value = {
    name: '',
    displayName: '',
    type: 'rollingAverage',
    inputChannel: '',
    outputUnit: '',
    enabled: true
  }
  selectedTransform.value = null
  showTransformEditor.value = true
}

function editTransform(transform: Transformation) {
  transformForm.value = { ...transform }
  selectedTransform.value = transform.id
  showTransformEditor.value = true
}

function saveTransform() {
  // Add type-specific defaults
  const baseTransform = {
    ...transformForm.value,
    lastValue: null,
    lastError: null
  }

  switch (transformForm.value.type) {
    case 'rollingAverage':
    case 'rollingMin':
    case 'rollingMax':
    case 'rollingStdDev':
      Object.assign(baseTransform, {
        windowSize: (transformForm.value as any).windowSize || 10,
        windowType: 'samples'
      })
      break
    case 'rateOfChange':
      Object.assign(baseTransform, {
        timeWindowMs: (transformForm.value as any).timeWindowMs || 1000,
        rateUnit: (transformForm.value as any).rateUnit || '/min'
      })
      break
    case 'unitConversion':
      Object.assign(baseTransform, {
        conversionType: (transformForm.value as any).conversionType || 'celsius_to_fahrenheit'
      })
      break
    case 'polynomial':
      Object.assign(baseTransform, {
        coefficients: (transformForm.value as any).coefficients || [0, 1]
      })
      break
    case 'deadband':
      Object.assign(baseTransform, {
        deadband: (transformForm.value as any).deadband || 1
      })
      break
    case 'clamp':
      Object.assign(baseTransform, {
        minValue: (transformForm.value as any).minValue || 0,
        maxValue: (transformForm.value as any).maxValue || 100
      })
      break
  }

  if (selectedTransform.value) {
    scripts.updateTransformation(selectedTransform.value, baseTransform as any)
  } else {
    scripts.addTransformation(baseTransform as any)
  }
  showTransformEditor.value = false
}

function deleteTransform(id: string) {
  if (confirm('Delete this transformation?')) {
    scripts.deleteTransformation(id)
    if (selectedTransform.value === id) {
      selectedTransform.value = null
      showTransformEditor.value = false
    }
  }
}

// =============================================================================
// TRIGGER METHODS
// =============================================================================

function createTrigger() {
  triggerForm.value = {
    name: '',
    description: '',
    enabled: true,
    oneShot: false,
    cooldownMs: 5000,
    trigger: {
      type: 'valueReached',
      channel: '',
      operator: '>',
      value: 0,
      hysteresis: 0
    } as any,
    actions: []
  }
  selectedTrigger.value = null
  showTriggerEditor.value = true
}

function editTrigger(trigger: AutomationTrigger) {
  triggerForm.value = { ...trigger, actions: [...trigger.actions] }
  selectedTrigger.value = trigger.id
  showTriggerEditor.value = true
}

function saveTrigger() {
  if (selectedTrigger.value) {
    scripts.updateTrigger(selectedTrigger.value, triggerForm.value)
  } else {
    scripts.addTrigger(triggerForm.value as any)
  }
  showTriggerEditor.value = false
}

function deleteTrigger(id: string) {
  if (confirm('Delete this trigger?')) {
    scripts.deleteTrigger(id)
    if (selectedTrigger.value === id) {
      selectedTrigger.value = null
      showTriggerEditor.value = false
    }
  }
}

function addTriggerAction() {
  triggerForm.value.actions = [
    ...(triggerForm.value.actions || []),
    { type: 'notification', message: '' }
  ]
}

function removeTriggerAction(index: number) {
  triggerForm.value.actions = triggerForm.value.actions?.filter((_, i) => i !== index)
}

// =============================================================================
// TEMPLATE METHODS
// =============================================================================

function selectTemplate(template: ScriptTemplate) {
  selectedTemplate.value = template
  templateParams.value = {}
  template.parameters.forEach(param => {
    templateParams.value[param.name] = param.default || ''
  })
}

function applyTemplate() {
  if (!selectedTemplate.value) return

  let formula = selectedTemplate.value.formula

  // Replace parameters
  Object.entries(templateParams.value).forEach(([key, value]) => {
    formula = formula.replace(new RegExp(`\\$\\{${key}\\}`, 'g'), String(value))
  })

  scripts.addCalculatedParam({
    name: selectedTemplate.value.id + '-' + Date.now(),
    displayName: selectedTemplate.value.name,
    formula,
    unit: selectedTemplate.value.unit,
    enabled: true,
    category: 'template',
    templateId: selectedTemplate.value.id
  })

  // Switch to formulas tab
  scripts.activeSubTab.value = 'formulas'
  selectedTemplate.value = null
}

// =============================================================================
// FUNCTION BLOCK METHODS
// =============================================================================

function selectBlockTemplate(template: FunctionBlockTemplate) {
  selectedBlockTemplate.value = template
  newBlockName.value = template.name
}

function createBlock() {
  if (!selectedBlockTemplate.value || !newBlockName.value.trim()) return

  const blockId = scripts.createFunctionBlockFromTemplate(
    selectedBlockTemplate.value.id,
    newBlockName.value.trim()
  )

  if (blockId) {
    selectedBlock.value = blockId
    showBlockEditor.value = true
  }

  selectedBlockTemplate.value = null
  newBlockName.value = ''
}

function editBlock(block: FunctionBlock) {
  selectedBlock.value = block.id
  showBlockEditor.value = true
}

function closeBlockEditor() {
  selectedBlock.value = null
  showBlockEditor.value = false
}

function deleteBlock(id: string) {
  if (confirm('Delete this function block?')) {
    scripts.deleteFunctionBlock(id)
    if (selectedBlock.value === id) {
      closeBlockEditor()
    }
  }
}

function toggleBlock(id: string) {
  const block = scripts.functionBlocks.value.find(b => b.id === id)
  if (block) {
    scripts.updateFunctionBlock(id, { enabled: !block.enabled })
  }
}

function resetBlock(id: string) {
  scripts.resetFunctionBlockState(id)
}

function updateBlockInput(blockId: string, inputName: string, value: string) {
  scripts.updateFunctionBlockInput(blockId, inputName, value)
}

// Get selected block object
const selectedBlockData = computed(() => {
  if (!selectedBlock.value) return null
  return scripts.functionBlocks.value.find(b => b.id === selectedBlock.value) || null
})

// Available binding options for inputs
const bindingOptions = computed(() => {
  const options: Array<{ value: string; label: string; group: string }> = []

  // Add channels
  Object.entries(store.channels).forEach(([name, config]) => {
    options.push({
      value: name,
      label: config.display_name || name,
      group: 'Channels'
    })
  })

  // Add calculated params
  scripts.calculatedParams.value.forEach(p => {
    options.push({
      value: p.name,
      label: p.displayName || p.name,
      group: 'Calculated'
    })
  })

  // Add other function block outputs
  scripts.functionBlocks.value.forEach(block => {
    if (block.id !== selectedBlock.value) {
      block.outputs.forEach(output => {
        options.push({
          value: `${block.id}.${output.name}`,
          label: `${block.displayName} → ${output.label}`,
          group: 'Blocks'
        })
      })
    }
  })

  return options
})

// Category icons
function getCategoryIcon(category: FunctionBlockCategory): string {
  const icons: Record<FunctionBlockCategory, string> = {
    control: '⚙️',
    math: '➗',
    filter: '〰️',
    statistics: '📊',
    thermal: '🌡️',
    logic: '⚖️',
    timing: '⏱️',
    custom: '🔧'
  }
  return icons[category] || '📦'
}

// =============================================================================
// LIFECYCLE
// =============================================================================

onMounted(() => {
  scripts.loadAll()
  // Start evaluation - it's a singleton so it won't create duplicate intervals
  scripts.startEvaluation()
})

// Note: We don't stop evaluation on unmount since scripts module is a singleton
// and evaluation should continue running in background

// Preview for formula editor
const formulaPreview = computed(() => {
  if (!formulaForm.value.formula) return null
  return scripts.evaluateFormula(formulaForm.value.formula)
})

// Template categories
const templateCategories = computed(() => {
  const categories: Record<string, ScriptTemplate[]> = {}
  templates.forEach(t => {
    if (!categories[t.category]) {
      categories[t.category] = []
    }
    categories[t.category]!.push(t)
  })
  return categories
})
</script>

<template>
  <div class="scripts-tab">
    <!-- Sub-tab Navigation -->
    <div class="sub-tabs">
      <button
        v-for="tab in subTabs"
        :key="tab.id"
        class="sub-tab"
        :class="{ active: scripts.activeSubTab.value === tab.id }"
        @click="scripts.activeSubTab.value = tab.id"
      >
        <span class="tab-icon">{{ tab.icon === 'fx' ? 'ƒx' : tab.icon === 'blocks' ? '🧩' : tab.icon === 'list' ? '☰' : tab.icon === 'bell' ? '🔔' : tab.icon === 'chart' ? '📊' : tab.icon === 'zap' ? '⚡' : '📖' }}</span>
        <span class="tab-label">{{ tab.label }}</span>
        <span v-if="tab.id === 'alarms' && scripts.activeAlarmIds.value.length" class="badge alarm">
          {{ scripts.activeAlarmIds.value.length }}
        </span>
        <span v-if="tab.id === 'sequences' && scripts.runningSequenceId.value" class="badge running">
          ●
        </span>
      </button>
    </div>

    <!-- ===================================================================== -->
    <!-- FORMULAS TAB -->
    <!-- ===================================================================== -->
    <div v-if="scripts.activeSubTab.value === 'formulas'" class="tab-content">
      <div class="toolbar">
        <button class="btn btn-primary" @click="createFormula">
          <span class="icon">+</span> New Formula
        </button>
        <div class="count">{{ scripts.calculatedParams.value.length }} formulas</div>
      </div>

      <div class="main-content">
        <!-- List -->
        <div class="list-panel">
          <div class="list-header">CALCULATED PARAMETERS</div>
          <div
            v-for="param in scripts.calculatedParams.value"
            :key="param.id"
            class="list-item"
            :class="{ selected: selectedFormula === param.id, disabled: !param.enabled }"
            @click="editFormula(param)"
          >
            <div class="item-info">
              <div class="item-name">{{ param.displayName || param.name }}</div>
              <div class="item-sub">{{ param.formula }}</div>
            </div>
            <div class="item-value" :class="{ error: param.lastError }">
              <span v-if="param.lastError" class="error-icon" :title="param.lastError">⚠</span>
              <span v-else-if="param.lastValue !== null">
                {{ param.lastValue.toFixed(3) }}
                <span class="unit">{{ param.unit }}</span>
              </span>
              <span v-else class="no-value">--</span>
            </div>
            <div class="item-actions">
              <button class="toggle-btn" :class="{ on: param.enabled }" @click.stop="toggleFormula(param.id)">
                <span class="slider"></span>
              </button>
              <button class="delete-btn" @click.stop="deleteFormula(param.id)">✕</button>
            </div>
          </div>
          <div v-if="scripts.calculatedParams.value.length === 0" class="empty-list">
            <p>No calculated parameters</p>
            <p class="hint">Create formulas to compute derived values from channels</p>
          </div>
        </div>

        <!-- Editor -->
        <div class="editor-panel" :class="{ visible: showFormulaEditor }">
          <div class="editor-header">
            <h3>{{ selectedFormula ? 'Edit' : 'New' }} Formula</h3>
            <button class="close-btn" @click="showFormulaEditor = false">✕</button>
          </div>
          <div class="editor-form">
            <div class="form-group">
              <label>Name (ID)</label>
              <input v-model="formulaForm.name" type="text" placeholder="e.g., avg_temp" />
            </div>
            <div class="form-group">
              <label>Display Name</label>
              <input v-model="formulaForm.displayName" type="text" placeholder="e.g., Average Temperature" />
            </div>
            <div class="form-group">
              <label>Unit</label>
              <input v-model="formulaForm.unit" type="text" placeholder="e.g., °C" />
            </div>
            <div class="form-group">
              <label>Formula</label>
              <textarea v-model="formulaForm.formula" placeholder="e.g., (ch.TC_Zone1 + ch.TC_Zone2) / 2" rows="3"></textarea>
              <div class="formula-help">
                Use <code>ch.CHANNEL_NAME</code> for channel values. Math: abs, sqrt, pow, log, sin, cos, min, max, PI
              </div>
            </div>
            <div class="form-group">
              <label>Available Channels</label>
              <div class="channel-chips">
                <button
                  v-for="ch in channelVariables"
                  :key="ch.name"
                  class="channel-chip"
                  @click="insertVariable(ch.variable)"
                  :title="ch.displayName"
                >
                  {{ ch.name }}
                </button>
              </div>
            </div>
            <div class="form-group" v-if="formulaForm.formula">
              <label>Preview</label>
              <div class="preview-value">
                <template v-if="formulaPreview?.error">
                  <span class="error">{{ formulaPreview.error }}</span>
                </template>
                <template v-else>
                  <span class="value">{{ formulaPreview?.value?.toFixed(3) }}</span>
                  <span class="unit">{{ formulaForm.unit }}</span>
                </template>
              </div>
            </div>
          </div>
          <div class="editor-actions">
            <button class="btn btn-secondary" @click="showFormulaEditor = false">Cancel</button>
            <button class="btn btn-primary" @click="saveFormula" :disabled="!formulaForm.name || !formulaForm.formula">Save</button>
          </div>
        </div>
      </div>
    </div>

    <!-- ===================================================================== -->
    <!-- FUNCTION BLOCKS TAB -->
    <!-- ===================================================================== -->
    <div v-if="scripts.activeSubTab.value === 'functionBlocks'" class="tab-content">
      <div class="toolbar">
        <input
          v-model="blockSearchQuery"
          type="text"
          placeholder="Search blocks..."
          class="search-input"
        />
        <div class="count">{{ scripts.functionBlocks.value.length }} blocks</div>
      </div>

      <div class="main-content blocks-layout">
        <!-- Left: Block templates (Add new block) -->
        <div class="templates-panel">
          <div class="list-header">ADD NEW BLOCK</div>

          <!-- Selected template form -->
          <div v-if="selectedBlockTemplate" class="create-block-form">
            <div class="selected-template">
              <span class="template-icon">{{ selectedBlockTemplate.icon }}</span>
              <span class="template-name">{{ selectedBlockTemplate.name }}</span>
              <button class="clear-btn" @click="selectedBlockTemplate = null">✕</button>
            </div>
            <input
              v-model="newBlockName"
              type="text"
              placeholder="Block name..."
              class="block-name-input"
            />
            <button class="btn btn-primary btn-full" @click="createBlock" :disabled="!newBlockName.trim()">
              Create Block
            </button>
          </div>

          <!-- Template categories -->
          <div v-else class="template-categories">
            <div
              v-for="(categoryTemplates, category) in blockTemplatesByCategory"
              :key="category"
              class="block-category"
            >
              <div v-if="categoryTemplates.length > 0" class="category-header">
                <span class="category-icon">{{ getCategoryIcon(category as FunctionBlockCategory) }}</span>
                {{ category.toUpperCase() }}
              </div>
              <div class="category-templates">
                <button
                  v-for="template in categoryTemplates"
                  :key="template.id"
                  class="template-btn"
                  @click="selectBlockTemplate(template)"
                  :title="template.description"
                >
                  <span class="t-icon">{{ template.icon }}</span>
                  <span class="t-name">{{ template.name }}</span>
                </button>
              </div>
            </div>
          </div>
        </div>

        <!-- Middle: Active blocks list -->
        <div class="list-panel blocks-list">
          <div class="list-header">ACTIVE BLOCKS</div>
          <div
            v-for="block in filteredBlocks"
            :key="block.id"
            class="list-item block-item"
            :class="{
              selected: selectedBlock === block.id,
              disabled: !block.enabled
            }"
            @click="editBlock(block)"
          >
            <div class="block-category-icon">{{ getCategoryIcon(block.category) }}</div>
            <div class="item-info">
              <div class="item-name">{{ block.displayName }}</div>
              <div class="item-sub">{{ block.description }}</div>
            </div>
            <div class="block-outputs">
              <div
                v-for="output in block.outputs.slice(0, 2)"
                :key="output.name"
                class="output-value"
                :class="{ error: output.error }"
              >
                <span class="output-name">{{ output.label }}:</span>
                <span v-if="output.error" class="error-icon" :title="output.error">⚠</span>
                <span v-else-if="output.value !== null" class="value">
                  {{ output.value.toFixed(2) }}
                  <span class="unit">{{ output.unit }}</span>
                </span>
                <span v-else class="no-value">--</span>
              </div>
            </div>
            <div class="item-actions">
              <button
                class="toggle-btn"
                :class="{ on: block.enabled }"
                @click.stop="toggleBlock(block.id)"
              >
                <span class="slider"></span>
              </button>
              <button class="delete-btn" @click.stop="deleteBlock(block.id)">✕</button>
            </div>
          </div>
          <div v-if="scripts.functionBlocks.value.length === 0" class="empty-list">
            <p>No function blocks</p>
            <p class="hint">Select a template from the left to create a block</p>
          </div>
        </div>

        <!-- Right: Block configuration editor -->
        <div class="editor-panel block-editor" :class="{ visible: showBlockEditor && selectedBlockData }">
          <template v-if="selectedBlockData">
            <div class="editor-header">
              <h3>
                <span class="block-icon">{{ getCategoryIcon(selectedBlockData.category) }}</span>
                {{ selectedBlockData.displayName }}
              </h3>
              <div class="header-actions">
                <button class="action-btn" @click="resetBlock(selectedBlockData.id)" title="Reset state">
                  🔄
                </button>
                <button class="close-btn" @click="closeBlockEditor">✕</button>
              </div>
            </div>

            <div class="editor-form">
              <!-- Block info -->
              <div class="block-info">
                <p>{{ selectedBlockData.description }}</p>
                <span class="block-category-badge">{{ selectedBlockData.category }}</span>
              </div>

              <!-- Inputs -->
              <div class="form-section">
                <div class="section-header">INPUTS</div>
                <div class="inputs-grid">
                  <div
                    v-for="input in selectedBlockData.inputs"
                    :key="input.name"
                    class="input-row"
                  >
                    <label class="input-label">
                      {{ input.label }}
                      <span v-if="input.required" class="required">*</span>
                      <span v-if="input.unit" class="input-unit">({{ input.unit }})</span>
                    </label>

                    <!-- Number input -->
                    <template v-if="input.type === 'number'">
                      <input
                        type="number"
                        :value="input.binding || input.defaultValue"
                        @input="updateBlockInput(selectedBlockData!.id, input.name, ($event.target as HTMLInputElement).value)"
                        :min="input.min"
                        :max="input.max"
                        :step="0.1"
                        class="number-input"
                      />
                    </template>

                    <!-- Boolean input -->
                    <template v-else-if="input.type === 'boolean'">
                      <select
                        :value="input.binding || (input.defaultValue ? 'true' : 'false')"
                        @change="updateBlockInput(selectedBlockData!.id, input.name, ($event.target as HTMLSelectElement).value)"
                        class="bool-select"
                      >
                        <option value="false">Off (0)</option>
                        <option value="true">On (1)</option>
                      </select>
                    </template>

                    <!-- Channel / block output binding -->
                    <template v-else>
                      <select
                        :value="input.binding || ''"
                        @change="updateBlockInput(selectedBlockData!.id, input.name, ($event.target as HTMLSelectElement).value)"
                        class="binding-select"
                      >
                        <option value="">Select source...</option>
                        <optgroup label="Channels">
                          <option
                            v-for="ch in channelVariables"
                            :key="ch.name"
                            :value="ch.name"
                          >
                            {{ ch.displayName }} ({{ ch.unit }})
                          </option>
                        </optgroup>
                        <optgroup label="Calculated">
                          <option
                            v-for="p in scripts.calculatedParams.value"
                            :key="p.id"
                            :value="p.name"
                          >
                            {{ p.displayName || p.name }}
                          </option>
                        </optgroup>
                        <optgroup label="Block Outputs">
                          <option
                            v-for="opt in bindingOptions.filter(o => o.group === 'Blocks')"
                            :key="opt.value"
                            :value="opt.value"
                          >
                            {{ opt.label }}
                          </option>
                        </optgroup>
                      </select>
                    </template>
                  </div>
                </div>
              </div>

              <!-- Outputs -->
              <div class="form-section">
                <div class="section-header">OUTPUTS</div>
                <div class="outputs-grid">
                  <div
                    v-for="output in selectedBlockData.outputs"
                    :key="output.name"
                    class="output-row"
                  >
                    <span class="output-label">{{ output.label }}</span>
                    <span class="output-display" :class="{ error: output.error }">
                      <template v-if="output.error">
                        <span class="error-text">{{ output.error }}</span>
                      </template>
                      <template v-else-if="output.value !== null">
                        <span class="output-value-num">{{ output.value.toFixed(3) }}</span>
                        <span class="output-unit">{{ output.unit }}</span>
                      </template>
                      <template v-else>
                        <span class="no-value">--</span>
                      </template>
                    </span>
                  </div>
                </div>
              </div>

              <!-- State (for debugging) -->
              <div v-if="Object.keys(selectedBlockData.state || {}).length > 0" class="form-section">
                <div class="section-header">INTERNAL STATE</div>
                <div class="state-display">
                  <div v-for="(value, key) in selectedBlockData.state" :key="key" class="state-row">
                    <span class="state-key">{{ key }}:</span>
                    <span class="state-value">{{ typeof value === 'number' ? value.toFixed(4) : JSON.stringify(value) }}</span>
                  </div>
                </div>
              </div>
            </div>

            <div class="editor-actions">
              <button class="btn btn-secondary" @click="closeBlockEditor">Close</button>
            </div>
          </template>
        </div>
      </div>
    </div>

    <!-- ===================================================================== -->
    <!-- SEQUENCES TAB -->
    <!-- ===================================================================== -->
    <div v-if="scripts.activeSubTab.value === 'sequences'" class="tab-content">
      <div class="toolbar">
        <button class="btn btn-primary" @click="createSequence">
          <span class="icon">+</span> New Sequence
        </button>
        <div class="sequence-controls" v-if="scripts.runningSequence.value">
          <span class="running-label">Running: {{ scripts.runningSequence.value.name }}</span>
          <button class="btn btn-warning" @click="scripts.pauseSequence(scripts.runningSequenceId.value!)">⏸ Pause</button>
          <button class="btn btn-danger" @click="scripts.abortSequence(scripts.runningSequenceId.value!)">⏹ Abort</button>
        </div>
        <div class="count">{{ scripts.sequences.value.length }} sequences</div>
      </div>

      <div class="main-content">
        <!-- List -->
        <div class="list-panel">
          <div class="list-header">TEST SEQUENCES</div>
          <div
            v-for="seq in scripts.sequences.value"
            :key="seq.id"
            class="list-item sequence-item"
            :class="{
              selected: selectedSequence === seq.id,
              running: seq.state === 'running',
              paused: seq.state === 'paused',
              error: seq.state === 'error'
            }"
            @click="editSequence(seq)"
          >
            <div class="item-info">
              <div class="item-name">
                {{ seq.name }}
                <span class="state-badge" :class="seq.state">{{ seq.state }}</span>
              </div>
              <div class="item-sub">{{ seq.steps.length }} steps • {{ seq.description || 'No description' }}</div>
            </div>
            <div class="item-actions">
              <button
                v-if="seq.state === 'idle'"
                class="action-btn play"
                @click.stop="scripts.startSequence(seq.id)"
                title="Run"
              >▶</button>
              <button
                v-else-if="seq.state === 'paused'"
                class="action-btn play"
                @click.stop="scripts.resumeSequence(seq.id)"
                title="Resume"
              >▶</button>
              <button
                v-else-if="seq.state === 'running'"
                class="action-btn pause"
                @click.stop="scripts.pauseSequence(seq.id)"
                title="Pause"
              >⏸</button>
              <button class="delete-btn" @click.stop="deleteSequence(seq.id)">✕</button>
            </div>
          </div>
          <div v-if="scripts.sequences.value.length === 0" class="empty-list">
            <p>No sequences</p>
            <p class="hint">Create test sequences with ramps, soaks, and loops</p>
          </div>
        </div>

        <!-- Sequence Editor -->
        <div class="editor-panel wide" :class="{ visible: showSequenceEditor }">
          <div class="editor-header">
            <h3>{{ selectedSequence ? 'Edit' : 'New' }} Sequence</h3>
            <button class="close-btn" @click="showSequenceEditor = false">✕</button>
          </div>
          <div class="editor-form">
            <div class="form-row">
              <div class="form-group">
                <label>Name</label>
                <input v-model="sequenceForm.name" type="text" placeholder="e.g., Thermal Cycle Test" />
              </div>
              <div class="form-group">
                <label>Description</label>
                <input v-model="sequenceForm.description" type="text" placeholder="e.g., 500°C 2hr soak with 10 cycles" />
              </div>
            </div>

            <div class="form-group">
              <label>Steps</label>
              <div class="steps-list">
                <div
                  v-for="(step, index) in sequenceForm.steps"
                  :key="step.id"
                  class="step-item"
                  :class="{ disabled: !step.enabled }"
                >
                  <div class="step-number">{{ index + 1 }}</div>
                  <div class="step-icon">{{ getStepIcon(step.type) }}</div>
                  <div class="step-info">
                    <div class="step-type">{{ step.type }}</div>
                    <div class="step-desc">{{ getStepDescription(step) }}</div>
                  </div>
                  <div class="step-actions">
                    <button class="step-btn" @click="moveStep(index, 'up')" :disabled="index === 0">↑</button>
                    <button class="step-btn" @click="moveStep(index, 'down')" :disabled="index === sequenceForm.steps!.length - 1">↓</button>
                    <button class="step-btn" @click="editStep(index)">✏️</button>
                    <button class="step-btn delete" @click="removeStep(index)">✕</button>
                  </div>
                </div>
                <div v-if="!sequenceForm.steps?.length" class="empty-steps">
                  No steps yet. Add steps below.
                </div>
              </div>
            </div>

            <div class="form-group">
              <label>Add Step</label>
              <div class="step-buttons">
                <button class="step-type-btn" @click="addStep('ramp')">📈 Ramp</button>
                <button class="step-type-btn" @click="addStep('soak')">⏸️ Soak</button>
                <button class="step-type-btn" @click="addStep('wait')">⏳ Wait</button>
                <button class="step-type-btn" @click="addStep('setOutput')">🎚️ Set Output</button>
                <button class="step-type-btn" @click="addStep('setVariable')">📝 Set Variable</button>
                <button class="step-type-btn" @click="addStep('loop')">🔄 Loop</button>
                <button class="step-type-btn" @click="addStep('endLoop')">↩️ End Loop</button>
                <button class="step-type-btn" @click="addStep('message')">💬 Message</button>
              </div>
            </div>
          </div>
          <div class="editor-actions">
            <button class="btn btn-secondary" @click="showSequenceEditor = false">Cancel</button>
            <button class="btn btn-primary" @click="saveSequence" :disabled="!sequenceForm.name">Save</button>
          </div>
        </div>
      </div>

      <!-- Step Editor Modal -->
      <div v-if="showStepEditor" class="modal-overlay" @click.self="showStepEditor = false">
        <div class="modal">
          <div class="modal-header">
            <h3>Edit Step: {{ stepForm.type }}</h3>
            <button class="close-btn" @click="showStepEditor = false">✕</button>
          </div>
          <div class="modal-body">
            <div class="form-group">
              <label>Label (optional)</label>
              <input v-model="stepForm.label" type="text" placeholder="Step description" />
            </div>
            <div class="form-group">
              <label>Enabled</label>
              <input type="checkbox" v-model="stepForm.enabled" />
            </div>

            <!-- Ramp Step Fields -->
            <template v-if="stepForm.type === 'ramp'">
              <div class="form-group">
                <label>Target Channel (Setpoint)</label>
                <select v-model="(stepForm as any).targetChannel">
                  <option value="">Select output...</option>
                  <option v-for="ch in outputChannels" :key="ch.name" :value="ch.name">{{ ch.displayName }}</option>
                </select>
              </div>
              <div class="form-group">
                <label>Monitor Channel</label>
                <select v-model="(stepForm as any).monitorChannel">
                  <option value="">Select input...</option>
                  <option v-for="ch in inputChannels" :key="ch.name" :value="ch.name">{{ ch.displayName }}</option>
                </select>
              </div>
              <div class="form-row">
                <div class="form-group">
                  <label>Target Value</label>
                  <input type="number" v-model.number="(stepForm as any).targetValue" />
                </div>
                <div class="form-group">
                  <label>Ramp Rate</label>
                  <input type="number" v-model.number="(stepForm as any).rampRate" />
                </div>
                <div class="form-group">
                  <label>Rate Unit</label>
                  <input type="text" v-model="(stepForm as any).rampRateUnit" placeholder="°C/min" />
                </div>
              </div>
              <div class="form-group">
                <label>Tolerance</label>
                <input type="number" v-model.number="(stepForm as any).tolerance" />
              </div>
            </template>

            <!-- Soak Step Fields -->
            <template v-if="stepForm.type === 'soak'">
              <div class="form-group">
                <label>Duration (seconds)</label>
                <input type="number" v-model.number="(stepForm as any).duration" min="1" />
              </div>
              <div class="form-group">
                <label>Monitor Channel (optional)</label>
                <select v-model="(stepForm as any).monitorChannel">
                  <option value="">None</option>
                  <option v-for="ch in inputChannels" :key="ch.name" :value="ch.name">{{ ch.displayName }}</option>
                </select>
              </div>
            </template>

            <!-- Wait Step Fields -->
            <template v-if="stepForm.type === 'wait'">
              <div class="form-group">
                <label>Condition (formula returning true/false)</label>
                <input type="text" v-model="(stepForm as any).condition" placeholder="ch.TC_Zone1 > 450" />
              </div>
              <div class="form-row">
                <div class="form-group">
                  <label>Timeout (seconds, 0=infinite)</label>
                  <input type="number" v-model.number="(stepForm as any).timeout" min="0" />
                </div>
                <div class="form-group">
                  <label>Timeout Action</label>
                  <select v-model="(stepForm as any).timeoutAction">
                    <option value="abort">Abort Sequence</option>
                    <option value="continue">Continue</option>
                    <option value="alarm">Alarm & Continue</option>
                  </select>
                </div>
              </div>
            </template>

            <!-- SetOutput Step Fields -->
            <template v-if="stepForm.type === 'setOutput'">
              <div class="form-group">
                <label>Output Channel</label>
                <select v-model="(stepForm as any).channel">
                  <option value="">Select output...</option>
                  <option v-for="ch in outputChannels" :key="ch.name" :value="ch.name">{{ ch.displayName }}</option>
                </select>
              </div>
              <div class="form-group">
                <label>Value</label>
                <input type="number" v-model.number="(stepForm as any).value" />
              </div>
            </template>

            <!-- Loop Step Fields -->
            <template v-if="stepForm.type === 'loop'">
              <div class="form-group">
                <label>Iterations (0 = infinite)</label>
                <input type="number" v-model.number="(stepForm as any).iterations" min="0" />
              </div>
            </template>

            <!-- End Loop Step Fields -->
            <template v-if="stepForm.type === 'endLoop'">
              <div class="form-group">
                <label>Loop ID</label>
                <select v-model="(stepForm as any).loopId">
                  <option value="">Select loop...</option>
                  <option
                    v-for="step in sequenceForm.steps?.filter(s => s.type === 'loop')"
                    :key="(step as any).loopId"
                    :value="(step as any).loopId"
                  >
                    {{ step.label || (step as any).loopId }}
                  </option>
                </select>
              </div>
            </template>

            <!-- Message Step Fields -->
            <template v-if="stepForm.type === 'message'">
              <div class="form-group">
                <label>Message</label>
                <input type="text" v-model="(stepForm as any).message" />
              </div>
              <div class="form-row">
                <div class="form-group">
                  <label>Severity</label>
                  <select v-model="(stepForm as any).severity">
                    <option value="info">Info</option>
                    <option value="warning">Warning</option>
                    <option value="error">Error</option>
                  </select>
                </div>
                <div class="form-group">
                  <label>Pause Execution</label>
                  <input type="checkbox" v-model="(stepForm as any).pauseExecution" />
                </div>
              </div>
            </template>

            <!-- SetVariable Step Fields -->
            <template v-if="stepForm.type === 'setVariable'">
              <div class="form-group">
                <label>Variable Name</label>
                <input
                  type="text"
                  v-model="(stepForm as any).variableName"
                  placeholder="myVariable"
                  pattern="[a-zA-Z_][a-zA-Z0-9_]*"
                />
                <small class="hint">Use letters, numbers, and underscores. Start with a letter.</small>
              </div>
              <div class="form-group">
                <label>
                  <input type="checkbox" v-model="(stepForm as any).isFormula" />
                  Use Formula
                </label>
              </div>
              <div class="form-group" v-if="!(stepForm as any).isFormula">
                <label>Value (constant)</label>
                <input type="number" v-model.number="(stepForm as any).value" step="any" />
              </div>
              <div class="form-group" v-else>
                <label>Formula</label>
                <input
                  type="text"
                  v-model="(stepForm as any).value"
                  placeholder="ch.Flow_Meter_1 * 0.5 + 10"
                />
                <small class="hint">
                  Use ch.ChannelName for channel values, seq.varName for other variables,
                  loop_ID for loop counters. Math: abs, sqrt, pow, sin, cos, min, max, PI, E
                </small>
              </div>
              <div class="info-box">
                <strong>Tip:</strong> Variables can be used in Wait conditions and other formulas
                as <code>seq.{{ (stepForm as any).variableName || 'varName' }}</code> or directly
                as <code>{{ (stepForm as any).variableName || 'varName' }}</code>
              </div>
            </template>
          </div>
          <div class="modal-footer">
            <button class="btn btn-secondary" @click="showStepEditor = false">Cancel</button>
            <button class="btn btn-primary" @click="saveStep">Save Step</button>
          </div>
        </div>
      </div>
    </div>

    <!-- ===================================================================== -->
    <!-- SCHEDULE TAB -->
    <!-- ===================================================================== -->
    <div v-if="scripts.activeSubTab.value === 'schedule'" class="tab-content">
      <div class="toolbar">
        <button class="btn btn-primary" @click="openScheduleEditor()">
          <span class="icon">+</span> New Schedule
        </button>
        <div class="schedule-summary" v-if="scripts.hasActiveSchedule.value">
          <span class="active-indicator">Schedule Active</span>
        </div>
        <div class="count">{{ scripts.schedules.value.length }} schedules</div>
      </div>

      <div class="schedule-list">
        <div
          v-for="schedule in scripts.schedules.value"
          :key="schedule.id"
          class="schedule-card"
          :class="{ disabled: !schedule.enabled, running: schedule.isRunning }"
        >
          <div class="schedule-header">
            <div class="schedule-info">
              <h4>{{ schedule.name }}</h4>
              <p class="description" v-if="schedule.description">{{ schedule.description }}</p>
            </div>
            <div class="schedule-controls">
              <button
                class="btn-icon"
                :class="{ active: schedule.enabled }"
                @click="scripts.updateSchedule(schedule.id, { enabled: !schedule.enabled })"
                title="Toggle enabled"
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <circle cx="12" cy="12" r="10"/>
                  <polyline v-if="schedule.enabled" points="9 12 11 14 15 10"/>
                </svg>
              </button>
              <button class="btn-icon" @click="openScheduleEditor(schedule)" title="Edit">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
                  <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
                </svg>
              </button>
              <button class="btn-icon delete" @click="scripts.deleteSchedule(schedule.id)" title="Delete">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
                </svg>
              </button>
            </div>
          </div>
          <div class="schedule-timing">
            <div class="time-info">
              <span class="label">Time:</span>
              <span class="value">{{ schedule.startTime }}{{ schedule.endTime ? ' - ' + schedule.endTime : '' }}</span>
            </div>
            <div class="repeat-info">
              <span class="label">Repeat:</span>
              <span class="value">
                {{ schedule.repeat === 'once' ? 'Once' : schedule.repeat === 'daily' ? 'Daily' : schedule.repeat === 'weekly' ? 'Weekly' : 'Monthly' }}
                <template v-if="schedule.repeat === 'weekly' && schedule.daysOfWeek">
                  ({{ schedule.daysOfWeek.map(d => dayNames[d]).join(', ') }})
                </template>
                <template v-if="schedule.repeat === 'monthly' && schedule.dayOfMonth">
                  (Day {{ schedule.dayOfMonth }})
                </template>
              </span>
            </div>
            <div class="next-run">
              <span class="label">Next Run:</span>
              <span class="value" :class="{ active: schedule.isRunning }">
                {{ schedule.isRunning ? 'Running now' : formatNextRun(schedule.nextRun) }}
              </span>
            </div>
          </div>
          <div class="schedule-actions">
            <div class="action-group">
              <span class="group-label">Start Actions:</span>
              <span class="action-count">{{ schedule.startActions?.length || 0 }} action(s)</span>
            </div>
            <div class="action-group" v-if="schedule.endActions?.length">
              <span class="group-label">End Actions:</span>
              <span class="action-count">{{ schedule.endActions.length }} action(s)</span>
            </div>
          </div>
        </div>

        <div v-if="!scripts.schedules.value.length" class="empty-state">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1">
            <circle cx="12" cy="12" r="10"/>
            <polyline points="12 6 12 12 16 14"/>
          </svg>
          <p>No schedules configured</p>
          <p class="hint">Create a schedule to automate sequences and recordings at specific times</p>
        </div>
      </div>

      <!-- Schedule Editor Modal -->
      <Transition name="modal">
        <div v-if="showScheduleEditor" class="modal-overlay" @click.self="closeScheduleEditor">
          <div class="modal schedule-editor-modal">
            <div class="modal-header">
              <h3>{{ selectedSchedule ? 'Edit Schedule' : 'New Schedule' }}</h3>
              <button class="close-btn" @click="closeScheduleEditor">&times;</button>
            </div>
            <div class="modal-body">
              <div class="form-row">
                <label>Name</label>
                <input type="text" v-model="scheduleForm.name" placeholder="Daily Recording" />
              </div>
              <div class="form-row">
                <label>Description</label>
                <input type="text" v-model="scheduleForm.description" placeholder="Optional description" />
              </div>
              <div class="form-row">
                <label>Start Time</label>
                <input type="time" v-model="scheduleForm.startTime" />
              </div>
              <div class="form-row">
                <label>End Time (optional)</label>
                <input type="time" v-model="scheduleForm.endTime" />
              </div>
              <div class="form-row">
                <label>Repeat</label>
                <select v-model="scheduleForm.repeat">
                  <option value="once">Once</option>
                  <option value="daily">Daily</option>
                  <option value="weekly">Weekly</option>
                  <option value="monthly">Monthly</option>
                </select>
              </div>
              <div v-if="scheduleForm.repeat === 'once'" class="form-row">
                <label>Date</label>
                <input type="date" v-model="scheduleForm.date" />
              </div>
              <div v-if="scheduleForm.repeat === 'weekly'" class="form-row">
                <label>Days of Week</label>
                <div class="day-picker">
                  <button
                    v-for="(name, idx) in dayNames"
                    :key="idx"
                    class="day-btn"
                    :class="{ selected: scheduleForm.daysOfWeek.includes(idx) }"
                    @click="toggleDayOfWeek(idx)"
                  >
                    {{ name }}
                  </button>
                </div>
              </div>
              <div v-if="scheduleForm.repeat === 'monthly'" class="form-row">
                <label>Day of Month</label>
                <input type="number" v-model="scheduleForm.dayOfMonth" min="1" max="31" />
              </div>
              <div class="form-row">
                <label class="checkbox-label">
                  <input type="checkbox" v-model="scheduleForm.enabled" />
                  Enabled
                </label>
              </div>
            </div>
            <div class="modal-footer">
              <button class="btn btn-secondary" @click="closeScheduleEditor">Cancel</button>
              <button class="btn btn-primary" @click="saveSchedule" :disabled="!scheduleForm.name">Save</button>
            </div>
          </div>
        </div>
      </Transition>
    </div>

    <!-- ===================================================================== -->
    <!-- ALARMS TAB -->
    <!-- ===================================================================== -->
    <div v-if="scripts.activeSubTab.value === 'alarms'" class="tab-content">
      <div class="toolbar">
        <button class="btn btn-primary" @click="createAlarm">
          <span class="icon">+</span> New Alarm
        </button>
        <div class="alarm-summary" v-if="scripts.activeAlarms.value.length">
          <span class="active-alarms">{{ scripts.activeAlarms.value.length }} Active Alarms</span>
        </div>
        <div class="count">{{ scripts.alarms.value.length }} alarms</div>
      </div>

      <div class="main-content">
        <!-- Active Alarms Banner -->
        <div v-if="scripts.activeAlarms.value.length" class="active-alarms-banner">
          <div
            v-for="alarm in scripts.activeAlarms.value"
            :key="alarm.id"
            class="active-alarm"
            :class="alarm.severity"
          >
            <span class="alarm-icon">🔔</span>
            <span class="alarm-name">{{ alarm.name }}</span>
            <span class="alarm-time">{{ new Date(alarm.triggeredAt!).toLocaleTimeString() }}</span>
            <button class="ack-btn" @click="scripts.acknowledgeAlarm(alarm.id)">Acknowledge</button>
          </div>
        </div>

        <!-- List -->
        <div class="list-panel">
          <div class="list-header">ALARM RULES</div>
          <div
            v-for="alarm in scripts.alarms.value"
            :key="alarm.id"
            class="list-item alarm-item"
            :class="{
              selected: selectedAlarm === alarm.id,
              active: alarm.state === 'active',
              warning: alarm.severity === 'warning',
              critical: alarm.severity === 'critical'
            }"
            @click="editAlarm(alarm)"
          >
            <div class="severity-indicator" :class="alarm.severity"></div>
            <div class="item-info">
              <div class="item-name">
                {{ alarm.name }}
                <span v-if="alarm.state !== 'normal'" class="state-badge" :class="alarm.state">{{ alarm.state }}</span>
              </div>
              <div class="item-sub">
                {{ alarm.conditions.length }} condition(s) • {{ alarm.actions.length }} action(s)
              </div>
            </div>
            <div class="item-actions">
              <button
                class="toggle-btn"
                :class="{ on: alarm.enabled }"
                @click.stop="scripts.updateAlarm(alarm.id, { enabled: !alarm.enabled })"
              >
                <span class="slider"></span>
              </button>
              <button class="delete-btn" @click.stop="deleteAlarm(alarm.id)">✕</button>
            </div>
          </div>
          <div v-if="scripts.alarms.value.length === 0" class="empty-list">
            <p>No alarms configured</p>
            <p class="hint">Create alarms to monitor conditions and trigger actions</p>
          </div>
        </div>

        <!-- Alarm Editor -->
        <div class="editor-panel wide" :class="{ visible: showAlarmEditor }">
          <div class="editor-header">
            <h3>{{ selectedAlarm ? 'Edit' : 'New' }} Alarm</h3>
            <button class="close-btn" @click="showAlarmEditor = false">✕</button>
          </div>
          <div class="editor-form">
            <div class="form-row">
              <div class="form-group">
                <label>Name</label>
                <input v-model="alarmForm.name" type="text" placeholder="e.g., High Temperature" />
              </div>
              <div class="form-group">
                <label>Severity</label>
                <select v-model="alarmForm.severity">
                  <option value="info">Info</option>
                  <option value="warning">Warning</option>
                  <option value="critical">Critical</option>
                </select>
              </div>
            </div>
            <div class="form-group">
              <label>Description</label>
              <input v-model="alarmForm.description" type="text" placeholder="Alarm description" />
            </div>

            <div class="form-group">
              <label>Conditions ({{ alarmForm.conditionLogic }})</label>
              <div class="conditions-list">
                <div v-for="(cond, index) in alarmForm.conditions" :key="index" class="condition-row">
                  <select v-model="cond.channel" class="channel-select">
                    <option value="">Select channel...</option>
                    <option v-for="ch in channelVariables" :key="ch.name" :value="ch.name">{{ ch.displayName }}</option>
                  </select>
                  <select v-model="cond.operator" class="operator-select">
                    <option value=">">></option>
                    <option value="<"><</option>
                    <option value=">=">>=</option>
                    <option value="<="><=</option>
                    <option value="==">=</option>
                    <option value="!=">!=</option>
                    <option value="roc>">Rate > (°/min)</option>
                    <option value="roc<">Rate < (°/min)</option>
                  </select>
                  <input type="number" v-model.number="cond.value" class="value-input" />
                  <button class="remove-btn" @click="removeCondition(index)">✕</button>
                </div>
                <button class="btn btn-small" @click="addCondition">+ Add Condition</button>
              </div>
              <div class="form-row" style="margin-top: 8px;">
                <label>
                  <input type="radio" v-model="alarmForm.conditionLogic" value="AND" /> All conditions (AND)
                </label>
                <label>
                  <input type="radio" v-model="alarmForm.conditionLogic" value="OR" /> Any condition (OR)
                </label>
              </div>
            </div>

            <div class="form-group">
              <label>Actions</label>
              <div class="actions-list">
                <div v-for="(action, index) in alarmForm.actions" :key="index" class="action-row">
                  <select v-model="action.type" class="action-type-select">
                    <option value="notification">Notification</option>
                    <option value="setOutput">Set Output</option>
                    <option value="abortSequence">Abort Sequence</option>
                    <option value="runSequence">Run Sequence</option>
                    <option value="sound">Play Sound</option>
                    <option value="log">Log Event</option>
                  </select>
                  <template v-if="action.type === 'notification'">
                    <input type="text" v-model="action.message" placeholder="Message" class="flex-input" />
                  </template>
                  <template v-if="action.type === 'setOutput'">
                    <select v-model="action.channel" class="channel-select">
                      <option value="">Select output...</option>
                      <option v-for="ch in outputChannels" :key="ch.name" :value="ch.name">{{ ch.displayName }}</option>
                    </select>
                    <input type="number" v-model.number="action.value" class="value-input" />
                  </template>
                  <template v-if="action.type === 'runSequence'">
                    <select v-model="action.sequenceId" class="flex-input">
                      <option value="">Select sequence...</option>
                      <option v-for="seq in scripts.sequences.value" :key="seq.id" :value="seq.id">{{ seq.name }}</option>
                    </select>
                  </template>
                  <button class="remove-btn" @click="removeAction(index)">✕</button>
                </div>
                <button class="btn btn-small" @click="addAction">+ Add Action</button>
              </div>
            </div>

            <div class="form-row">
              <div class="form-group">
                <label>Debounce (ms)</label>
                <input type="number" v-model.number="alarmForm.debounceMs" min="0" />
              </div>
              <div class="form-group">
                <label>Auto-Reset (ms, 0=manual)</label>
                <input type="number" v-model.number="alarmForm.autoResetMs" min="0" />
              </div>
            </div>
          </div>
          <div class="editor-actions">
            <button class="btn btn-secondary" @click="showAlarmEditor = false">Cancel</button>
            <button class="btn btn-primary" @click="saveAlarm" :disabled="!alarmForm.name">Save</button>
          </div>
        </div>
      </div>
    </div>

    <!-- ===================================================================== -->
    <!-- TRANSFORMATIONS TAB -->
    <!-- ===================================================================== -->
    <div v-if="scripts.activeSubTab.value === 'transformations'" class="tab-content">
      <div class="toolbar">
        <button class="btn btn-primary" @click="createTransform">
          <span class="icon">+</span> New Transformation
        </button>
        <div class="count">{{ scripts.transformations.value.length }} transforms</div>
      </div>

      <div class="main-content">
        <!-- List -->
        <div class="list-panel">
          <div class="list-header">DATA TRANSFORMATIONS</div>
          <div
            v-for="transform in scripts.transformations.value"
            :key="transform.id"
            class="list-item"
            :class="{ selected: selectedTransform === transform.id, disabled: !transform.enabled }"
            @click="editTransform(transform)"
          >
            <div class="item-info">
              <div class="item-name">{{ transform.displayName || transform.name }}</div>
              <div class="item-sub">{{ transform.type }} • {{ transform.inputChannel }}</div>
            </div>
            <div class="item-value" :class="{ error: transform.lastError }">
              <span v-if="transform.lastError" class="error-icon" :title="transform.lastError">⚠</span>
              <span v-else-if="transform.lastValue !== null">
                {{ transform.lastValue.toFixed(3) }}
                <span class="unit">{{ transform.outputUnit }}</span>
              </span>
              <span v-else class="no-value">--</span>
            </div>
            <div class="item-actions">
              <button
                class="toggle-btn"
                :class="{ on: transform.enabled }"
                @click.stop="scripts.updateTransformation(transform.id, { enabled: !transform.enabled })"
              >
                <span class="slider"></span>
              </button>
              <button class="delete-btn" @click.stop="deleteTransform(transform.id)">✕</button>
            </div>
          </div>
          <div v-if="scripts.transformations.value.length === 0" class="empty-list">
            <p>No transformations</p>
            <p class="hint">Create transformations like rolling averages, filters, or unit conversions</p>
          </div>
        </div>

        <!-- Transform Editor -->
        <div class="editor-panel" :class="{ visible: showTransformEditor }">
          <div class="editor-header">
            <h3>{{ selectedTransform ? 'Edit' : 'New' }} Transformation</h3>
            <button class="close-btn" @click="showTransformEditor = false">✕</button>
          </div>
          <div class="editor-form">
            <div class="form-group">
              <label>Name</label>
              <input v-model="transformForm.name" type="text" placeholder="e.g., tc1_avg" />
            </div>
            <div class="form-group">
              <label>Display Name</label>
              <input v-model="transformForm.displayName" type="text" placeholder="e.g., TC1 Rolling Average" />
            </div>
            <div class="form-group">
              <label>Type</label>
              <select v-model="transformForm.type">
                <optgroup label="Rolling Statistics">
                  <option value="rollingAverage">Rolling Average</option>
                  <option value="rollingMin">Rolling Minimum</option>
                  <option value="rollingMax">Rolling Maximum</option>
                  <option value="rollingStdDev">Rolling Std Dev</option>
                </optgroup>
                <optgroup label="Rate">
                  <option value="rateOfChange">Rate of Change</option>
                </optgroup>
                <optgroup label="Conversion">
                  <option value="unitConversion">Unit Conversion</option>
                  <option value="polynomial">Polynomial</option>
                </optgroup>
                <optgroup label="Signal Processing">
                  <option value="lowPassFilter">Low Pass Filter</option>
                  <option value="highPassFilter">High Pass Filter</option>
                  <option value="deadband">Deadband</option>
                  <option value="clamp">Clamp</option>
                </optgroup>
              </select>
            </div>
            <div class="form-group">
              <label>Input Channel</label>
              <select v-model="transformForm.inputChannel">
                <option value="">Select channel...</option>
                <option v-for="ch in channelVariables" :key="ch.name" :value="ch.name">{{ ch.displayName }}</option>
              </select>
            </div>
            <div class="form-group">
              <label>Output Unit</label>
              <input v-model="transformForm.outputUnit" type="text" placeholder="e.g., °C" />
            </div>

            <!-- Rolling specific -->
            <template v-if="['rollingAverage', 'rollingMin', 'rollingMax', 'rollingStdDev'].includes(transformForm.type!)">
              <div class="form-group">
                <label>Window Size (samples)</label>
                <input type="number" v-model.number="(transformForm as any).windowSize" min="2" />
              </div>
            </template>

            <!-- Rate of Change specific -->
            <template v-if="transformForm.type === 'rateOfChange'">
              <div class="form-group">
                <label>Time Window (ms)</label>
                <input type="number" v-model.number="(transformForm as any).timeWindowMs" min="100" />
              </div>
              <div class="form-group">
                <label>Rate Unit</label>
                <input type="text" v-model="(transformForm as any).rateUnit" placeholder="°C/min" />
              </div>
            </template>

            <!-- Unit Conversion specific -->
            <template v-if="transformForm.type === 'unitConversion'">
              <div class="form-group">
                <label>Conversion Type</label>
                <select v-model="(transformForm as any).conversionType">
                  <option value="celsius_to_fahrenheit">°C to °F</option>
                  <option value="fahrenheit_to_celsius">°F to °C</option>
                  <option value="psi_to_bar">PSI to Bar</option>
                  <option value="bar_to_psi">Bar to PSI</option>
                  <option value="lpm_to_gpm">L/min to GPM</option>
                  <option value="gpm_to_lpm">GPM to L/min</option>
                  <option value="custom">Custom</option>
                </select>
              </div>
              <template v-if="(transformForm as any).conversionType === 'custom'">
                <div class="form-row">
                  <div class="form-group">
                    <label>Multiplier</label>
                    <input type="number" v-model.number="(transformForm as any).multiplier" step="0.001" />
                  </div>
                  <div class="form-group">
                    <label>Offset</label>
                    <input type="number" v-model.number="(transformForm as any).offset" step="0.001" />
                  </div>
                </div>
              </template>
            </template>

            <!-- Polynomial specific -->
            <template v-if="transformForm.type === 'polynomial'">
              <div class="form-group">
                <label>Coefficients (c0 + c1*x + c2*x² + ...)</label>
                <input
                  type="text"
                  :value="((transformForm as any).coefficients || []).join(', ')"
                  @input="(transformForm as any).coefficients = ($event.target as HTMLInputElement).value.split(',').map(s => parseFloat(s.trim()) || 0)"
                  placeholder="0, 1, 0.5"
                />
              </div>
            </template>

            <!-- Deadband specific -->
            <template v-if="transformForm.type === 'deadband'">
              <div class="form-group">
                <label>Deadband Value</label>
                <input type="number" v-model.number="(transformForm as any).deadband" step="0.1" />
              </div>
            </template>

            <!-- Clamp specific -->
            <template v-if="transformForm.type === 'clamp'">
              <div class="form-row">
                <div class="form-group">
                  <label>Min Value</label>
                  <input type="number" v-model.number="(transformForm as any).minValue" />
                </div>
                <div class="form-group">
                  <label>Max Value</label>
                  <input type="number" v-model.number="(transformForm as any).maxValue" />
                </div>
              </div>
            </template>
          </div>
          <div class="editor-actions">
            <button class="btn btn-secondary" @click="showTransformEditor = false">Cancel</button>
            <button class="btn btn-primary" @click="saveTransform" :disabled="!transformForm.name || !transformForm.inputChannel">Save</button>
          </div>
        </div>
      </div>
    </div>

    <!-- ===================================================================== -->
    <!-- TRIGGERS TAB -->
    <!-- ===================================================================== -->
    <div v-if="scripts.activeSubTab.value === 'triggers'" class="tab-content">
      <div class="toolbar">
        <button class="btn btn-primary" @click="createTrigger">
          <span class="icon">+</span> New Trigger
        </button>
        <div class="count">{{ scripts.triggers.value.length }} triggers</div>
      </div>

      <div class="main-content">
        <!-- List -->
        <div class="list-panel">
          <div class="list-header">AUTOMATION TRIGGERS</div>
          <div
            v-for="trigger in scripts.triggers.value"
            :key="trigger.id"
            class="list-item"
            :class="{ selected: selectedTrigger === trigger.id, disabled: !trigger.enabled }"
            @click="editTrigger(trigger)"
          >
            <div class="item-info">
              <div class="item-name">{{ trigger.name }}</div>
              <div class="item-sub">
                {{ trigger.trigger.type }} • {{ trigger.actions.length }} action(s)
                <span v-if="trigger.oneShot" class="one-shot-badge">One-shot</span>
              </div>
            </div>
            <div class="item-actions">
              <button
                class="toggle-btn"
                :class="{ on: trigger.enabled }"
                @click.stop="scripts.updateTrigger(trigger.id, { enabled: !trigger.enabled })"
              >
                <span class="slider"></span>
              </button>
              <button class="delete-btn" @click.stop="deleteTrigger(trigger.id)">✕</button>
            </div>
          </div>
          <div v-if="scripts.triggers.value.length === 0" class="empty-list">
            <p>No triggers</p>
            <p class="hint">Create triggers to automate actions based on conditions</p>
          </div>
        </div>

        <!-- Trigger Editor -->
        <div class="editor-panel wide" :class="{ visible: showTriggerEditor }">
          <div class="editor-header">
            <h3>{{ selectedTrigger ? 'Edit' : 'New' }} Trigger</h3>
            <button class="close-btn" @click="showTriggerEditor = false">✕</button>
          </div>
          <div class="editor-form">
            <div class="form-group">
              <label>Name</label>
              <input v-model="triggerForm.name" type="text" placeholder="e.g., Start recording on temp" />
            </div>
            <div class="form-group">
              <label>Description</label>
              <input v-model="triggerForm.description" type="text" />
            </div>
            <div class="form-row">
              <div class="form-group">
                <label>One-shot (disable after trigger)</label>
                <input type="checkbox" v-model="triggerForm.oneShot" />
              </div>
              <div class="form-group">
                <label>Cooldown (ms)</label>
                <input type="number" v-model.number="triggerForm.cooldownMs" min="0" />
              </div>
            </div>

            <div class="form-group">
              <label>Trigger Type</label>
              <select v-model="(triggerForm.trigger as any).type">
                <option value="valueReached">Value Reached</option>
                <option value="scheduled">Scheduled</option>
                <option value="stateChange">State Change</option>
                <option value="sequenceEvent">Sequence Event</option>
              </select>
            </div>

            <!-- Value Reached Trigger -->
            <template v-if="(triggerForm.trigger as any)?.type === 'valueReached'">
              <div class="form-row">
                <div class="form-group">
                  <label>Channel</label>
                  <select v-model="(triggerForm.trigger as any).channel">
                    <option value="">Select channel...</option>
                    <option v-for="ch in channelVariables" :key="ch.name" :value="ch.name">{{ ch.displayName }}</option>
                  </select>
                </div>
                <div class="form-group">
                  <label>Operator</label>
                  <select v-model="(triggerForm.trigger as any).operator">
                    <option value=">">></option>
                    <option value="<"><</option>
                    <option value=">=">>=</option>
                    <option value="<="><=</option>
                    <option value="==">=</option>
                    <option value="!=">!=</option>
                  </select>
                </div>
                <div class="form-group">
                  <label>Value</label>
                  <input type="number" v-model.number="(triggerForm.trigger as any).value" />
                </div>
              </div>
            </template>

            <div class="form-group">
              <label>Actions</label>
              <div class="actions-list">
                <div v-for="(action, index) in triggerForm.actions" :key="index" class="action-row">
                  <select v-model="action.type" class="action-type-select">
                    <option value="startSequence">Start Sequence</option>
                    <option value="stopSequence">Stop Sequence</option>
                    <option value="setOutput">Set Output</option>
                    <option value="startRecording">Start Recording</option>
                    <option value="stopRecording">Stop Recording</option>
                    <option value="notification">Notification</option>
                  </select>
                  <template v-if="action.type === 'startSequence'">
                    <select v-model="action.sequenceId" class="flex-input">
                      <option value="">Select sequence...</option>
                      <option v-for="seq in scripts.sequences.value" :key="seq.id" :value="seq.id">{{ seq.name }}</option>
                    </select>
                  </template>
                  <template v-if="action.type === 'setOutput'">
                    <select v-model="action.channel" class="channel-select">
                      <option value="">Select output...</option>
                      <option v-for="ch in outputChannels" :key="ch.name" :value="ch.name">{{ ch.displayName }}</option>
                    </select>
                    <input type="number" v-model.number="action.value" class="value-input" />
                  </template>
                  <template v-if="action.type === 'notification'">
                    <input type="text" v-model="action.message" placeholder="Message" class="flex-input" />
                  </template>
                  <button class="remove-btn" @click="removeTriggerAction(index)">✕</button>
                </div>
                <button class="btn btn-small" @click="addTriggerAction">+ Add Action</button>
              </div>
            </div>
          </div>
          <div class="editor-actions">
            <button class="btn btn-secondary" @click="showTriggerEditor = false">Cancel</button>
            <button class="btn btn-primary" @click="saveTrigger" :disabled="!triggerForm.name">Save</button>
          </div>
        </div>
      </div>
    </div>

    <!-- ===================================================================== -->
    <!-- TEMPLATES TAB -->
    <!-- ===================================================================== -->
    <div v-if="scripts.activeSubTab.value === 'templates'" class="tab-content">
      <div class="toolbar">
        <div class="template-intro">Select a template to quickly create a calculated parameter</div>
      </div>

      <div class="main-content templates-layout">
        <!-- Template Categories -->
        <div class="templates-list">
          <div v-for="(categoryTemplates, category) in templateCategories" :key="category" class="template-category">
            <div class="category-header">{{ category.toUpperCase() }}</div>
            <div
              v-for="template in categoryTemplates"
              :key="template.id"
              class="template-item"
              :class="{ selected: selectedTemplate?.id === template.id }"
              @click="selectTemplate(template)"
            >
              <div class="template-name">{{ template.name }}</div>
              <div class="template-desc">{{ template.description }}</div>
            </div>
          </div>
        </div>

        <!-- Template Configuration -->
        <div class="template-config" :class="{ visible: selectedTemplate }">
          <template v-if="selectedTemplate">
            <div class="config-header">
              <h3>{{ selectedTemplate.name }}</h3>
              <p>{{ selectedTemplate.description }}</p>
            </div>
            <div class="config-form">
              <div v-for="param in selectedTemplate.parameters" :key="param.name" class="form-group">
                <label>{{ param.label }}</label>
                <template v-if="param.type === 'channel'">
                  <select v-model="templateParams[param.name]">
                    <option value="">Select channel...</option>
                    <option v-for="ch in channelVariables" :key="ch.name" :value="ch.name">{{ ch.displayName }}</option>
                  </select>
                </template>
                <template v-else-if="param.type === 'number'">
                  <input type="number" v-model.number="templateParams[param.name]" :placeholder="param.placeholder" />
                </template>
                <template v-else-if="param.type === 'select' && param.options">
                  <select v-model="templateParams[param.name]">
                    <option v-for="opt in param.options" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
                  </select>
                </template>
              </div>
              <div class="form-group">
                <label>Preview Formula</label>
                <code class="formula-preview">{{ selectedTemplate.formula }}</code>
              </div>
            </div>
            <div class="config-actions">
              <button class="btn btn-secondary" @click="selectedTemplate = null">Cancel</button>
              <button class="btn btn-primary" @click="applyTemplate">Create Formula</button>
            </div>
          </template>
          <div v-else class="no-selection">
            <p>Select a template from the left to configure it</p>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* Base Layout */
.scripts-tab {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #0a0a14;
}

/* Sub-tab Navigation */
.sub-tabs {
  display: flex;
  gap: 2px;
  padding: 8px 12px;
  background: #0f0f1a;
  border-bottom: 1px solid #2a2a4a;
}

.sub-tab {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 14px;
  background: transparent;
  border: none;
  border-radius: 6px;
  color: #888;
  font-size: 0.8rem;
  cursor: pointer;
  transition: all 0.2s;
}

.sub-tab:hover {
  background: #1a1a2e;
  color: #fff;
}

.sub-tab.active {
  background: #1e3a5f;
  color: #fff;
}

.tab-icon {
  font-size: 0.9rem;
}

.badge {
  padding: 2px 6px;
  border-radius: 10px;
  font-size: 0.65rem;
  font-weight: 600;
}

.badge.alarm {
  background: #ef4444;
  color: #fff;
}

.badge.running {
  color: #22c55e;
  animation: pulse 1s infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

/* Tab Content */
.tab-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* Toolbar */
.toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  background: #0f0f1a;
  border-bottom: 1px solid #2a2a4a;
}

.count {
  margin-left: auto;
  font-size: 0.75rem;
  color: #666;
}

/* Buttons */
.btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 14px;
  border: none;
  border-radius: 4px;
  font-size: 0.8rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-primary {
  background: #3b82f6;
  color: #fff;
}

.btn-primary:hover {
  background: #2563eb;
}

.btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-secondary {
  background: #374151;
  color: #fff;
}

.btn-secondary:hover {
  background: #4b5563;
}

.btn-warning {
  background: #f59e0b;
  color: #000;
}

.btn-danger {
  background: #ef4444;
  color: #fff;
}

.btn-small {
  padding: 4px 10px;
  font-size: 0.75rem;
}

.icon {
  font-size: 1rem;
}

/* Main Content Layout */
.main-content {
  display: flex;
  flex: 1;
  overflow: hidden;
}

/* List Panel */
.list-panel {
  width: 400px;
  border-right: 1px solid #2a2a4a;
  overflow-y: auto;
}

.list-header {
  padding: 10px 16px;
  font-size: 0.7rem;
  font-weight: 600;
  color: #666;
  background: #0f0f1a;
  border-bottom: 1px solid #2a2a4a;
  position: sticky;
  top: 0;
}

.list-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  border-bottom: 1px solid #1a1a2e;
  cursor: pointer;
  transition: background 0.2s;
}

.list-item:hover {
  background: #1a1a2e;
}

.list-item.selected {
  background: #1e3a5f;
}

.list-item.disabled {
  opacity: 0.5;
}

.item-info {
  flex: 1;
  min-width: 0;
}

.item-name {
  font-size: 0.85rem;
  font-weight: 500;
  color: #fff;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.item-sub {
  font-size: 0.7rem;
  color: #666;
  font-family: 'JetBrains Mono', monospace;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.item-value {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.85rem;
  color: #22c55e;
  white-space: nowrap;
}

.item-value.error {
  color: #ef4444;
}

.item-value .unit {
  font-size: 0.7rem;
  color: #666;
  margin-left: 2px;
}

.item-value .no-value {
  color: #555;
}

.error-icon {
  color: #ef4444;
}

.item-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}

/* Toggle Button */
.toggle-btn {
  position: relative;
  width: 32px;
  height: 16px;
  background: #4b5563;
  border-radius: 8px;
  border: none;
  cursor: pointer;
  padding: 2px;
  transition: background 0.2s;
}

.toggle-btn.on {
  background: #22c55e;
}

.toggle-btn .slider {
  position: absolute;
  top: 2px;
  left: 2px;
  width: 12px;
  height: 12px;
  background: white;
  border-radius: 50%;
  transition: transform 0.2s;
}

.toggle-btn.on .slider {
  transform: translateX(16px);
}

.delete-btn {
  background: transparent;
  border: none;
  color: #666;
  cursor: pointer;
  padding: 4px;
  border-radius: 4px;
  font-size: 0.8rem;
}

.delete-btn:hover {
  background: #7f1d1d;
  color: #fca5a5;
}

.empty-list {
  padding: 40px 20px;
  text-align: center;
  color: #555;
}

.empty-list .hint {
  font-size: 0.75rem;
  margin-top: 8px;
}

/* Editor Panel */
.editor-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  background: #0f0f1a;
  opacity: 0.3;
  pointer-events: none;
  transition: opacity 0.2s;
  overflow: hidden;
}

.editor-panel.visible {
  opacity: 1;
  pointer-events: auto;
}

.editor-panel.wide {
  min-width: 500px;
}

.editor-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid #2a2a4a;
}

.editor-header h3 {
  margin: 0;
  font-size: 0.9rem;
  color: #fff;
}

.close-btn {
  background: transparent;
  border: none;
  color: #666;
  cursor: pointer;
  padding: 4px;
  font-size: 1rem;
}

.close-btn:hover {
  color: #fff;
}

.editor-form {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
}

.form-group {
  margin-bottom: 16px;
}

.form-group label {
  display: block;
  font-size: 0.75rem;
  color: #888;
  margin-bottom: 6px;
  text-transform: uppercase;
}

.form-group input[type="text"],
.form-group input[type="number"],
.form-group textarea,
.form-group select {
  width: 100%;
  padding: 8px 12px;
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 4px;
  color: #fff;
  font-size: 0.85rem;
  font-family: inherit;
}

.form-group input[type="checkbox"] {
  width: auto;
}

.form-group textarea {
  font-family: 'JetBrains Mono', monospace;
  resize: vertical;
}

.form-group input:focus,
.form-group textarea:focus,
.form-group select:focus {
  outline: none;
  border-color: #3b82f6;
}

.form-row {
  display: flex;
  gap: 12px;
}

.form-row .form-group {
  flex: 1;
}

.formula-help {
  margin-top: 6px;
  font-size: 0.7rem;
  color: #555;
}

.formula-help code {
  background: #1a1a2e;
  padding: 1px 4px;
  border-radius: 2px;
  color: #60a5fa;
}

.channel-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  max-height: 120px;
  overflow-y: auto;
}

.channel-chip {
  padding: 4px 8px;
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 4px;
  color: #888;
  font-size: 0.7rem;
  font-family: 'JetBrains Mono', monospace;
  cursor: pointer;
}

.channel-chip:hover {
  background: #2a2a4a;
  color: #fff;
  border-color: #3b82f6;
}

.preview-value {
  padding: 12px;
  background: #1a1a2e;
  border-radius: 4px;
  font-family: 'JetBrains Mono', monospace;
}

.preview-value .value {
  font-size: 1.2rem;
  font-weight: 600;
  color: #22c55e;
}

.preview-value .unit {
  font-size: 0.85rem;
  color: #666;
  margin-left: 4px;
}

.preview-value .error {
  color: #ef4444;
  font-size: 0.85rem;
}

.editor-actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
  padding: 12px 16px;
  border-top: 1px solid #2a2a4a;
}

/* State Badges */
.state-badge {
  display: inline-block;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 0.65rem;
  font-weight: 600;
  text-transform: uppercase;
  margin-left: 8px;
}

.state-badge.idle { background: #374151; color: #9ca3af; }
.state-badge.running { background: #166534; color: #22c55e; }
.state-badge.paused { background: #78350f; color: #fbbf24; }
.state-badge.completed { background: #1e3a5f; color: #60a5fa; }
.state-badge.aborted { background: #7f1d1d; color: #fca5a5; }
.state-badge.error { background: #7f1d1d; color: #ef4444; }
.state-badge.active { background: #7f1d1d; color: #ef4444; animation: pulse 1s infinite; }
.state-badge.acknowledged { background: #78350f; color: #fbbf24; }

/* Sequence specific */
.sequence-controls {
  display: flex;
  align-items: center;
  gap: 8px;
}

.running-label {
  font-size: 0.8rem;
  color: #22c55e;
}

.steps-list {
  background: #0a0a14;
  border: 1px solid #2a2a4a;
  border-radius: 4px;
  max-height: 300px;
  overflow-y: auto;
}

.step-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border-bottom: 1px solid #1a1a2e;
}

.step-item.disabled {
  opacity: 0.5;
}

.step-number {
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #1e3a5f;
  border-radius: 50%;
  font-size: 0.7rem;
  font-weight: 600;
  color: #60a5fa;
}

.step-icon {
  font-size: 1rem;
}

.step-info {
  flex: 1;
  min-width: 0;
}

.step-type {
  font-size: 0.75rem;
  color: #888;
  text-transform: uppercase;
}

.step-desc {
  font-size: 0.8rem;
  color: #fff;
}

.step-actions {
  display: flex;
  gap: 4px;
}

.step-btn {
  padding: 4px 8px;
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 4px;
  color: #888;
  font-size: 0.75rem;
  cursor: pointer;
}

.step-btn:hover {
  background: #2a2a4a;
  color: #fff;
}

.step-btn.delete:hover {
  background: #7f1d1d;
  color: #fca5a5;
}

.step-btn:disabled {
  opacity: 0.3;
  cursor: not-allowed;
}

.empty-steps {
  padding: 20px;
  text-align: center;
  color: #555;
  font-size: 0.8rem;
}

.step-buttons {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.step-type-btn {
  padding: 8px 12px;
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 4px;
  color: #fff;
  font-size: 0.8rem;
  cursor: pointer;
}

.step-type-btn:hover {
  background: #2a2a4a;
  border-color: #3b82f6;
}

/* Alarm specific */
.severity-indicator {
  width: 4px;
  height: 40px;
  border-radius: 2px;
}

.severity-indicator.info { background: #3b82f6; }
.severity-indicator.warning { background: #f59e0b; }
.severity-indicator.critical { background: #ef4444; }

.active-alarms-banner {
  background: #1a0a0a;
  border-bottom: 1px solid #7f1d1d;
  padding: 8px 16px;
}

.active-alarm {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 12px;
  background: #2a0a0a;
  border-radius: 4px;
  margin-bottom: 4px;
}

.active-alarm.warning {
  background: #2a1a0a;
}

.active-alarm.critical {
  background: #3a0a0a;
}

.alarm-icon {
  font-size: 1rem;
}

.alarm-name {
  flex: 1;
  font-weight: 500;
  color: #fff;
}

.alarm-time {
  font-size: 0.75rem;
  color: #888;
}

.ack-btn {
  padding: 4px 10px;
  background: #374151;
  border: none;
  border-radius: 4px;
  color: #fff;
  font-size: 0.75rem;
  cursor: pointer;
}

.ack-btn:hover {
  background: #4b5563;
}

.conditions-list,
.actions-list {
  background: #0a0a14;
  border: 1px solid #2a2a4a;
  border-radius: 4px;
  padding: 8px;
}

.condition-row,
.action-row {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-bottom: 8px;
}

.channel-select {
  width: 150px;
}

.operator-select {
  width: 80px;
}

.value-input {
  width: 80px;
}

.action-type-select {
  width: 140px;
}

.flex-input {
  flex: 1;
}

.remove-btn {
  padding: 4px 8px;
  background: #7f1d1d;
  border: none;
  border-radius: 4px;
  color: #fca5a5;
  cursor: pointer;
}

.remove-btn:hover {
  background: #991b1b;
}

/* One-shot badge */
.one-shot-badge {
  display: inline-block;
  padding: 1px 4px;
  background: #4c1d95;
  color: #c4b5fd;
  border-radius: 2px;
  font-size: 0.6rem;
  margin-left: 6px;
}

/* Modal */
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.7);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.modal {
  background: #0f0f1a;
  border: 1px solid #2a2a4a;
  border-radius: 8px;
  width: 500px;
  max-width: 90vw;
  max-height: 80vh;
  display: flex;
  flex-direction: column;
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px;
  border-bottom: 1px solid #2a2a4a;
}

.modal-header h3 {
  margin: 0;
  font-size: 1rem;
  color: #fff;
}

.modal-body {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
}

.modal-footer {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
  padding: 16px;
  border-top: 1px solid #2a2a4a;
}

/* Templates Layout */
.templates-layout {
  display: flex;
}

.templates-list {
  width: 350px;
  border-right: 1px solid #2a2a4a;
  overflow-y: auto;
}

.template-category {
  margin-bottom: 16px;
}

.category-header {
  padding: 8px 16px;
  font-size: 0.7rem;
  font-weight: 600;
  color: #666;
  background: #0f0f1a;
  border-bottom: 1px solid #2a2a4a;
  position: sticky;
  top: 0;
}

.template-item {
  padding: 12px 16px;
  border-bottom: 1px solid #1a1a2e;
  cursor: pointer;
  transition: background 0.2s;
}

.template-item:hover {
  background: #1a1a2e;
}

.template-item.selected {
  background: #1e3a5f;
}

.template-name {
  font-size: 0.85rem;
  font-weight: 500;
  color: #fff;
}

.template-desc {
  font-size: 0.7rem;
  color: #666;
  margin-top: 4px;
}

.template-config {
  flex: 1;
  display: flex;
  flex-direction: column;
  padding: 20px;
  opacity: 0.3;
  pointer-events: none;
  transition: opacity 0.2s;
}

.template-config.visible {
  opacity: 1;
  pointer-events: auto;
}

.config-header {
  margin-bottom: 20px;
}

.config-header h3 {
  margin: 0 0 8px 0;
  font-size: 1.1rem;
  color: #fff;
}

.config-header p {
  margin: 0;
  font-size: 0.85rem;
  color: #888;
}

.config-form {
  flex: 1;
}

.formula-preview {
  display: block;
  padding: 12px;
  background: #1a1a2e;
  border-radius: 4px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.8rem;
  color: #60a5fa;
  word-break: break-all;
}

.config-actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
  margin-top: 20px;
}

.no-selection {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: #555;
}

.template-intro {
  font-size: 0.85rem;
  color: #888;
}

/* Action button styles */
.action-btn {
  padding: 6px 10px;
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 4px;
  color: #888;
  font-size: 0.8rem;
  cursor: pointer;
}

.action-btn:hover {
  background: #2a2a4a;
  color: #fff;
}

.action-btn.play {
  color: #22c55e;
  border-color: #166534;
}

.action-btn.play:hover {
  background: #166534;
}

.action-btn.pause {
  color: #fbbf24;
  border-color: #78350f;
}

.action-btn.pause:hover {
  background: #78350f;
}

/* =========================================================================
   FUNCTION BLOCKS TAB STYLES
   ========================================================================= */

.search-input {
  padding: 8px 12px;
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 4px;
  color: #fff;
  font-size: 0.85rem;
  width: 200px;
}

.search-input:focus {
  outline: none;
  border-color: #3b82f6;
}

.blocks-layout {
  display: flex;
  gap: 0;
}

.templates-panel {
  width: 280px;
  background: #0a0a14;
  border-right: 1px solid #2a2a4a;
  overflow-y: auto;
}

.create-block-form {
  padding: 12px;
  border-bottom: 1px solid #2a2a4a;
  background: #0f0f1a;
}

.selected-template {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: #1e3a5f;
  border-radius: 4px;
  margin-bottom: 8px;
}

.template-icon {
  font-size: 1.2rem;
}

.template-name {
  flex: 1;
  font-size: 0.85rem;
  font-weight: 500;
  color: #fff;
}

.clear-btn {
  background: transparent;
  border: none;
  color: #888;
  cursor: pointer;
  padding: 4px;
}

.clear-btn:hover {
  color: #fff;
}

.block-name-input {
  width: 100%;
  padding: 8px 12px;
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 4px;
  color: #fff;
  font-size: 0.85rem;
  margin-bottom: 8px;
}

.block-name-input:focus {
  outline: none;
  border-color: #3b82f6;
}

.btn-full {
  width: 100%;
}

.template-categories {
  padding: 8px 0;
}

.block-category {
  margin-bottom: 4px;
}

.block-category .category-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  font-size: 0.7rem;
  font-weight: 600;
  color: #666;
  background: transparent;
  border-bottom: none;
}

.category-icon {
  font-size: 0.9rem;
}

.category-templates {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  padding: 4px 12px 8px;
}

.template-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 6px 10px;
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 4px;
  color: #888;
  font-size: 0.75rem;
  cursor: pointer;
  transition: all 0.2s;
}

.template-btn:hover {
  background: #1e3a5f;
  border-color: #3b82f6;
  color: #fff;
}

.template-btn .t-icon {
  font-size: 0.9rem;
}

.template-btn .t-name {
  white-space: nowrap;
}

.blocks-list {
  flex: 1;
  min-width: 350px;
}

.block-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
}

.block-category-icon {
  font-size: 1.2rem;
  width: 28px;
  text-align: center;
}

.block-outputs {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 120px;
}

.block-outputs .output-value {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 0.7rem;
  font-family: 'JetBrains Mono', monospace;
}

.block-outputs .output-name {
  color: #666;
}

.block-outputs .value {
  color: #22c55e;
}

.block-outputs .output-value.error .value {
  color: #ef4444;
}

.block-editor {
  min-width: 400px;
}

.block-editor .editor-header {
  display: flex;
  align-items: center;
}

.block-editor .editor-header h3 {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
}

.block-icon {
  font-size: 1.2rem;
}

.header-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}

.block-info {
  padding: 12px;
  background: #1a1a2e;
  border-radius: 4px;
  margin-bottom: 16px;
}

.block-info p {
  margin: 0 0 8px 0;
  font-size: 0.85rem;
  color: #888;
}

.block-category-badge {
  display: inline-block;
  padding: 2px 8px;
  background: #2a2a4a;
  border-radius: 4px;
  font-size: 0.7rem;
  color: #888;
  text-transform: uppercase;
}

.form-section {
  margin-bottom: 20px;
}

.section-header {
  font-size: 0.7rem;
  font-weight: 600;
  color: #666;
  margin-bottom: 10px;
  text-transform: uppercase;
}

.inputs-grid,
.outputs-grid {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.input-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.input-label {
  width: 140px;
  font-size: 0.8rem;
  color: #ccc;
  flex-shrink: 0;
}

.input-label .required {
  color: #ef4444;
}

.input-unit {
  font-size: 0.7rem;
  color: #666;
  margin-left: 4px;
}

.number-input,
.bool-select,
.binding-select {
  flex: 1;
  padding: 6px 10px;
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 4px;
  color: #fff;
  font-size: 0.8rem;
}

.number-input:focus,
.bool-select:focus,
.binding-select:focus {
  outline: none;
  border-color: #3b82f6;
}

.number-input {
  width: 100px;
}

.output-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  background: #0a0a14;
  border-radius: 4px;
}

.output-label {
  font-size: 0.8rem;
  color: #ccc;
}

.output-display {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.9rem;
}

.output-display .output-value-num {
  color: #22c55e;
  font-weight: 500;
}

.output-display.error .error-text {
  color: #ef4444;
  font-size: 0.75rem;
}

.output-unit {
  font-size: 0.75rem;
  color: #666;
  margin-left: 4px;
}

.state-display {
  background: #0a0a14;
  border-radius: 4px;
  padding: 8px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.75rem;
}

.state-row {
  display: flex;
  gap: 8px;
  padding: 4px;
}

.state-key {
  color: #888;
}

.state-value {
  color: #60a5fa;
}

/* Schedule Tab Styles */
.schedule-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 12px;
}

.schedule-card {
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 8px;
  padding: 16px;
}

.schedule-card.disabled {
  opacity: 0.5;
}

.schedule-card.running {
  border-color: #22c55e;
  box-shadow: 0 0 8px rgba(34, 197, 94, 0.3);
}

.schedule-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 12px;
}

.schedule-info h4 {
  margin: 0 0 4px;
  color: #fff;
  font-size: 1rem;
}

.schedule-info .description {
  margin: 0;
  color: #888;
  font-size: 0.85rem;
}

.schedule-controls {
  display: flex;
  gap: 8px;
}

.schedule-timing {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  margin-bottom: 12px;
  padding: 12px;
  background: #0f0f1a;
  border-radius: 6px;
}

.schedule-timing .label {
  color: #888;
  font-size: 0.8rem;
  margin-right: 6px;
}

.schedule-timing .value {
  color: #fff;
  font-size: 0.9rem;
}

.schedule-timing .value.active {
  color: #22c55e;
  font-weight: 600;
}

.schedule-actions {
  display: flex;
  gap: 16px;
}

.action-group {
  display: flex;
  align-items: center;
  gap: 6px;
}

.action-group .group-label {
  color: #888;
  font-size: 0.8rem;
}

.action-group .action-count {
  color: #60a5fa;
  font-size: 0.85rem;
}

.schedule-summary .active-indicator {
  color: #22c55e;
  font-weight: 600;
}

/* Day Picker */
.day-picker {
  display: flex;
  gap: 6px;
}

.day-btn {
  padding: 6px 10px;
  background: #1a1a2e;
  border: 1px solid #2a2a4a;
  border-radius: 4px;
  color: #888;
  cursor: pointer;
  font-size: 0.8rem;
}

.day-btn:hover {
  background: #2a2a4a;
}

.day-btn.selected {
  background: #3b82f6;
  border-color: #3b82f6;
  color: #fff;
}

.schedule-editor-modal {
  width: 500px;
}

/* SetVariable Step Styles */
.form-group .hint {
  display: block;
  font-size: 0.7rem;
  color: #666;
  margin-top: 4px;
}

.info-box {
  background: #1a2a3a;
  border: 1px solid #2a3a4a;
  border-radius: 4px;
  padding: 10px 12px;
  font-size: 0.8rem;
  color: #aaa;
  margin-top: 12px;
}

.info-box strong {
  color: #60a5fa;
}

.info-box code {
  background: #0f1520;
  padding: 2px 4px;
  border-radius: 2px;
  font-family: monospace;
  color: #22c55e;
}
</style>
