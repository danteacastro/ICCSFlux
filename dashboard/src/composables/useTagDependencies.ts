/**
 * Tag Dependency Tracker
 *
 * Tracks all places where tags are referenced in the system:
 * - Python scripts (tags.TAG_NAME, outputs.set('TAG_NAME'))
 * - Safety/Safe State configurations
 * - Alarms
 * - Triggers
 * - Watchdogs
 * - Calculated parameters/formulas
 * - Recording channel selection
 *
 * Used for:
 * - Validating tag renames (warn if tag is used elsewhere)
 * - Auto-updating references when a tag is renamed
 * - Finding orphaned references (tags that no longer exist)
 */

import { computed, ref } from 'vue'
import { useDashboardStore } from '../stores/dashboard'
import { useSafety } from './useSafety'
import { useBackendScripts } from './useBackendScripts'

export interface TagReference {
  type: 'script' | 'safety' | 'alarm' | 'trigger' | 'watchdog' | 'formula' | 'recording'
  id: string           // ID of the referencing item (script ID, alarm ID, etc.)
  name: string         // Human-readable name
  location: string     // Where in the item (e.g., "code line 5", "condition")
  context?: string     // Snippet of code/config showing the reference
}

export interface TagDependencyResult {
  tag: string
  references: TagReference[]
  count: number
}

