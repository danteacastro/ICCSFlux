<script setup lang="ts">
/**
 * PidCustomSymbolImport - Import custom SVG symbols into the P&ID library
 *
 * Provides file picker, SVG preview, validation, name/category input,
 * and port placement via click-on-edge.
 */
import { ref, computed } from 'vue'
import { useDashboardStore } from '../stores/dashboard'

const store = useDashboardStore()
const emit = defineEmits<{ close: [] }>()

const svgContent = ref('')
const symbolName = ref('')
const symbolCategory = ref('Custom')
const previewSvg = ref('')
const validationError = ref('')
const ports = ref<Array<{ id: string; x: number; y: number; direction: 'left' | 'right' | 'top' | 'bottom' }>>([])

function onFileSelect(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return

  const reader = new FileReader()
  reader.onload = () => {
    const content = reader.result as string
    validateAndPreview(content)
  }
  reader.readAsText(file)
}

function validateAndPreview(content: string) {
  validationError.value = ''
  ports.value = []

  // Basic validation
  if (!content.includes('<svg')) {
    validationError.value = 'File does not contain an SVG element'
    return
  }

  // Check for script tags (security)
  if (/<script/i.test(content)) {
    validationError.value = 'SVG contains script elements (not allowed)'
    return
  }

  // Check for event handlers
  if (/on\w+\s*=/i.test(content)) {
    validationError.value = 'SVG contains event handlers (not allowed)'
    return
  }

  // Check for viewBox
  if (!content.includes('viewBox')) {
    validationError.value = 'SVG missing viewBox attribute (required for scaling)'
    return
  }

  svgContent.value = content
  previewSvg.value = content
}

function onPreviewClick(event: MouseEvent) {
  const target = event.currentTarget as HTMLElement
  const rect = target.getBoundingClientRect()
  const x = (event.clientX - rect.left) / rect.width
  const y = (event.clientY - rect.top) / rect.height

  // Determine direction based on position
  let direction: 'left' | 'right' | 'top' | 'bottom'
  const edgeDist = { left: x, right: 1 - x, top: y, bottom: 1 - y }
  const minEdge = Math.min(edgeDist.left, edgeDist.right, edgeDist.top, edgeDist.bottom)
  if (minEdge === edgeDist.left) direction = 'left'
  else if (minEdge === edgeDist.right) direction = 'right'
  else if (minEdge === edgeDist.top) direction = 'top'
  else direction = 'bottom'

  ports.value.push({
    id: `port-${ports.value.length + 1}`,
    x: Math.round(x * 100) / 100,
    y: Math.round(y * 100) / 100,
    direction
  })
}

function removePort(index: number) {
  ports.value.splice(index, 1)
}

const canImport = computed(() =>
  svgContent.value && symbolName.value.trim() && !validationError.value
)

function doImport() {
  if (!canImport.value) return
  const id = `custom-${Date.now()}-${Math.random().toString(36).slice(2, 5)}`
  store.pidAddCustomSymbol(id, {
    svg: svgContent.value,
    name: symbolName.value.trim(),
    category: symbolCategory.value || 'Custom',
    ports: ports.value
  })
  emit('close')
}
</script>

