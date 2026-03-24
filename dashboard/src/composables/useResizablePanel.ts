import { ref, onUnmounted } from 'vue'

interface UseResizablePanelOptions {
  side: 'left' | 'right'
  minWidth: number
  maxWidth: number
  getWidth: () => number
  setWidth: (w: number) => void
}

export function useResizablePanel(options: UseResizablePanelOptions) {
  const isResizing = ref(false)
  let startX = 0
  let startWidth = 0

  function onMouseDown(e: MouseEvent) {
    e.preventDefault()
    isResizing.value = true
    startX = e.clientX
    startWidth = options.getWidth()
    document.addEventListener('mousemove', onMouseMove)
    document.addEventListener('mouseup', onMouseUp)
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
  }

  function onMouseMove(e: MouseEvent) {
    if (!isResizing.value) return
    const deltaX = e.clientX - startX
    const newWidth = options.side === 'left'
      ? startWidth + deltaX
      : startWidth - deltaX
    options.setWidth(Math.max(options.minWidth, Math.min(options.maxWidth, newWidth)))
  }

  function onMouseUp() {
    isResizing.value = false
    document.removeEventListener('mousemove', onMouseMove)
    document.removeEventListener('mouseup', onMouseUp)
    document.body.style.cursor = ''
    document.body.style.userSelect = ''
  }

  onUnmounted(() => {
    document.removeEventListener('mousemove', onMouseMove)
    document.removeEventListener('mouseup', onMouseUp)
  })

  return { isResizing, onMouseDown }
}
