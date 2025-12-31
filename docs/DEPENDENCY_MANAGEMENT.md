# Dependency Management System

## Philosophy: Scientist-Friendly Deletion

When a scientist deletes something (channel, module, formula, etc.), they need to:
1. **See** exactly what depends on it
2. **Decide** what to do - not have the system decide for them
3. **Control** whether to leave orphans (fixable errors) or clean up everything

## Dependency Types

```
Chassis
  └── Modules (module.chassis = "chassis_name")
        └── Channels (channel.module = "module_name")
              ├── Formulas (formula references channel in expression)
              ├── Alarms (alarm.source = "channel_name" or "formula_name")
              ├── Widgets (widget.sources = ["channel_name", ...])
              └── Safety Actions (safety_action.actions = {channel: value})

Safety Actions
  └── Channels (channel.safety_action = "action_name")
```

## Deletion Scenarios

### Deleting a Channel

**Example: Delete `F1_Zone2_Temp` (thermocouple went bad)**

System shows:
```
⚠️ "F1_Zone2_Temp" is referenced by:

FORMULAS (1):
  • Avg_F1_Temp: (F1_Zone1_Temp + F1_Zone2_Temp + F1_Zone3_Temp) / 3

ALARMS (0):
  (none)

WIDGETS (2):
  • Dashboard "Furnace 1": Line chart "Zone Temps"
  • Dashboard "Overview": Gauge "F1 Zone 2"

SAFETY ACTIONS (1):
  • F1_overtemp: triggers when this channel exceeds high_limit

What would you like to do?

[Cancel]                    - Don't delete, go back
[Delete Anyway]             - Delete channel, leave broken references
[Delete + Clean Up All]     - Delete channel AND all items above
```

