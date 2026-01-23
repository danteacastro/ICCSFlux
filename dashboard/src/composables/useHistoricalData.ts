/**
 * useHistoricalData - Composable for loading and managing historical recording data
 *
 * Provides reactive access to recorded data files with support for:
 * - Listing available recordings
 * - Loading file metadata
 * - Loading data with time filtering and decimation
 * - Lazy loading for large files (range-based loading)
 */

import { ref, computed, shallowRef } from 'vue'
import { useMqtt } from './useMqtt'

// Types
export interface RecordingFile {
  name: string
  path: string
  size: number
  duration: number
  created: string
  modified?: string
  sample_count: number
  channels: string[]
}

export interface FileInfo {
  success: boolean
  error: string | null
  filename: string
  path: string | null
  size_bytes: number
  channels: string[]
  sample_count: number
  start_time: string | null
  end_time: string | null
  duration_seconds: number
  sample_rate_hz: number
}

export interface HistoricalDataPoint {
  timestamp: string
  values: Record<string, number | null>
}

export interface HistoricalData {
  success: boolean
  error: string | null
  filename: string
  channels: string[]
  data: HistoricalDataPoint[]
  start_time: string | null
  end_time: string | null
  sample_count: number
  total_samples: number
}

export interface LoadOptions {
  start_time?: string
  end_time?: string
  channels?: string[]
  decimation?: number
  max_samples?: number
}

export interface RangeLoadOptions {
  start_sample?: number
  end_sample?: number
  channels?: string[]
}

// Singleton state
const recordings = ref<RecordingFile[]>([])
const isLoadingList = ref(false)
const isLoadingData = ref(false)
const currentFile = ref<FileInfo | null>(null)
const currentData = shallowRef<HistoricalData | null>(null)
const error = ref<string | null>(null)

// Response handlers (will be set up on first use)
let responseHandlersInitialized = false
let pendingResolvers: {
  list?: (files: RecordingFile[]) => void
  fileInfo?: (info: FileInfo) => void
  read?: (data: HistoricalData) => void
} = {}

