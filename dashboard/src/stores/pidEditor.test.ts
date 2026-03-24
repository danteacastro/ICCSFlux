/**
 * Tests for P&ID editor store operations
 *
 * Covers: symbol CRUD, pipe CRUD, undo/redo, grouping, layers,
 * custom symbols, favorites, operator notes
 */
import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useDashboardStore } from './dashboard'

describe('P&ID Editor Store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  // ======================================================
  // SYMBOL CRUD
  // ======================================================

  describe('Symbol Management', () => {
    it('should add a symbol to the layer', () => {
      const store = useDashboardStore()
      const id = store.addPidSymbol({
        type: 'solenoidValve',
        x: 100, y: 200,
        width: 60, height: 60,
        rotation: 0,
      } as any)
      expect(store.pidLayer.symbols).toHaveLength(1)
      expect(store.pidLayer.symbols[0]!.id).toBe(id)
    })

    it('should update a symbol', () => {
      const store = useDashboardStore()
      const id = store.addPidSymbol({
        type: 'solenoidValve', x: 0, y: 0, width: 60, height: 60, rotation: 0,
      } as any)
      store.updatePidSymbol(id, { x: 300, y: 400 })
      expect(store.pidLayer.symbols[0]!.x).toBe(300)
      expect(store.pidLayer.symbols[0]!.y).toBe(400)
    })

    it('should remove a symbol', () => {
      const store = useDashboardStore()
      const id = store.addPidSymbol({
        type: 'solenoidValve', x: 0, y: 0, width: 60, height: 60, rotation: 0,
      } as any)
      store.removePidSymbol(id)
      expect(store.pidLayer.symbols).toHaveLength(0)
    })
  })

  // ======================================================
  // PIPE CRUD
  // ======================================================

  describe('Pipe Management', () => {
    it('should add a pipe', () => {
      const store = useDashboardStore()
      store.addPidPipe({
        points: [{ x: 0, y: 0 }, { x: 100, y: 0 }],
        color: '#60a5fa',
        strokeWidth: 2,
      } as any)
      expect(store.pidLayer.pipes).toHaveLength(1)
    })

    it('should update a pipe', () => {
      const store = useDashboardStore()
      const id = store.addPidPipe({
        points: [{ x: 0, y: 0 }, { x: 100, y: 0 }],
        color: '#60a5fa',
        strokeWidth: 2,
      } as any)
      store.updatePidPipe(id, { color: '#ff0000' })
      expect(store.pidLayer.pipes[0]!.color).toBe('#ff0000')
    })

    it('should remove a pipe', () => {
      const store = useDashboardStore()
      const id = store.addPidPipe({
        points: [{ x: 0, y: 0 }, { x: 100, y: 0 }],
        color: '#60a5fa',
        strokeWidth: 2,
      } as any)
      store.removePidPipe(id)
      expect(store.pidLayer.pipes).toHaveLength(0)
    })
  })

  // ======================================================
  // UNDO / REDO
  // ======================================================

  describe('Undo/Redo', () => {
    it('should undo a symbol add', () => {
      const store = useDashboardStore()
      store.addPidSymbolWithUndo({
        type: 'solenoidValve', x: 100, y: 100, width: 60, height: 60, rotation: 0,
      } as any)
      expect(store.pidLayer.symbols).toHaveLength(1)
      expect(store.canPidUndo).toBe(true)
      store.pidUndo()
      expect(store.pidLayer.symbols).toHaveLength(0)
    })

    it('should redo after undo', () => {
      const store = useDashboardStore()
      store.addPidSymbolWithUndo({
        type: 'solenoidValve', x: 100, y: 100, width: 60, height: 60, rotation: 0,
      } as any)
      store.pidUndo()
      expect(store.canPidRedo).toBe(true)
      store.pidRedo()
      expect(store.pidLayer.symbols).toHaveLength(1)
    })

    it('should clear redo stack on new action after undo', () => {
      const store = useDashboardStore()
      store.addPidSymbolWithUndo({
        type: 'solenoidValve', x: 0, y: 0, width: 60, height: 60, rotation: 0,
      } as any)
      store.pidUndo()
      store.addPidSymbolWithUndo({
        type: 'centrifugalPump', x: 100, y: 100, width: 60, height: 60, rotation: 0,
      } as any)
      expect(store.canPidRedo).toBe(false)
    })
  })

  // ======================================================
  // CUSTOM SYMBOLS
  // ======================================================

  describe('Custom Symbols', () => {
    it('should add a custom symbol', () => {
      const store = useDashboardStore()
      store.pidAddCustomSymbol('custom-1', {
        svg: '<svg viewBox="0 0 100 100"><rect width="100" height="100"/></svg>',
        name: 'Test Symbol',
        category: 'Custom',
        ports: [],
      })
      expect(store.pidCustomSymbols['custom-1']).toBeDefined()
      expect(store.pidCustomSymbols['custom-1']!.name).toBe('Test Symbol')
    })

    it('should persist custom symbols to localStorage', () => {
      const store = useDashboardStore()
      store.pidAddCustomSymbol('custom-1', {
        svg: '<svg></svg>',
        name: 'Stored Symbol',
        category: 'Custom',
        ports: [],
      })
      const saved = JSON.parse(localStorage.getItem('pid-custom-symbols') || '{}')
      expect(saved['custom-1']).toBeDefined()
    })

    it('should remove a custom symbol', () => {
      const store = useDashboardStore()
      store.pidAddCustomSymbol('custom-1', {
        svg: '<svg></svg>', name: 'Test', category: 'Custom', ports: [],
      })
      store.pidRemoveCustomSymbol('custom-1')
      expect(store.pidCustomSymbols['custom-1']).toBeUndefined()
    })
  })

  // ======================================================
  // FAVORITES & RECENT
  // ======================================================

  describe('Favorites & Recent', () => {
    it('should toggle favorite symbol', () => {
      const store = useDashboardStore()
      store.pidToggleFavorite('solenoidValve')
      expect(store.pidFavoriteSymbols).toContain('solenoidValve')
      store.pidToggleFavorite('solenoidValve')
      expect(store.pidFavoriteSymbols).not.toContain('solenoidValve')
    })

    it('should track recent symbols (max 10)', () => {
      const store = useDashboardStore()
      for (let i = 0; i < 15; i++) {
        store.pidTrackRecentSymbol(`sym-${i}`)
      }
      expect(store.pidRecentSymbols).toHaveLength(10)
      expect(store.pidRecentSymbols[0]).toBe('sym-14') // most recent first
    })

    it('should persist favorites to localStorage', () => {
      const store = useDashboardStore()
      store.pidToggleFavorite('centrifugalPump')
      const saved = JSON.parse(localStorage.getItem('pid-favorites') || '[]')
      expect(saved).toContain('centrifugalPump')
    })
  })

  // ======================================================
  // OPERATOR NOTES (#6.6)
  // ======================================================

  describe('Operator Notes', () => {
    it('should add an operator note', () => {
      const store = useDashboardStore()
      const id = store.pidAddOperatorNote(100, 200, 'Test note')
      expect(store.pidOperatorNotes).toHaveLength(1)
      expect(store.pidOperatorNotes[0]!.text).toBe('Test note')
      expect(store.pidOperatorNotes[0]!.id).toBe(id)
    })

    it('should update an operator note', () => {
      const store = useDashboardStore()
      const id = store.pidAddOperatorNote(100, 200, 'Original')
      store.pidUpdateOperatorNote(id, { text: 'Updated' })
      expect(store.pidOperatorNotes[0]!.text).toBe('Updated')
    })

    it('should remove an operator note', () => {
      const store = useDashboardStore()
      const id = store.pidAddOperatorNote(100, 200, 'Delete me')
      store.pidRemoveOperatorNote(id)
      expect(store.pidOperatorNotes).toHaveLength(0)
    })

    it('should clear all operator notes', () => {
      const store = useDashboardStore()
      store.pidAddOperatorNote(0, 0, 'A')
      store.pidAddOperatorNote(10, 10, 'B')
      store.pidClearOperatorNotes()
      expect(store.pidOperatorNotes).toHaveLength(0)
    })

    it('should persist notes to localStorage', () => {
      const store = useDashboardStore()
      store.pidAddOperatorNote(50, 50, 'Persisted')
      const saved = JSON.parse(localStorage.getItem('pid-operator-notes') || '[]')
      expect(saved).toHaveLength(1)
      expect(saved[0].text).toBe('Persisted')
    })

    it('should set default color and author', () => {
      const store = useDashboardStore()
      store.pidAddOperatorNote(0, 0, 'Defaults')
      expect(store.pidOperatorNotes[0]!.color).toBe('#fbbf24')
      expect(store.pidOperatorNotes[0]!.author).toBe('Operator')
    })

    it('should set custom color and author', () => {
      const store = useDashboardStore()
      store.pidAddOperatorNote(0, 0, 'Custom', '#ef4444', 'Admin')
      expect(store.pidOperatorNotes[0]!.color).toBe('#ef4444')
      expect(store.pidOperatorNotes[0]!.author).toBe('Admin')
    })
  })

  // ======================================================
  // LAYERS
  // ======================================================

  describe('Layer Management', () => {
    it('should add a layer', () => {
      const store = useDashboardStore()
      const id = store.pidAddLayer('Piping')
      const layerInfos = store.pidLayer.layerInfos || []
      expect(layerInfos.find(l => l.id === id)).toBeDefined()
    })

    it('should toggle layer visibility', () => {
      const store = useDashboardStore()
      const id = store.pidAddLayer('Piping')
      store.pidToggleLayerVisibility(id)
      const info = (store.pidLayer.layerInfos || []).find(l => l.id === id)
      expect(info?.visible).toBe(false)
    })

    it('should toggle layer lock', () => {
      const store = useDashboardStore()
      const id = store.pidAddLayer('Piping')
      store.pidToggleLayerLock(id)
      const info = (store.pidLayer.layerInfos || []).find(l => l.id === id)
      expect(info?.locked).toBe(true)
    })

    it('should check if a layer is locked', () => {
      const store = useDashboardStore()
      const id = store.pidAddLayer('Piping')
      expect(store.isLayerLocked(id)).toBe(false)
      store.pidToggleLayerLock(id)
      expect(store.isLayerLocked(id)).toBe(true)
    })

    it('should rename a layer', () => {
      const store = useDashboardStore()
      const id = store.pidAddLayer('Piping')
      store.pidRenameLayer(id, 'Process Piping')
      const info = (store.pidLayer.layerInfos || []).find(l => l.id === id)
      expect(info?.name).toBe('Process Piping')
    })
  })

  // ======================================================
  // SELECTION
  // ======================================================

  describe('Selection', () => {
    it('should select items', () => {
      const store = useDashboardStore()
      store.pidSelectItems(['s1', 's2'], [], [])
      expect(store.pidSelectedIds.symbolIds).toEqual(['s1', 's2'])
    })

    it('should clear selection', () => {
      const store = useDashboardStore()
      store.pidSelectItems(['s1'], ['p1'], [])
      store.pidClearSelection()
      expect(store.pidSelectedIds.symbolIds).toHaveLength(0)
      expect(store.pidSelectedIds.pipeIds).toHaveLength(0)
    })

    it('should report hasPidSelection', () => {
      const store = useDashboardStore()
      expect(store.hasPidSelection).toBe(false)
      store.pidSelectItems(['s1'], [], [])
      expect(store.hasPidSelection).toBe(true)
    })
  })

  // ======================================================
  // COPY / PASTE
  // ======================================================

  describe('Copy & Paste', () => {
    it('should copy and paste symbols', () => {
      const store = useDashboardStore()
      const id = store.addPidSymbol({
        type: 'solenoidValve', x: 100, y: 100, width: 60, height: 60, rotation: 0,
      } as any)
      store.pidSelectItems([id], [], [])
      store.pidCopy()
      expect(store.hasPidClipboard).toBe(true)
      store.pidPaste()
      expect(store.pidLayer.symbols).toHaveLength(2)
      // Pasted symbol should have different ID
      expect(store.pidLayer.symbols[1]!.id).not.toBe(id)
    })
  })
})
