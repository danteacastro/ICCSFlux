<script setup lang="ts">
import { ref, watch, computed } from 'vue'
import { useDashboardStore } from '../stores/dashboard'
import type { WidgetStyle } from '../types'
import { WIDGET_COLORS } from '../types'

const props = defineProps<{
  widgetId: string
  text?: string
  style?: WidgetStyle
}>()

const store = useDashboardStore()
const isEditing = ref(false)
const showSettings = ref(false)
const editText = ref(props.text || 'Title')

// Style settings
const fontSize = computed(() => props.style?.fontSize || 'medium')
const textAlign = computed(() => props.style?.textAlign || 'left')
const verticalAlign = computed(() => props.style?.verticalAlign || 'center')
const textColor = computed(() => props.style?.textColor || '#ffffff')
const backgroundColor = computed(() => props.style?.backgroundColor || 'transparent')

const fontSizeClass = computed(() => {
  const sizes: Record<string, string> = {
    small: 'text-sm',
    medium: 'text-md',
    large: 'text-lg',
    xlarge: 'text-xl'
  }
  return sizes[fontSize.value] || 'text-md'
})

const alignClass = computed(() => `align-${textAlign.value} valign-${verticalAlign.value}`)

const customStyle = computed(() => ({
  color: textColor.value,
  backgroundColor: backgroundColor.value === 'transparent' ? undefined : backgroundColor.value,
}))

function startEdit() {
  if (store.editMode) {
    isEditing.value = true
    editText.value = props.text || 'Title'
  }
}

function saveEdit() {
  isEditing.value = false
  // Update text property (which takes precedence in DashboardGrid)
  // Also clear title to prevent it from overriding
  store.updateWidget(props.widgetId, {
    text: editText.value,
    label: editText.value,
    title: undefined
  })
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter') {
    saveEdit()
  } else if (e.key === 'Escape') {
    isEditing.value = false
  }
}

function openSettings() {
  if (store.editMode) {
    showSettings.value = true
  }
}

function closeSettings() {
  showSettings.value = false
}

function updateStyle(updates: Partial<WidgetStyle>) {
  store.updateWidgetStyle(props.widgetId, updates)
}

watch(() => props.text, (newText) => {
  editText.value = newText || 'Title'
})
</script>

<template>
  <div
    class="title-label no-drag"
    :class="[fontSizeClass, alignClass]"
    :style="customStyle"
    @dblclick="startEdit"
  >
    <input
      v-if="isEditing"
      v-model="editText"
      @blur="saveEdit"
      @keydown="handleKeydown"
      class="edit-input no-drag"
      autofocus
    />
    <span v-else class="label-text">{{ text || 'Title' }}</span>

    <!-- Settings button (edit mode only) -->
    <button
      v-if="store.editMode && !isEditing"
      class="settings-btn"
      @click.stop="openSettings"
      title="Style settings"
    >
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <circle cx="12" cy="12" r="3"/>
        <path d="M12 1v4M12 19v4M4.22 4.22l2.83 2.83M16.95 16.95l2.83 2.83M1 12h4M19 12h4M4.22 19.78l2.83-2.83M16.95 7.05l2.83-2.83"/>
      </svg>
    </button>
  </div>

  <!-- Settings Modal -->
  <Teleport to="body">
    <div v-if="showSettings" class="modal-overlay" @click.self="closeSettings">
      <div class="modal settings-modal">
        <h3>Title Style</h3>

        <!-- Font Size -->
        <div class="setting-group">
          <label>Font Size</label>
          <div class="btn-group">
            <button
              v-for="size in ['small', 'medium', 'large', 'xlarge']"
              :key="size"
              :class="{ active: fontSize === size }"
              @click="updateStyle({ fontSize: size as WidgetStyle['fontSize'] })"
            >{{ size }}</button>
          </div>
        </div>

        <!-- Horizontal Align -->
        <div class="setting-group">
          <label>Horizontal</label>
          <div class="btn-group">
            <button :class="{ active: textAlign === 'left' }" @click="updateStyle({ textAlign: 'left' })">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="15" y2="12"/><line x1="3" y1="18" x2="18" y2="18"/>
              </svg>
            </button>
            <button :class="{ active: textAlign === 'center' }" @click="updateStyle({ textAlign: 'center' })">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <line x1="3" y1="6" x2="21" y2="6"/><line x1="6" y1="12" x2="18" y2="12"/><line x1="4" y1="18" x2="20" y2="18"/>
              </svg>
            </button>
            <button :class="{ active: textAlign === 'right' }" @click="updateStyle({ textAlign: 'right' })">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <line x1="3" y1="6" x2="21" y2="6"/><line x1="9" y1="12" x2="21" y2="12"/><line x1="6" y1="18" x2="21" y2="18"/>
              </svg>
            </button>
          </div>
        </div>

        <!-- Vertical Align -->
        <div class="setting-group">
          <label>Vertical</label>
          <div class="btn-group">
            <button :class="{ active: verticalAlign === 'top' }" @click="updateStyle({ verticalAlign: 'top' })">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <line x1="12" y1="3" x2="12" y2="15"/><polyline points="5 10 12 3 19 10"/>
              </svg>
            </button>
            <button :class="{ active: verticalAlign === 'center' }" @click="updateStyle({ verticalAlign: 'center' })">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <line x1="4" y1="12" x2="20" y2="12"/><circle cx="12" cy="12" r="2" fill="currentColor"/>
              </svg>
            </button>
            <button :class="{ active: verticalAlign === 'bottom' }" @click="updateStyle({ verticalAlign: 'bottom' })">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <line x1="12" y1="21" x2="12" y2="9"/><polyline points="19 14 12 21 5 14"/>
              </svg>
            </button>
          </div>
        </div>

        <!-- Text Color -->
        <div class="setting-group">
          <label>Text Color</label>
          <div class="color-swatches">
            <button
              v-for="color in WIDGET_COLORS.text"
              :key="color"
              class="color-swatch"
              :class="{ active: textColor === color }"
              :style="{ backgroundColor: color }"
              @click="updateStyle({ textColor: color })"
            ></button>
          </div>
        </div>

        <!-- Background Color -->
        <div class="setting-group">
          <label>Background</label>
          <div class="color-swatches">
            <button
              v-for="color in WIDGET_COLORS.background"
              :key="color"
              class="color-swatch"
              :class="{ active: backgroundColor === color, transparent: color === 'transparent' }"
              :style="{ backgroundColor: color === 'transparent' ? undefined : color }"
              @click="updateStyle({ backgroundColor: color })"
            >
              <span v-if="color === 'transparent'" class="transparent-x">×</span>
            </button>
          </div>
        </div>

        <button class="close-btn" @click="closeSettings">Done</button>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.title-label {
  display: flex;
  align-items: center;
  height: 100%;
  padding: 4px 8px;
  color: var(--text-primary);
  font-weight: 600;
  position: relative;
  border-radius: 4px;
}