// Regex patterns for finding tag references in Python scripts
const TAG_PATTERNS = {
  // tags.TAG_NAME or tags['TAG_NAME'] or tags["TAG_NAME"] or tags.get('TAG_NAME')
  tagsAccess: /tags\.([a-zA-Z_][a-zA-Z0-9_]*)|tags\[['"]([^'"]+)['"]\]|tags\.get\(['"]([^'"]+)['"]/g,
  // outputs.set('TAG_NAME', value) or outputs.set("TAG_NAME", value)
  outputsSet: /outputs\.set\(['"]([^'"]+)['"]/g,
  // wait_until(tags.TAG_NAME condition) - harder to parse, just look for tags. references
}

export function useTagDependencies() {
  const store = useDashboardStore()
  const safety = useSafety()
  const backendScripts = useBackendScripts()

  /**
   * Extract tag references from Python script code
   */
  function extractTagsFromScript(code: string): string[] {
    const tags = new Set<string>()

    // Reset regex lastIndex
    TAG_PATTERNS.tagsAccess.lastIndex = 0
    TAG_PATTERNS.outputsSet.lastIndex = 0

    // Find tags.X, tags['X'], tags.get('X')
    let match
    while ((match = TAG_PATTERNS.tagsAccess.exec(code)) !== null) {
      const tag = match[1] || match[2] || match[3]
      if (tag) tags.add(tag)
    }

    // Find outputs.set('X', ...)
    TAG_PATTERNS.outputsSet.lastIndex = 0
    while ((match = TAG_PATTERNS.outputsSet.exec(code)) !== null) {
      if (match[1]) tags.add(match[1])
    }

    return Array.from(tags)
  }

  /**
   * Get all references to a specific tag across the system
   */
  function getTagReferences(tagName: string): TagReference[] {
    const references: TagReference[] = []

    // 1. Check Python scripts from backend scripts composable
    const scripts = Object.values(backendScripts.scripts.value || {})
    for (const script of scripts) {
      if (!script.code) continue

      const scriptTags = extractTagsFromScript(script.code)
      if (scriptTags.includes(tagName)) {
        // Find the line(s) where this tag is referenced
        const lines = script.code.split('\n')
        lines.forEach((line: string, idx: number) => {
          if (line.includes(tagName)) {
            references.push({
              type: 'script',
              id: script.id,
              name: script.name,
              location: `line ${idx + 1}`,
              context: line.trim().substring(0, 60)
            })
          }
        })
      }
    }

    // 2. Check Safety/Safe State outputs from safety composable
    const safeStateConfig = safety.safeStateConfig?.value
    if (safeStateConfig) {
      // Check digital output channels in safe state config
      if (safeStateConfig.digitalOutputChannels?.includes(tagName)) {
        references.push({
          type: 'safety',
          id: tagName,
          name: 'Safe State - Digital Output',
          location: 'digitalOutputChannels',
          context: `reset to safe state on trip`
        })
      }
      // Check analog output channels in safe state config
      if (safeStateConfig.analogOutputChannels?.includes(tagName)) {
        references.push({
          type: 'safety',
          id: tagName,
          name: 'Safe State - Analog Output',
          location: 'analogOutputChannels',
          context: `reset to ${safeStateConfig.analogSafeValue} on trip`
        })
      }
    }

    // 3. Check Alarms from safety composable
    const alarms = safety.alarmConfigs?.value || {}
    for (const [alarmId, alarm] of Object.entries(alarms)) {
      if (alarm.channel === tagName) {
        references.push({
          type: 'alarm',
          id: alarmId,
          name: alarm.name || alarmId,
          location: 'monitored tag',
          context: `monitors ${tagName}`
        })
      }
    }

    // 4. Check Interlocks from safety composable
    const interlocks = safety.interlocks?.value || []
    for (const interlock of interlocks) {
      // Check conditions
      for (const condition of interlock.conditions || []) {
        if (condition.channel === tagName) {
          references.push({
            type: 'trigger',
            id: interlock.id,
            name: interlock.name || interlock.id,
            location: 'interlock condition',
            context: `${condition.channel} ${condition.operator} ${condition.value}`
          })
        }
      }
    }

    // 5. Check Recording selection
    if (store.selectedRecordingChannels?.includes(tagName)) {
      references.push({
        type: 'recording',
        id: 'recording',
        name: 'Recording Configuration',
        location: 'selected channels',
        context: 'selected for recording'
      })
    }

    return references
  }

  /**
   * Get all tag dependencies in the system
   */
  function getAllTagDependencies(): TagDependencyResult[] {
    const results: TagDependencyResult[] = []
    const channelNames = Object.keys(store.channels || {})

    for (const tagName of channelNames) {
      const refs = getTagReferences(tagName)
      if (refs.length > 0) {
        results.push({
          tag: tagName,
          references: refs,
          count: refs.length
        })
      }
    }

    return results.sort((a, b) => b.count - a.count)
  }

  /**
   * Find orphaned references (references to tags that don't exist)
   */
  function findOrphanedReferences(): TagReference[] {
    const orphans: TagReference[] = []
    const channelNames = new Set(Object.keys(store.channels || {}))

    // Check Python scripts for references to non-existent tags
    const scripts = Object.values(backendScripts.scripts.value || {})
    for (const script of scripts) {
      if (!script.code) continue

      const scriptTags = extractTagsFromScript(script.code)
      for (const tag of scriptTags) {
        if (!channelNames.has(tag)) {
          const lines = script.code.split('\n')
          lines.forEach((line: string, idx: number) => {
            if (line.includes(tag)) {
              orphans.push({
                type: 'script',
                id: script.id,
                name: script.name,
                location: `line ${idx + 1}`,
                context: `${tag} (not found)`
              })
            }
          })
        }
      }
    }

    // Check alarms from safety composable
    const alarms = safety.alarmConfigs?.value || {}
    for (const [alarmId, alarm] of Object.entries(alarms)) {
      if (alarm.channel && !channelNames.has(alarm.channel)) {
        orphans.push({
          type: 'alarm',
          id: alarmId,
          name: alarm.name || alarmId,
          location: 'monitored tag',
          context: `${alarm.channel} (not found)`
        })
      }
    }

    // Check interlocks from safety composable
    const interlocks = safety.interlocks?.value || []
    for (const interlock of interlocks) {
      for (const condition of interlock.conditions || []) {
        if (condition.channel && !channelNames.has(condition.channel)) {
          orphans.push({
            type: 'trigger',
            id: interlock.id,
            name: interlock.name || interlock.id,
            location: 'interlock condition',
            context: `${condition.channel} (not found)`
          })
        }
      }
    }

    return orphans
  }

  /**
   * Validate a tag rename - returns references that would be affected
   */
  function validateTagRename(oldName: string, newName: string): {
    valid: boolean
    affectedReferences: TagReference[]
    warnings: string[]
  } {
    const warnings: string[] = []
    const refs = getTagReferences(oldName)

    // Check if new name already exists
    if (store.channels[newName]) {
      warnings.push(`Tag "${newName}" already exists`)
    }

    // Check if new name is valid (allows dashes for ISA-5.1 naming like PT-001)
    if (!/^[a-zA-Z_][a-zA-Z0-9_-]*$/.test(newName)) {
      warnings.push(`Tag name "${newName}" contains invalid characters`)
    }

    return {
      valid: warnings.length === 0,
      affectedReferences: refs,
      warnings
    }
  }

  /**
   * Update tag references in Python script code
   */
  function updateTagInScript(code: string, oldTag: string, newTag: string): string {
    // Replace tags.OLD_TAG with tags.NEW_TAG
    let updated = code.replace(
      new RegExp(`tags\\.${oldTag}\\b`, 'g'),
      `tags.${newTag}`
    )

    // Replace tags['OLD_TAG'] with tags['NEW_TAG']
    updated = updated.replace(
      new RegExp(`tags\\['${oldTag}'\\]`, 'g'),
      `tags['${newTag}']`
    )
    updated = updated.replace(
      new RegExp(`tags\\["${oldTag}"\\]`, 'g'),
      `tags["${newTag}"]`
    )

    // Replace tags.get('OLD_TAG') with tags.get('NEW_TAG')
    updated = updated.replace(
      new RegExp(`tags\\.get\\(['"]${oldTag}['"]`, 'g'),
      `tags.get('${newTag}'`
    )

    // Replace outputs.set('OLD_TAG', with outputs.set('NEW_TAG',
    updated = updated.replace(
      new RegExp(`outputs\\.set\\(['"]${oldTag}['"]`, 'g'),
      `outputs.set('${newTag}'`
    )

    return updated
  }

  /**
   * Get summary of tag usage for display
   */
  const tagUsageSummary = computed(() => {
    const summary: Record<string, number> = {}
    const channelNames = Object.keys(store.channels || {})

    for (const tag of channelNames) {
      summary[tag] = getTagReferences(tag).length
    }

    return summary
  })

  return {
    // Core functions
    getTagReferences,
    getAllTagDependencies,
    findOrphanedReferences,
    validateTagRename,
    updateTagInScript,
    extractTagsFromScript,

    // Computed
    tagUsageSummary
  }
}
