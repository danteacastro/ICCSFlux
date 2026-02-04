/**
 * useWindowSync - Cross-window synchronization for multi-monitor support
 *
 * Uses BroadcastChannel API to sync layout changes across browser windows.
 * Also handles window position memory for multi-monitor setups.
 */

import { ref, watch } from 'vue'

// Message types for cross-window communication
interface SyncMessage {
  type: 'layout-update' | 'page-update' | 'edit-mode' | 'window-position'
  source: string  // Window ID to prevent echo
  payload: any
  timestamp: number
}

interface WindowPosition {
  pageId: string
  screenX: number
  screenY: number
  width: number
  height: number
  screenIndex?: number  // Which monitor (if detectable)
}

// Generate unique window ID
const windowId = `window-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`

// Singleton state
const channel = ref<BroadcastChannel | null>(null)
const isReceivingUpdate = ref(false)  // Guard against re-broadcasting received updates
const windowPositions = ref<Record<string, WindowPosition>>({})

// Callbacks for when updates are received
type LayoutUpdateCallback = (pages: any[]) => void
type EditModeCallback = (enabled: boolean) => void

const layoutUpdateCallbacks: LayoutUpdateCallback[] = []
const editModeCallbacks: EditModeCallback[] = []

export function useWindowSync() {

  // Initialize BroadcastChannel
  function init() {
    if (channel.value) return  // Already initialized

    try {
      channel.value = new BroadcastChannel('nisystem-dashboard-sync')

      channel.value.onmessage = (event: MessageEvent<SyncMessage>) => {
        const message = event.data

        // Ignore our own messages
        if (message.source === windowId) return

        console.debug('[WINDOW SYNC] Received:', message.type)

        // Set guard to prevent re-broadcasting
        isReceivingUpdate.value = true

        try {
          switch (message.type) {
            case 'layout-update':
              layoutUpdateCallbacks.forEach(cb => cb(message.payload))
              break
            case 'edit-mode':
              editModeCallbacks.forEach(cb => cb(message.payload))
              break
            case 'window-position':
              // Store window position from other windows
              const pos = message.payload as WindowPosition
              windowPositions.value[pos.pageId] = pos
              saveWindowPositions()
              break
          }
        } finally {
          // Clear guard after a tick to allow state to settle
          setTimeout(() => {
            isReceivingUpdate.value = false
          }, 50)
        }
      }

      console.debug('[WINDOW SYNC] Initialized with ID:', windowId)

      // Load saved window positions
      loadWindowPositions()

    } catch (e) {
      console.warn('[WINDOW SYNC] BroadcastChannel not supported:', e)
    }
  }

  // Broadcast layout changes to other windows
  function broadcastLayoutUpdate(pages: any[]) {
    if (!channel.value || isReceivingUpdate.value) return

    const message: SyncMessage = {
      type: 'layout-update',
      source: windowId,
      payload: pages,
      timestamp: Date.now()
    }

    channel.value.postMessage(message)
    console.debug('[WINDOW SYNC] Broadcast layout update')
  }

  // Broadcast edit mode changes
  function broadcastEditMode(enabled: boolean) {
    if (!channel.value || isReceivingUpdate.value) return

    const message: SyncMessage = {
      type: 'edit-mode',
      source: windowId,
      payload: enabled,
      timestamp: Date.now()
    }

    channel.value.postMessage(message)
  }

  // Register callback for layout updates
  function onLayoutUpdate(callback: LayoutUpdateCallback) {
    layoutUpdateCallbacks.push(callback)
  }

  // Register callback for edit mode changes
  function onEditModeChange(callback: EditModeCallback) {
    editModeCallbacks.push(callback)
  }

  // Check if we're currently receiving an update (to prevent re-broadcast)
  function isReceiving(): boolean {
    return isReceivingUpdate.value
  }

  // ============================================================================
  // WINDOW POSITION MEMORY
  // ============================================================================

  const POSITIONS_STORAGE_KEY = 'nisystem-window-positions'

  function loadWindowPositions() {
    try {
      const saved = localStorage.getItem(POSITIONS_STORAGE_KEY)
      if (saved) {
        windowPositions.value = JSON.parse(saved)
      }
    } catch (e) {
      console.warn('[WINDOW SYNC] Failed to load window positions:', e)
    }
  }

  function saveWindowPositions() {
    try {
      localStorage.setItem(POSITIONS_STORAGE_KEY, JSON.stringify(windowPositions.value))
    } catch (e) {
      console.warn('[WINDOW SYNC] Failed to save window positions:', e)
    }
  }

  // Save current window position for a page
  function saveCurrentWindowPosition(pageId: string) {
    const pos: WindowPosition = {
      pageId,
      screenX: window.screenX,
      screenY: window.screenY,
      width: window.outerWidth,
      height: window.outerHeight
    }

    // Try to detect which screen we're on (requires permission)
    detectScreenIndex().then(index => {
      pos.screenIndex = index
      windowPositions.value[pageId] = pos
      saveWindowPositions()

      // Broadcast to other windows
      if (channel.value) {
        channel.value.postMessage({
          type: 'window-position',
          source: windowId,
          payload: pos,
          timestamp: Date.now()
        } as SyncMessage)
      }
    })
  }

  // Get saved position for a page
  function getWindowPosition(pageId: string): WindowPosition | null {
    return windowPositions.value[pageId] || null
  }

  // Open a page in a new window at its remembered position
  function openPageInWindow(pageId: string, pageName: string) {
    const savedPos = windowPositions.value[pageId]
    const url = new URL(window.location.href)
    url.searchParams.set('page', pageId)

    // Default position/size
    let features = 'width=1200,height=800'

    if (savedPos) {
      // Use saved position
      features = `width=${savedPos.width},height=${savedPos.height},left=${savedPos.screenX},top=${savedPos.screenY}`
    }

    const newWindow = window.open(url.toString(), `nisystem-${pageId}`, features)

    if (newWindow) {
      // Set window title
      newWindow.document.title = `${pageName} - NISystem`
    }

    return newWindow
  }

  // Detect which screen the window is on
  async function detectScreenIndex(): Promise<number | undefined> {
    try {
      // Window Management API (Chrome 100+, Edge 100+)
      if ('getScreenDetails' in window) {
        const screenDetails = await (window as unknown as { getScreenDetails: () => Promise<{ screens: Array<{ left: number; top: number; width: number; height: number }> }> }).getScreenDetails()
        const screens = screenDetails.screens

        // Find which screen contains the window center
        const windowCenterX = window.screenX + window.outerWidth / 2
        const windowCenterY = window.screenY + window.outerHeight / 2

        for (let i = 0; i < screens.length; i++) {
          const screen = screens[i]!
          if (
            windowCenterX >= screen.left &&
            windowCenterX < screen.left + screen.width &&
            windowCenterY >= screen.top &&
            windowCenterY < screen.top + screen.height
          ) {
            return i
          }
        }
      }
    } catch (e) {
      // Permission denied or API not available
    }
    return undefined
  }

  // Track window position changes (call periodically or on resize/move)
  function trackWindowPosition(pageId: string) {
    // Debounce position saving
    let saveTimeout: ReturnType<typeof setTimeout> | null = null

    const savePosition = () => {
      if (saveTimeout) clearTimeout(saveTimeout)
      saveTimeout = setTimeout(() => {
        saveCurrentWindowPosition(pageId)
      }, 500)
    }

    // Listen for window move/resize
    window.addEventListener('resize', savePosition)

    // No direct 'move' event, but we can poll or use beforeunload
    window.addEventListener('beforeunload', () => {
      saveCurrentWindowPosition(pageId)
    })

    // Save initial position
    saveCurrentWindowPosition(pageId)

    return () => {
      window.removeEventListener('resize', savePosition)
    }
  }

  // Cleanup
  function destroy() {
    if (channel.value) {
      channel.value.close()
      channel.value = null
    }
  }

  return {
    // Initialization
    init,
    destroy,
    windowId,

    // Layout sync
    broadcastLayoutUpdate,
    broadcastEditMode,
    onLayoutUpdate,
    onEditModeChange,
    isReceiving,

    // Window position memory
    saveCurrentWindowPosition,
    getWindowPosition,
    openPageInWindow,
    trackWindowPosition,
    windowPositions
  }
}