export function useHistoricalData() {
  const mqtt = useMqtt('nisystem')

  // Initialize response handlers once
  if (!responseHandlersInitialized && mqtt.connected.value) {
    initResponseHandlers()
  }

  function initResponseHandlers() {
    if (responseHandlersInitialized) return

    // Subscribe to recording list responses
    mqtt.subscribe('nisystem/recording/files', (payload: any) => {
      if (Array.isArray(payload)) {
        recordings.value = payload
        isLoadingList.value = false
        if (pendingResolvers.list) {
          pendingResolvers.list(payload)
          pendingResolvers.list = undefined
        }
      }
    })

    // Subscribe to recording read responses
    mqtt.subscribe('nisystem/recording/read/response', (payload: any) => {
      isLoadingData.value = false

      if (payload && typeof payload === 'object') {
        // Check if this is a file info response or data response
        if ('size_bytes' in payload) {
          // File info response
          currentFile.value = payload as FileInfo
          if (pendingResolvers.fileInfo) {
            pendingResolvers.fileInfo(payload as FileInfo)
            pendingResolvers.fileInfo = undefined
          }
        } else if ('data' in payload) {
          // Data response
          currentData.value = payload as HistoricalData
          if (!payload.success) {
            error.value = payload.error || 'Unknown error loading data'
          } else {
            error.value = null
          }
          if (pendingResolvers.read) {
            pendingResolvers.read(payload as HistoricalData)
            pendingResolvers.read = undefined
          }
        }
      }
    })

    responseHandlersInitialized = true
  }

  /**
   * Load list of available recording files
   */
  async function loadRecordings(): Promise<RecordingFile[]> {
    if (!mqtt.connected.value) {
      error.value = 'MQTT not connected'
      return []
    }

    initResponseHandlers()
    isLoadingList.value = true
    error.value = null

    return new Promise((resolve) => {
      pendingResolvers.list = resolve

      // Request file list
      mqtt.sendCommand('recording/list', {})

      // Timeout after 10 seconds
      setTimeout(() => {
        if (pendingResolvers.list) {
          pendingResolvers.list = undefined
          isLoadingList.value = false
          error.value = 'Timeout loading recordings'
          resolve([])
        }
      }, 10000)
    })
  }

  /**
   * Get metadata about a specific file
   */
  async function getFileInfo(filename: string): Promise<FileInfo | null> {
    if (!mqtt.connected.value) {
      error.value = 'MQTT not connected'
      return null
    }

    initResponseHandlers()
    isLoadingData.value = true
    error.value = null

    return new Promise((resolve) => {
      pendingResolvers.fileInfo = resolve

      mqtt.sendCommand('recording/file-info', { filename })

      setTimeout(() => {
        if (pendingResolvers.fileInfo) {
          pendingResolvers.fileInfo = undefined
          isLoadingData.value = false
          error.value = 'Timeout loading file info'
          resolve(null)
        }
      }, 10000)
    })
  }

  /**
   * Load data from a recording file with optional filtering
   */
  async function loadFileData(
    filename: string,
    options: LoadOptions = {}
  ): Promise<HistoricalData | null> {
    if (!mqtt.connected.value) {
      error.value = 'MQTT not connected'
      return null
    }

    initResponseHandlers()
    isLoadingData.value = true
    error.value = null
    currentData.value = null

    return new Promise((resolve) => {
      pendingResolvers.read = resolve

      mqtt.sendCommand('recording/read', {
        filename,
        start_time: options.start_time,
        end_time: options.end_time,
        channels: options.channels,
        decimation: options.decimation ?? 1,
        max_samples: options.max_samples ?? 50000
      })

      setTimeout(() => {
        if (pendingResolvers.read) {
          pendingResolvers.read = undefined
          isLoadingData.value = false
          error.value = 'Timeout loading file data'
          resolve(null)
        }
      }, 30000) // Longer timeout for large files
    })
  }

  /**
   * Load a range of samples (for lazy loading large files)
   */
  async function loadFileRange(
    filename: string,
    options: RangeLoadOptions = {}
  ): Promise<HistoricalData | null> {
    if (!mqtt.connected.value) {
      error.value = 'MQTT not connected'
      return null
    }

    initResponseHandlers()
    isLoadingData.value = true
    error.value = null

    return new Promise((resolve) => {
      pendingResolvers.read = resolve

      mqtt.sendCommand('recording/read-range', {
        filename,
        start_sample: options.start_sample ?? 0,
        end_sample: options.end_sample,
        channels: options.channels
      })

      setTimeout(() => {
        if (pendingResolvers.read) {
          pendingResolvers.read = undefined
          isLoadingData.value = false
          error.value = 'Timeout loading file range'
          resolve(null)
        }
      }, 30000)
    })
  }

  /**
   * Convert historical data to chart-friendly format
   * Returns { timestamps: Date[], series: { [channel]: number[] } }
   */
  function toChartFormat(data: HistoricalData | null) {
    if (!data || !data.data.length) {
      return { timestamps: [], series: {} }
    }

    const timestamps: Date[] = []
    const series: Record<string, (number | null)[]> = {}

    // Initialize series arrays
    for (const channel of data.channels) {
      series[channel] = []
    }

    // Convert data points
    for (const point of data.data) {
      timestamps.push(new Date(point.timestamp))
      for (const channel of data.channels) {
        series[channel]?.push(point.values[channel] ?? null)
      }
    }

    return { timestamps, series }
  }

  /**
   * Get time range statistics for the current data
   */
  const dataTimeRange = computed(() => {
    if (!currentData.value || !currentData.value.start_time || !currentData.value.end_time) {
      return null
    }

    const start = new Date(currentData.value.start_time)
    const end = new Date(currentData.value.end_time)
    const durationMs = end.getTime() - start.getTime()

    return {
      start,
      end,
      durationMs,
      durationSeconds: durationMs / 1000,
      durationMinutes: durationMs / 60000,
      durationHours: durationMs / 3600000
    }
  })

  /**
   * Calculate optimal decimation for a target number of points
   */
  function calculateDecimation(totalSamples: number, targetPoints: number = 1000): number {
    if (totalSamples <= targetPoints) return 1
    return Math.ceil(totalSamples / targetPoints)
  }

  return {
    // State
    recordings,
    isLoadingList,
    isLoadingData,
    currentFile,
    currentData,
    error,

    // Computed
    dataTimeRange,

    // Methods
    loadRecordings,
    getFileInfo,
    loadFileData,
    loadFileRange,
    toChartFormat,
    calculateDecimation
  }
}