<template>
  <div class="import-overlay" @click.self="emit('close')">
    <div class="import-dialog">
      <div class="dialog-header">
        <span class="dialog-title">Import Custom Symbol</span>
        <button class="btn-close" @click="emit('close')">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
          </svg>
        </button>
      </div>

      <div class="dialog-body">
        <!-- File picker -->
        <div class="form-group">
          <label class="form-label">SVG File</label>
          <input type="file" accept=".svg" @change="onFileSelect" class="file-input" />
        </div>

        <div v-if="validationError" class="error-msg">{{ validationError }}</div>

        <!-- Preview + port placement -->
        <div v-if="previewSvg && !validationError" class="preview-section">
          <label class="form-label">Preview (click edges to add ports)</label>
          <div class="preview-box" @click="onPreviewClick">
            <div class="preview-svg" v-html="previewSvg" />
            <!-- Port markers -->
            <div
              v-for="(port, idx) in ports"
              :key="port.id"
              class="port-marker"
              :style="{ left: `${port.x * 100}%`, top: `${port.y * 100}%` }"
              @click.stop="removePort(idx)"
              :title="`Port ${idx + 1} (${port.direction}) - Click to remove`"
            >{{ idx + 1 }}</div>
          </div>
          <div v-if="ports.length > 0" class="port-list">
            <span v-for="(port, idx) in ports" :key="port.id" class="port-tag">
              Port {{ idx + 1 }}: {{ port.direction }}
            </span>
          </div>
        </div>

        <!-- Name + category -->
        <div class="form-row">
          <div class="form-group">
            <label class="form-label">Name</label>
            <input v-model="symbolName" type="text" class="text-input" placeholder="e.g., Custom Valve" />
          </div>
          <div class="form-group">
            <label class="form-label">Category</label>
            <input v-model="symbolCategory" type="text" class="text-input" placeholder="Custom" />
          </div>
        </div>
      </div>

      <div class="dialog-footer">
        <button class="btn-cancel" @click="emit('close')">Cancel</button>
        <button class="btn-import" :disabled="!canImport" @click="doImport">Import Symbol</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.import-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 300;
}

.import-dialog {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  width: 480px;
  max-height: 80vh;
  overflow-y: auto;
  box-shadow: 0 16px 48px rgba(0, 0, 0, 0.5);
}

.dialog-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-color);
}

.dialog-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-accent-light);
}

.btn-close {
  background: transparent;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
  padding: 2px;
}

.btn-close:hover {
  color: var(--text-primary);
}

.dialog-body {
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.form-label {
  font-size: 11px;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.3px;
}

.file-input {
  font-size: 12px;
  color: var(--text-bright);
}

.text-input {
  background: var(--bg-widget);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  padding: 6px 8px;
  color: var(--text-bright);
  font-size: 13px;
  outline: none;
}

.text-input:focus {
  border-color: var(--color-accent);
}

.form-row {
  display: flex;
  gap: 12px;
}

.form-row .form-group {
  flex: 1;
}

.error-msg {
  color: var(--color-error);
  font-size: 12px;
  padding: 6px 8px;
  background: rgba(239, 68, 68, 0.1);
  border-radius: 4px;
}

.preview-section {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.preview-box {
  position: relative;
  width: 200px;
  height: 200px;
  border: 1px solid var(--border-color);
  border-radius: 4px;
  background: var(--bg-widget);
  cursor: crosshair;
  overflow: hidden;
  align-self: center;
}

.preview-svg {
  width: 100%;
  height: 100%;
  color: var(--color-accent-light);
  display: flex;
  align-items: center;
  justify-content: center;
}

.preview-svg :deep(svg) {
  width: 80%;
  height: 80%;
}

.port-marker {
  position: absolute;
  width: 16px;
  height: 16px;
  background: var(--color-success);
  color: var(--text-primary);
  border-radius: 50%;
  font-size: 9px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  transform: translate(-50%, -50%);
  cursor: pointer;
  border: 2px solid var(--text-primary);
}

.port-marker:hover {
  background: var(--color-error);
}

.port-list {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.port-tag {
  font-size: 10px;
  padding: 2px 6px;
  background: var(--bg-surface);
  border-radius: 3px;
  color: var(--text-secondary);
}

.dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 12px 16px;
  border-top: 1px solid var(--border-color);
}

.btn-cancel {
  padding: 6px 16px;
  background: transparent;
  border: 1px solid var(--border-heavy);
  border-radius: 4px;
  color: var(--text-secondary);
  font-size: 12px;
  cursor: pointer;
}

.btn-cancel:hover {
  background: var(--bg-surface);
}

.btn-import {
  padding: 6px 16px;
  background: var(--color-accent);
  border: none;
  border-radius: 4px;
  color: var(--text-primary);
  font-size: 12px;
  cursor: pointer;
}

.btn-import:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.btn-import:not(:disabled):hover {
  background: var(--color-accent-dark);
}
</style>
