<script setup lang="ts">
/**
 * PidToolbar - Toolbar for P&ID Canvas Editing
 *
 * Provides controls for:
 * - Adding P&ID symbols (valves, pumps, tanks, etc.)
 * - Drawing free-form pipes
 * - Symbol type selection
 * - Pipe style options
 */

import { ref, computed } from 'vue'
import { useDashboardStore } from '../stores/dashboard'
import { SCADA_SYMBOLS, type ScadaSymbolType } from '../assets/symbols'

const store = useDashboardStore()

// Currently selected symbol type for adding
const selectedSymbolType = ref<ScadaSymbolType>('solenoidValve')

// Available symbols with display names - grouped by category
const availableSymbols: { type: ScadaSymbolType; name: string }[] = [
  // Valves
  { type: 'solenoidValve', name: 'Solenoid Valve' },
  { type: 'controlValve', name: 'Control Valve' },
  { type: 'ballValve', name: 'Ball Valve' },
  { type: 'gateValve', name: 'Gate Valve' },
  { type: 'checkValve', name: 'Check Valve' },
  { type: 'reliefValve', name: 'Relief Valve' },
  { type: 'butterflyValve', name: 'Butterfly Valve' },
  { type: 'threeWayValve', name: '3-Way Valve' },
  // Equipment
  { type: 'pump', name: 'Pump' },
  { type: 'compressor', name: 'Compressor' },
  { type: 'blower', name: 'Blower/Fan' },
  { type: 'motor', name: 'Motor' },
  { type: 'filter', name: 'Filter' },
  { type: 'mixer', name: 'Mixer' },
  // Vessels
  { type: 'tank', name: 'Tank' },
  { type: 'horizontalTank', name: 'Horizontal Tank' },
  { type: 'reactor', name: 'Reactor' },
  { type: 'column', name: 'Column/Tower' },
  // Heat Exchangers
  { type: 'heatExchanger', name: 'Heat Exchanger' },
  { type: 'heater', name: 'Heater' },
  { type: 'cooler', name: 'Cooler' },
  { type: 'boiler', name: 'Boiler' },
  // Instruments
  { type: 'pressureTransducer', name: 'Pressure Transmitter' },
  { type: 'temperatureElement', name: 'Temperature Element' },
  { type: 'flowMeter', name: 'Flow Meter' },
  { type: 'levelTransmitter', name: 'Level Transmitter' },
  { type: 'pressureGauge', name: 'Pressure Gauge' }
]

// Pipe drawing options
const pipeColor = ref('#60a5fa')
const pipeWidth = ref(3)
const pipeDashed = ref(false)
const pipeAnimated = ref(false)
const pipePathType = ref<'polyline' | 'bezier' | 'orthogonal'>('polyline')

// Add a new symbol to the canvas
function addSymbol() {
  // Add symbol at center of viewport (will be draggable)
  store.addPidSymbol({
    type: selectedSymbolType.value,
    x: 200,
    y: 200,
    width: 60,
    height: 60,
    rotation: 0,
    color: '#60a5fa',
    showValue: false
  })
}

// Toggle pipe drawing mode
function togglePipeDrawing() {
  store.setPidDrawingMode(!store.pidDrawingMode)
}

// Exit P&ID edit mode
function exitEditMode() {
  store.setPidEditMode(false)
}

// Clear all P&ID elements
function clearAll() {
  if (confirm('Clear all P&ID symbols and pipes on this page?')) {
    store.clearPidLayer()
  }
}

// Get symbol preview SVG
function getSymbolPreview(type: ScadaSymbolType): string {
  return SCADA_SYMBOLS[type] || ''
}
</script>