.text-sm { font-size: 0.85rem; }
.text-md { font-size: 1.1rem; }
.text-lg { font-size: 1.5rem; }
.text-xl { font-size: 2rem; }

/* Horizontal alignment */
.align-left { justify-content: flex-start; }
.align-center { justify-content: center; }
.align-right { justify-content: flex-end; }

/* Vertical alignment */
.valign-top { align-items: flex-start; }
.valign-center { align-items: center; }
.valign-bottom { align-items: flex-end; }

.label-text {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.edit-input {
  background: var(--bg-widget);
  border: 1px solid var(--color-accent);
  border-radius: 4px;
  color: var(--text-primary);
  font-size: inherit;
  font-weight: inherit;
  padding: 2px 6px;
  width: 100%;
  outline: none;
}

.settings-btn {
  position: absolute;
  top: 2px;
  right: 2px;
  background: #2d3748;
  border: none;
  border-radius: 2px;
  color: var(--text-secondary);
  cursor: pointer;
  padding: 2px;
  display: flex;
  align-items: center;
  opacity: 0;
  transition: opacity 0.2s;
}

.title-label:hover .settings-btn {
  opacity: 1;
}

.settings-btn:hover {
  background: #4a5568;
  color: var(--text-primary);
}

/* Modal styles */
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.7);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.modal {
  background: var(--bg-widget);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 16px;
  min-width: 280px;
}

.modal h3 {
  margin: 0 0 16px;
  color: var(--text-primary);
  font-size: 1rem;
}

.setting-group {
  margin-bottom: 16px;
}

.setting-group label {
  display: block;
  font-size: 0.75rem;
  color: var(--text-secondary);
  margin-bottom: 8px;
  text-transform: uppercase;
}

.btn-group {
  display: flex;
  gap: 4px;
}

.btn-group button {
  flex: 1;
  padding: 6px 8px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  color: var(--text-secondary);
  font-size: 0.75rem;
  cursor: pointer;
  transition: all 0.2s;
  text-transform: capitalize;
}

.btn-group button:hover {
  background: var(--bg-widget);
  color: var(--text-primary);
}

.btn-group button.active {
  background: #1e3a5f;
  border-color: var(--color-accent);
  color: var(--text-primary);
}

.color-swatches {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.color-swatch {
  width: 28px;
  height: 28px;
  border: 2px solid var(--border-color);
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.2s;
  display: flex;
  align-items: center;
  justify-content: center;
}

.color-swatch:hover {
  border-color: #4a5568;
  transform: scale(1.1);
}

.color-swatch.active {
  border-color: var(--color-accent);
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.3);
}

.color-swatch.transparent {
  background: repeating-conic-gradient(#333 0% 25%, var(--bg-widget) 0% 50%) 50% / 10px 10px;
}

.transparent-x {
  color: var(--text-muted);
  font-size: 1.2rem;
  font-weight: bold;
}

.close-btn {
  width: 100%;
  padding: 8px;
  background: var(--color-accent);
  color: var(--text-primary);
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-weight: 500;
  margin-top: 8px;
}

.close-btn:hover {
  background: var(--color-accent-dark);
}
</style>