**"Delete Anyway" behavior:**
- Channel is deleted
- Formula `Avg_F1_Temp` shows error: "Missing channel: F1_Zone2_Temp"
- Widgets show "No data" or error state for that source
- Safety action continues to work (just won't trigger from this channel)
- Scientist can then manually fix each one

**"Delete + Clean Up All" behavior:**
- Channel is deleted
- Formula is deleted
- Widgets are deleted (or just that source removed?)
- Safety action reference is removed

### Deleting a Module

**Example: Delete `Slot1_FurnaceTC` (module failed, replacing with different type)**

System shows:
```
⚠️ "Slot1_FurnaceTC" has 8 channels that will also be deleted:

CHANNELS (8):
  • F1_Zone1_Temp
  • F1_Zone2_Temp
  • F1_Zone3_Temp
  • F1_Door_Temp
  • F2_Zone1_Temp
  • F2_Zone2_Temp
  • F2_Zone3_Temp
  • F2_Door_Temp

These channels are referenced by:

FORMULAS (2):
  • Avg_F1_Temp
  • Avg_F2_Temp

WIDGETS (5):
  • Dashboard "Furnace 1": Line chart, Gauge x2
  • Dashboard "Furnace 2": Line chart, Gauge x2

SAFETY ACTIONS (2):
  • F1_overtemp (references 3 channels)
  • F2_overtemp (references 3 channels)

[Cancel]  [Delete Anyway]  [Delete + Clean Up All]
```

### Deleting a Safety Action

**Example: Delete `F1_overtemp`**

```
⚠️ "F1_overtemp" is used as safety_action by:

CHANNELS (3):
  • F1_Zone1_Temp (high_limit: 1000°C)
  • F1_Zone2_Temp (high_limit: 1000°C)
  • F1_Zone3_Temp (high_limit: 1000°C)

If deleted, these channels will have NO safety action when limits are exceeded.

[Cancel]  [Delete Anyway]  [Delete + Clean Up All]
```

**"Delete Anyway"**: Channels keep their limits but `safety_action` field becomes orphaned/null
**"Delete + Clean Up"**: Channels have their `safety_action` field cleared

## Data Model for Dependencies

```typescript
interface DependencyInfo {
  // What is being deleted
  target: {
    type: 'channel' | 'module' | 'chassis' | 'formula' | 'alarm' | 'widget' | 'safety_action';
    id: string;
    name: string;
  };

  // Direct children that will be deleted too (cascading)
  cascadeDeletes: Array<{
    type: string;
    id: string;
    name: string;
  }>;

  // Things that reference this (will be orphaned or cleaned)
  dependents: {
    formulas: Array<{
      id: string;
      name: string;
      expression: string;  // Show them the formula so they understand impact
    }>;
    alarms: Array<{
      id: string;
      name: string;
      condition: string;
    }>;
    widgets: Array<{
      id: string;
      dashboard: string;
      widgetType: string;
      title: string;
    }>;
    safetyActions: Array<{
      id: string;
      name: string;
      usageContext: string;  // "triggers F1_Heater_Enable:false"
    }>;
    channels: Array<{
      id: string;
      name: string;
      referenceField: string;  // "safety_action" or "formula_source"
    }>;
  };

  // Summary counts for quick glance
  summary: {
    totalAffected: number;
    willCascadeDelete: number;
    willOrphan: number;
  };
}
```

## API Design

```typescript
// Check what would be affected before deletion
async function getDependencies(
  type: EntityType,
  id: string
): Promise<DependencyInfo>

// Perform deletion with chosen strategy
async function deleteWithStrategy(
  type: EntityType,
  id: string,
  strategy: 'cancel' | 'delete_only' | 'delete_and_cleanup'
): Promise<DeleteResult>

interface DeleteResult {
  success: boolean;
  deleted: Array<{type: string; id: string; name: string}>;
  orphaned: Array<{type: string; id: string; name: string; brokenRef: string}>;
  errors: string[];
}
```

## UI Component

```tsx
interface DeleteConfirmationModalProps {
  target: { type: string; id: string; name: string };
  dependencies: DependencyInfo;
  onCancel: () => void;
  onDeleteOnly: () => void;
  onDeleteAndCleanup: () => void;
}
```

The modal should:
1. Show the target being deleted prominently
2. Group dependents by type with expandable sections
3. Show expressions/conditions so scientist understands the impact
4. Make "Cancel" the default/safe action
5. Require explicit click for destructive actions
6. Maybe add a "Type DELETE to confirm" for delete+cleanup

## Orphan Recovery

When references become orphaned (after "Delete Anyway"):

1. **Visual indicator** - Red border, warning icon, "Missing: X" text
2. **Hover tooltip** - "This formula references 'F1_Zone2_Temp' which no longer exists"
3. **Quick fix options**:
   - "Replace with..." - Pick a different channel
   - "Remove reference" - Delete just this reference
   - "Delete this item" - Delete the whole formula/widget/etc.

## MQTT API

### Check Dependencies Before Delete

**Request:** `nisystem/dependencies/check`
```json
{
  "type": "channel",  // or "module", "chassis", "safety_action"
  "id": "F1_Zone2_Temp"
}
```

**Response:** `nisystem/dependencies/check/response`
```json
{
  "success": true,
  "dependencies": {
    "target": {"type": "channel", "id": "F1_Zone2_Temp", "name": "F1_Zone2_Temp"},
    "cascade_deletes": [],
    "dependents": {
      "formulas": [{"type": "formula", "id": "Avg_F1_Temp", "name": "Avg_F1_Temp", "context": "uses F1_Zone2_Temp"}],
      "widgets": [{"type": "widget", "id": "chart_1", "name": "chart_1", "context": "displays F1_Zone2_Temp"}]
    },
    "summary": {"total_affected": 2, "cascade_count": 0, "dependent_count": 2, "has_dependencies": true}
  }
}
```

### Delete With Strategy

**Request:** `nisystem/dependencies/delete`
```json
{
  "type": "channel",
  "id": "F1_Zone2_Temp",
  "strategy": "delete_only"  // or "delete_and_cleanup"
}
```

**Response:** `nisystem/dependencies/delete/response`
```json
{
  "success": true,
  "result": {
    "deleted": [{"type": "channel", "id": "F1_Zone2_Temp", "name": "F1_Zone2_Temp"}],
    "orphaned": [{"type": "formula", "id": "Avg_F1_Temp", "context": "uses F1_Zone2_Temp"}],
    "errors": []
  }
}
```

### Validate Config (Find All Orphans)

**Request:** `nisystem/dependencies/validate`

**Response:** `nisystem/dependencies/validate/response`
```json
{
  "success": true,
  "validation": {
    "valid": false,
    "orphans": {
      "Avg_F1_Temp": [{"type": "channel", "id": "F1_Zone2_Temp", "context": "referenced in expression"}]
    },
    "orphan_count": 1,
    "warnings": [{"type": "no_safety_action", "entity": "Test_Channel", "message": "Channel has limits but no safety action"}],
    "warning_count": 1
  }
}
```

### Get Orphaned References

**Request:** `nisystem/dependencies/orphans`

**Response:** `nisystem/dependencies/orphans/response`
```json
{
  "success": true,
  "orphans": {
    "Avg_F1_Temp": [{"type": "channel", "id": "F1_Zone2_Temp", "context": "referenced in expression"}]
  },
  "count": 1
}
```

## Implementation Status

### Backend (Python)
- [x] `DependencyTracker` class in `dependency_tracker.py`
- [x] `get_dependencies()` - find all references to an entity
- [x] `delete_with_strategy()` - delete with "delete_only" or "delete_and_cleanup"
- [x] `find_orphaned_references()` - scan for broken references
- [x] `validate_config()` - full validation with warnings
- [x] MQTT API integration in `daq_service.py`

### Frontend (TODO)
- [ ] `DeleteConfirmationModal` component
- [ ] Wire up delete buttons to check dependencies first
- [ ] Orphan indicators on entities with broken references
- [ ] Quick-fix actions for orphaned references