<template>
  <div class="pid-toolbar">
    <div class="toolbar-section">
      <span class="section-title">P&ID Editor</span>
      <button class="btn-exit" @click="exitEditMode" title="Exit P&ID Edit Mode">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <line x1="18" y1="6" x2="6" y2="18"></line>
          <line x1="6" y1="6" x2="18" y2="18"></line>
        </svg>
        Exit
      </button>
    </div>

    <div class="toolbar-divider" />

    <!-- Add Symbol Section -->
    <div class="toolbar-section">
      <span class="section-label">Add Symbol:</span>
      <select v-model="selectedSymbolType" class="symbol-select">
        <option v-for="sym in availableSymbols" :key="sym.type" :value="sym.type">
          {{ sym.name }}
        </option>
      </select>
      <button class="btn-add" @click="addSymbol" title="Add Symbol">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <line x1="12" y1="5" x2="12" y2="19"></line>
          <line x1="5" y1="12" x2="19" y2="12"></line>
        </svg>
        Add
      </button>
    </div>

    <div class="toolbar-divider" />

    <!-- Pipe Drawing Section -->
    <div class="toolbar-section">
      <button
        class="btn-pipe"
        :class="{ active: store.pidDrawingMode }"
        @click="togglePipeDrawing"
        title="Draw Pipe"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M2 12h6l4-4 4 8 4-4h4" />
        </svg>
        {{ store.pidDrawingMode ? 'Drawing...' : 'Draw Pipe' }}
      </button>

      <select v-model="pipePathType" class="pipe-type-select" title="Pipe Path Type">
        <option value="polyline">Straight</option>
        <option value="bezier">Curved</option>
        <option value="orthogonal">Right-Angle</option>
      </select>

      <input
        type="color"
        v-model="pipeColor"
        class="color-picker"
        title="Pipe Color"
      />

      <label class="checkbox-label" title="Dashed Line">
        <input type="checkbox" v-model="pipeDashed" />
        Dashed
      </label>

      <label class="checkbox-label" title="Animated Flow">
        <input type="checkbox" v-model="pipeAnimated" />
        Flow
      </label>
    </div>

    <div class="toolbar-divider" />

    <!-- Actions -->
    <div class="toolbar-section">
      <button class="btn-clear" @click="clearAll" title="Clear All P&ID Elements">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polyline points="3 6 5 6 21 6"></polyline>
          <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
        </svg>
        Clear
      </button>
    </div>

    <!-- Help Text -->
    <div class="toolbar-help">
      <span v-if="store.pidDrawingMode">Click to add points, double-click to finish pipe</span>
      <span v-else>Drag symbols to position, corners to resize</span>
    </div>
  </div>
</template>

<style scoped>
.pid-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 16px;
  background: linear-gradient(to right, #1e3a5f, #2a4a6f);
  border-bottom: 1px solid #3b5998;
  flex-wrap: wrap;
}

.toolbar-section {
  display: flex;
  align-items: center;
  gap: 8px;
}

.section-title {
  font-size: 13px;
  font-weight: 600;
  color: #60a5fa;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.section-label {
  font-size: 12px;
  color: #aaa;
}

.toolbar-divider {
  width: 1px;
  height: 24px;
  background: #3b5998;
}

/* Buttons */
button {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 6px 12px;
  border: none;
  border-radius: 4px;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.15s;
}

.btn-exit {
  background: #4a5568;
  color: #fff;
}

.btn-exit:hover {
  background: #718096;
}

.btn-add {
  background: #22c55e;
  color: #fff;
}

.btn-add:hover {
  background: #16a34a;
}

.btn-pipe {
  background: #3b82f6;
  color: #fff;
}

.btn-pipe:hover {
  background: #2563eb;
}

.btn-pipe.active {
  background: #f59e0b;
  animation: pulse 1s infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.7; }
}

.btn-clear {
  background: #ef4444;
  color: #fff;
}

.btn-clear:hover {
  background: #dc2626;
}

/* Inputs */
.symbol-select,
.pipe-type-select {
  padding: 4px 8px;
  background: #2d3748;
  border: 1px solid #4a5568;
  border-radius: 4px;
  color: #fff;
  font-size: 12px;
}

.color-picker {
  width: 28px;
  height: 28px;
  padding: 0;
  border: none;
  border-radius: 4px;
  cursor: pointer;
}

.checkbox-label {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  color: #aaa;
  cursor: pointer;
}

.checkbox-label input {
  margin: 0;
}

/* Help text */
.toolbar-help {
  margin-left: auto;
  font-size: 11px;
  color: #888;
  font-style: italic;
}
</style>
