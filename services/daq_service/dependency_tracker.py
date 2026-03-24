"""
Dependency Tracker for NISystem
Tracks references between configuration entities to support safe deletion with user control.

Philosophy: Scientists need to see what will break and decide how to handle it.
- Cancel: Don't delete
- Delete Anyway: Delete target, leave orphaned references (show errors in UI)
- Delete + Clean Up: Delete target AND all dependents
"""

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Set
from enum import Enum
import re

class EntityType(Enum):
    CHASSIS = "chassis"
    MODULE = "module"
    CHANNEL = "channel"
    SAFETY_ACTION = "safety_action"
    FORMULA = "formula"
    ALARM = "alarm"
    WIDGET = "widget"

@dataclass
class EntityRef:
    """Reference to an entity"""
    entity_type: EntityType
    entity_id: str
    name: str
    context: str = ""  # Additional context like "used in expression" or "triggers action"

@dataclass
class DependencyInfo:
    """Complete dependency information for a delete operation"""

    # What is being deleted
    target: EntityRef

    # Direct children that will ALWAYS be deleted (cascade)
    # e.g., deleting a module always deletes its channels
    cascade_deletes: List[EntityRef] = field(default_factory=list)

    # Things that reference this (will be orphaned or cleaned based on user choice)
    dependents: Dict[str, List[EntityRef]] = field(default_factory=dict)

    # Summary for quick display
    @property
    def total_affected(self) -> int:
        count = len(self.cascade_deletes)
        for refs in self.dependents.values():
            count += len(refs)
        return count

    @property
    def has_dependencies(self) -> bool:
        return self.total_affected > 0

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict"""
        return {
            "target": {
                "type": self.target.entity_type.value,
                "id": self.target.entity_id,
                "name": self.target.name
            },
            "cascade_deletes": [
                {
                    "type": ref.entity_type.value,
                    "id": ref.entity_id,
                    "name": ref.name,
                    "context": ref.context
                }
                for ref in self.cascade_deletes
            ],
            "dependents": {
                category: [
                    {
                        "type": ref.entity_type.value,
                        "id": ref.entity_id,
                        "name": ref.name,
                        "context": ref.context
                    }
                    for ref in refs
                ]
                for category, refs in self.dependents.items()
            },
            "summary": {
                "total_affected": self.total_affected,
                "cascade_count": len(self.cascade_deletes),
                "dependent_count": sum(len(refs) for refs in self.dependents.values()),
                "has_dependencies": self.has_dependencies
            }
        }

@dataclass
class DeleteResult:
    """Result of a delete operation"""
    success: bool
    deleted: List[EntityRef] = field(default_factory=list)
    orphaned: List[EntityRef] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "deleted": [
                {"type": ref.entity_type.value, "id": ref.entity_id, "name": ref.name}
                for ref in self.deleted
            ],
            "orphaned": [
                {"type": ref.entity_type.value, "id": ref.entity_id, "name": ref.name, "context": ref.context}
                for ref in self.orphaned
            ],
            "errors": self.errors
        }

class DependencyTracker:
    """
    Tracks dependencies between configuration entities.

    Dependency Graph:

    Chassis
      └── Modules (module.chassis = "chassis_name")
            └── Channels (channel.module = "module_name")
                  ├── Formulas (formula references channel in expression)
                  ├── Alarms (alarm.source = "channel_name")
                  ├── Widgets (widget.sources includes channel)
                  └── Safety Actions (action.actions references channel)

    Safety Actions
      └── Channels (channel.safety_action = "action_name")
    """

    def __init__(self, config):
        """
        Initialize with an NISystemConfig object.

        Args:
            config: NISystemConfig with chassis, modules, channels, safety_actions
        """
        self.config = config

        # Future: these will come from a separate config/database
        self.formulas: Dict[str, dict] = {}  # name -> {expression, ...}
        self.alarms: Dict[str, dict] = {}    # name -> {source, condition, ...}
        self.widgets: Dict[str, dict] = {}   # name -> {sources: [...], ...}

    def set_formulas(self, formulas: Dict[str, dict]):
        """Set formula definitions for dependency tracking"""
        self.formulas = formulas

    def set_alarms(self, alarms: Dict[str, dict]):
        """Set alarm definitions for dependency tracking"""
        self.alarms = alarms

    def set_widgets(self, widgets: Dict[str, dict]):
        """Set widget definitions for dependency tracking"""
        self.widgets = widgets

    def refresh(self, config):
        """Refresh the dependency tracker with updated config"""
        self.config = config

    def get_dependencies(self, entity_type: EntityType, entity_id: str) -> DependencyInfo:
        """
        Get all dependencies for an entity before deletion.

        Args:
            entity_type: Type of entity (chassis, module, channel, etc.)
            entity_id: ID/name of the entity

        Returns:
            DependencyInfo with cascade deletes and dependents
        """
        if entity_type == EntityType.CHASSIS:
            return self._get_chassis_dependencies(entity_id)
        elif entity_type == EntityType.MODULE:
            return self._get_module_dependencies(entity_id)
        elif entity_type == EntityType.CHANNEL:
            return self._get_channel_dependencies(entity_id)
        elif entity_type == EntityType.SAFETY_ACTION:
            return self._get_safety_action_dependencies(entity_id)
        elif entity_type == EntityType.FORMULA:
            return self._get_formula_dependencies(entity_id)
        elif entity_type == EntityType.ALARM:
            return self._get_alarm_dependencies(entity_id)
        elif entity_type == EntityType.WIDGET:
            return self._get_widget_dependencies(entity_id)
        else:
            raise ValueError(f"Unknown entity type: {entity_type}")

    def _get_chassis_dependencies(self, chassis_id: str) -> DependencyInfo:
        """Get dependencies for a chassis"""
        chassis = self.config.chassis.get(chassis_id)
        if not chassis:
            raise ValueError(f"Chassis not found: {chassis_id}")

        info = DependencyInfo(
            target=EntityRef(EntityType.CHASSIS, chassis_id, chassis_id)
        )

        # Find all modules in this chassis (cascade delete)
        for mod_name, module in self.config.modules.items():
            if module.chassis == chassis_id:
                info.cascade_deletes.append(
                    EntityRef(EntityType.MODULE, mod_name, mod_name,
                             f"in slot {module.slot}")
                )

                # Also add channels from this module to cascade
                for ch_name, channel in self.config.channels.items():
                    if channel.module == mod_name:
                        info.cascade_deletes.append(
                            EntityRef(EntityType.CHANNEL, ch_name, ch_name,
                                     f"on {mod_name}")
                        )

        # Get dependents for all cascade-deleted channels
        all_channel_deps = self._collect_channel_dependents(
            [ref.entity_id for ref in info.cascade_deletes
             if ref.entity_type == EntityType.CHANNEL]
        )
        info.dependents = all_channel_deps

        return info

    def _get_module_dependencies(self, module_id: str) -> DependencyInfo:
        """Get dependencies for a module"""
        module = self.config.modules.get(module_id)
        if not module:
            raise ValueError(f"Module not found: {module_id}")

        info = DependencyInfo(
            target=EntityRef(EntityType.MODULE, module_id, module_id,
                           f"slot {module.slot} on {module.chassis}")
        )

        # Find all channels on this module (cascade delete)
        channel_ids = []
        for ch_name, channel in self.config.channels.items():
            if channel.module == module_id:
                info.cascade_deletes.append(
                    EntityRef(EntityType.CHANNEL, ch_name, ch_name,
                             channel.description or channel.physical_channel)
                )
                channel_ids.append(ch_name)

        # Get dependents for all cascade-deleted channels
        info.dependents = self._collect_channel_dependents(channel_ids)

        return info

    def _get_channel_dependencies(self, channel_id: str) -> DependencyInfo:
        """Get dependencies for a channel"""
        channel = self.config.channels.get(channel_id)
        if not channel:
            raise ValueError(f"Channel not found: {channel_id}")

        info = DependencyInfo(
            target=EntityRef(EntityType.CHANNEL, channel_id, channel_id,
                           channel.description or "")
        )

        # Get all things that reference this channel
        info.dependents = self._collect_channel_dependents([channel_id])

        return info

    def _collect_channel_dependents(self, channel_ids: List[str]) -> Dict[str, List[EntityRef]]:
        """Collect all entities that depend on the given channels"""
        dependents: Dict[str, List[EntityRef]] = {
            "formulas": [],
            "alarms": [],
            "widgets": [],
            "safety_actions": []
        }

        channel_set = set(channel_ids)

        # Check formulas for channel references
        for formula_name, formula in self.formulas.items():
            expression = formula.get("expression", "")
            referenced = self._extract_channel_refs(expression)
            overlap = referenced & channel_set
            if overlap:
                dependents["formulas"].append(
                    EntityRef(EntityType.FORMULA, formula_name, formula_name,
                             f"uses {', '.join(sorted(overlap))} in: {expression}")
                )

        # Check alarms for channel references
        for alarm_name, alarm in self.alarms.items():
            source = alarm.get("source", "")
            if source in channel_set:
                condition = alarm.get("condition", "")
                dependents["alarms"].append(
                    EntityRef(EntityType.ALARM, alarm_name, alarm_name,
                             f"monitors {source}: {condition}")
                )

        # Check widgets for channel references
        for widget_name, widget in self.widgets.items():
            sources = widget.get("sources", [])
            if isinstance(sources, str):
                sources = [sources]
            overlap = set(sources) & channel_set
            if overlap:
                widget_type = widget.get("type", "widget")
                dashboard = widget.get("dashboard", "")
                dependents["widgets"].append(
                    EntityRef(EntityType.WIDGET, widget_name, widget_name,
                             f"{widget_type} on '{dashboard}' displays {', '.join(sorted(overlap))}")
                )

        # Check safety actions for channel references in their actions
        for action_name, action in self.config.safety_actions.items():
            # action.actions is a dict like {"F1_Heater_Enable": False, ...}
            referenced_channels = set(action.actions.keys())
            overlap = referenced_channels & channel_set
            if overlap:
                action_strs = [f"{ch}:{action.actions[ch]}" for ch in sorted(overlap)]
                dependents["safety_actions"].append(
                    EntityRef(EntityType.SAFETY_ACTION, action_name, action_name,
                             f"sets {', '.join(action_strs)}")
                )

        # Remove empty categories
        return {k: v for k, v in dependents.items() if v}

    def _get_safety_action_dependencies(self, action_id: str) -> DependencyInfo:
        """Get dependencies for a safety action"""
        action = self.config.safety_actions.get(action_id)
        if not action:
            raise ValueError(f"Safety action not found: {action_id}")

        info = DependencyInfo(
            target=EntityRef(EntityType.SAFETY_ACTION, action_id, action_id,
                           action.description or "")
        )

        # Find channels that reference this safety action
        channels_using = []
        for ch_name, channel in self.config.channels.items():
            if channel.safety_action == action_id:
                channels_using.append(
                    EntityRef(EntityType.CHANNEL, ch_name, ch_name,
                             f"triggers on limit violation (limits: {channel.low_limit} - {channel.high_limit})")
                )

        if channels_using:
            info.dependents["channels"] = channels_using

        return info

    def _get_formula_dependencies(self, formula_id: str) -> DependencyInfo:
        """Get dependencies for a formula"""
        formula = self.formulas.get(formula_id)
        if not formula:
            raise ValueError(f"Formula not found: {formula_id}")

        info = DependencyInfo(
            target=EntityRef(EntityType.FORMULA, formula_id, formula_id,
                           formula.get("expression", ""))
        )

        # Formulas can be used by alarms and widgets
        dependents: Dict[str, List[EntityRef]] = {}

        # Check alarms
        alarms_using = []
        for alarm_name, alarm in self.alarms.items():
            if alarm.get("source") == formula_id:
                alarms_using.append(
                    EntityRef(EntityType.ALARM, alarm_name, alarm_name,
                             alarm.get("condition", ""))
                )
        if alarms_using:
            dependents["alarms"] = alarms_using

        # Check widgets
        widgets_using = []
        for widget_name, widget in self.widgets.items():
            sources = widget.get("sources", [])
            if isinstance(sources, str):
                sources = [sources]
            if formula_id in sources:
                widgets_using.append(
                    EntityRef(EntityType.WIDGET, widget_name, widget_name,
                             f"{widget.get('type', 'widget')} on '{widget.get('dashboard', '')}'")
                )
        if widgets_using:
            dependents["widgets"] = widgets_using

        info.dependents = dependents
        return info

    def _get_alarm_dependencies(self, alarm_id: str) -> DependencyInfo:
        """Get dependencies for an alarm"""
        alarm = self.alarms.get(alarm_id)
        if not alarm:
            raise ValueError(f"Alarm not found: {alarm_id}")

        # Alarms typically don't have dependents (they're leaf nodes)
        return DependencyInfo(
            target=EntityRef(EntityType.ALARM, alarm_id, alarm_id,
                           f"monitors {alarm.get('source', '?')}")
        )

    def _get_widget_dependencies(self, widget_id: str) -> DependencyInfo:
        """Get dependencies for a widget"""
        widget = self.widgets.get(widget_id)
        if not widget:
            raise ValueError(f"Widget not found: {widget_id}")

        # Widgets are leaf nodes, no dependents
        return DependencyInfo(
            target=EntityRef(EntityType.WIDGET, widget_id, widget_id,
                           f"{widget.get('type', 'widget')} on '{widget.get('dashboard', '')}'")
        )

    def _extract_channel_refs(self, expression: str) -> Set[str]:
        """
        Extract channel/formula references from an expression.

        Handles expressions like:
        - (F1_Zone1_Temp + F1_Zone2_Temp) / 2
        - Avg_Temp - Ambient_Temp
        - F1_Zone1_Temp > 500 ? 1 : 0
        """
        if not expression:
            return set()

        # Match identifiers (alphanumeric + underscore, starting with letter/underscore)
        # Exclude common keywords and numbers
        pattern = r'\b([A-Za-z_][A-Za-z0-9_]*)\b'
        matches = re.findall(pattern, expression)

        # Filter out keywords and operators
        keywords = {'true', 'false', 'if', 'else', 'and', 'or', 'not',
                   'min', 'max', 'abs', 'sqrt', 'sin', 'cos', 'tan', 'log', 'exp'}

        refs = set()
        for match in matches:
            if match.lower() not in keywords and not match.isdigit():
                # Check if it's a known channel or formula
                if match in self.config.channels or match in self.formulas:
                    refs.add(match)

        return refs

    def find_orphaned_references(self) -> Dict[str, List[EntityRef]]:
        """
        Scan all entities and find references to things that don't exist.

        Returns:
            Dict mapping entity IDs to list of broken references
        """
        orphans: Dict[str, List[EntityRef]] = {}

        # Check channels for missing modules
        for ch_name, channel in self.config.channels.items():
            if channel.module not in self.config.modules:
                if ch_name not in orphans:
                    orphans[ch_name] = []
                orphans[ch_name].append(
                    EntityRef(EntityType.MODULE, channel.module, channel.module,
                             "module not found")
                )

            # Check for missing safety action
            if channel.safety_action and channel.safety_action not in self.config.safety_actions:
                if ch_name not in orphans:
                    orphans[ch_name] = []
                orphans[ch_name].append(
                    EntityRef(EntityType.SAFETY_ACTION, channel.safety_action,
                             channel.safety_action, "safety action not found")
                )

        # Check modules for missing chassis
        for mod_name, module in self.config.modules.items():
            if module.chassis not in self.config.chassis:
                if mod_name not in orphans:
                    orphans[mod_name] = []
                orphans[mod_name].append(
                    EntityRef(EntityType.CHASSIS, module.chassis, module.chassis,
                             "chassis not found")
                )

        # Check formulas for missing channels
        for formula_name, formula in self.formulas.items():
            expression = formula.get("expression", "")
            refs = self._extract_channel_refs(expression)
            for ref in refs:
                if ref not in self.config.channels and ref not in self.formulas:
                    if formula_name not in orphans:
                        orphans[formula_name] = []
                    orphans[formula_name].append(
                        EntityRef(EntityType.CHANNEL, ref, ref,
                                 f"referenced in expression: {expression}")
                    )

        # Check alarms for missing sources
        for alarm_name, alarm in self.alarms.items():
            source = alarm.get("source", "")
            if source and source not in self.config.channels and source not in self.formulas:
                if alarm_name not in orphans:
                    orphans[alarm_name] = []
                orphans[alarm_name].append(
                    EntityRef(EntityType.CHANNEL, source, source,
                             "alarm source not found")
                )

        # Check widgets for missing sources
        for widget_name, widget in self.widgets.items():
            sources = widget.get("sources", [])
            if isinstance(sources, str):
                sources = [sources]
            for source in sources:
                if source and source not in self.config.channels and source not in self.formulas:
                    if widget_name not in orphans:
                        orphans[widget_name] = []
                    orphans[widget_name].append(
                        EntityRef(EntityType.CHANNEL, source, source,
                                 "widget source not found")
                    )

        # Check safety actions for missing channels in actions
        for action_name, action in self.config.safety_actions.items():
            for channel_ref in action.actions.keys():
                if channel_ref not in self.config.channels:
                    if action_name not in orphans:
                        orphans[action_name] = []
                    orphans[action_name].append(
                        EntityRef(EntityType.CHANNEL, channel_ref, channel_ref,
                                 f"channel in action not found")
                    )

        return orphans

    def validate_config(self) -> Dict[str, Any]:
        """
        Validate the current configuration and return a report.

        Returns:
            Dict with validation results including orphans and warnings
        """
        orphans = self.find_orphaned_references()

        warnings = []

        # Check for channels without safety actions that have limits
        for ch_name, channel in self.config.channels.items():
            if (channel.high_limit is not None or channel.low_limit is not None):
                if not channel.safety_action:
                    warnings.append({
                        "type": "no_safety_action",
                        "entity": ch_name,
                        "message": f"Channel has limits but no safety action"
                    })

        # Check for unused safety actions
        used_actions = set()
        for channel in self.config.channels.values():
            if channel.safety_action:
                used_actions.add(channel.safety_action)

        for action_name in self.config.safety_actions.keys():
            if action_name not in used_actions:
                warnings.append({
                    "type": "unused_safety_action",
                    "entity": action_name,
                    "message": "Safety action is defined but not used by any channel"
                })

        return {
            "valid": len(orphans) == 0,
            "orphans": {
                entity_id: [
                    {"type": ref.entity_type.value, "id": ref.entity_id, "context": ref.context}
                    for ref in refs
                ]
                for entity_id, refs in orphans.items()
            },
            "orphan_count": sum(len(refs) for refs in orphans.values()),
            "warnings": warnings,
            "warning_count": len(warnings)
        }

    def delete_with_strategy(
        self,
        entity_type: EntityType,
        entity_id: str,
        strategy: str  # "delete_only" or "delete_and_cleanup"
    ) -> DeleteResult:
        """
        Delete an entity with the specified strategy.

        Args:
            entity_type: Type of entity to delete
            entity_id: ID of entity to delete
            strategy: "delete_only" (leave orphans) or "delete_and_cleanup" (remove all dependents)

        Returns:
            DeleteResult with what was deleted/orphaned
        """
        if strategy not in ("delete_only", "delete_and_cleanup"):
            return DeleteResult(
                success=False,
                errors=[f"Invalid strategy: {strategy}. Use 'delete_only' or 'delete_and_cleanup'"]
            )

        # Get dependencies first
        try:
            deps = self.get_dependencies(entity_type, entity_id)
        except ValueError as e:
            return DeleteResult(success=False, errors=[str(e)])

        result = DeleteResult(success=True)

        # Delete cascade items first (always deleted regardless of strategy)
        for ref in deps.cascade_deletes:
            delete_ok = self._delete_entity(ref.entity_type, ref.entity_id)
            if delete_ok:
                result.deleted.append(ref)
            else:
                result.errors.append(f"Failed to delete {ref.entity_type.value}: {ref.entity_id}")

        # Handle dependents based on strategy
        if strategy == "delete_and_cleanup":
            # Delete all dependents
            for category, refs in deps.dependents.items():
                for ref in refs:
                    delete_ok = self._delete_entity(ref.entity_type, ref.entity_id)
                    if delete_ok:
                        result.deleted.append(ref)
                    else:
                        result.errors.append(f"Failed to delete {ref.entity_type.value}: {ref.entity_id}")
        else:
            # Just mark them as orphaned
            for category, refs in deps.dependents.items():
                for ref in refs:
                    result.orphaned.append(ref)

        # Finally delete the target itself
        delete_ok = self._delete_entity(entity_type, entity_id)
        if delete_ok:
            result.deleted.append(deps.target)
        else:
            result.success = False
            result.errors.append(f"Failed to delete target {entity_type.value}: {entity_id}")

        return result

    def _delete_entity(self, entity_type: EntityType, entity_id: str) -> bool:
        """
        Actually delete an entity from config.

        Returns True if successful, False otherwise.
        """
        try:
            if entity_type == EntityType.CHASSIS:
                if entity_id in self.config.chassis:
                    del self.config.chassis[entity_id]
                    return True

            elif entity_type == EntityType.MODULE:
                if entity_id in self.config.modules:
                    del self.config.modules[entity_id]
                    return True

            elif entity_type == EntityType.CHANNEL:
                if entity_id in self.config.channels:
                    del self.config.channels[entity_id]
                    return True

            elif entity_type == EntityType.SAFETY_ACTION:
                if entity_id in self.config.safety_actions:
                    del self.config.safety_actions[entity_id]
                    return True
                # Also clear references from channels
                for channel in self.config.channels.values():
                    if channel.safety_action == entity_id:
                        channel.safety_action = None

            elif entity_type == EntityType.FORMULA:
                if entity_id in self.formulas:
                    del self.formulas[entity_id]
                    return True

            elif entity_type == EntityType.ALARM:
                if entity_id in self.alarms:
                    del self.alarms[entity_id]
                    return True

            elif entity_type == EntityType.WIDGET:
                if entity_id in self.widgets:
                    del self.widgets[entity_id]
                    return True

            return False

        except Exception as e:
            return False

    def clear_orphaned_reference(
        self,
        entity_id: str,
        orphan_type: EntityType,
        orphan_id: str
    ) -> bool:
        """
        Clear a specific orphaned reference from an entity.

        For example, if a formula references a deleted channel,
        this can remove that reference from the formula.

        Args:
            entity_id: The entity containing the orphan reference
            orphan_type: Type of the orphaned reference
            orphan_id: ID of the orphaned reference

        Returns:
            True if cleared successfully
        """
        # Handle channel with missing safety action
        if entity_id in self.config.channels:
            channel = self.config.channels[entity_id]
            if orphan_type == EntityType.SAFETY_ACTION and channel.safety_action == orphan_id:
                channel.safety_action = None
                return True

        # Handle formula with missing channel reference
        if entity_id in self.formulas:
            formula = self.formulas[entity_id]
            # Can't easily remove a reference from expression without breaking it
            # Best to delete the whole formula or let user edit it
            return False

        # Handle alarm with missing source
        if entity_id in self.alarms:
            alarm = self.alarms[entity_id]
            if alarm.get("source") == orphan_id:
                # Can't have alarm without source, would need to delete
                return False

        # Handle widget with missing source
        if entity_id in self.widgets:
            widget = self.widgets[entity_id]
            sources = widget.get("sources", [])
            if isinstance(sources, str):
                sources = [sources]
            if orphan_id in sources:
                sources.remove(orphan_id)
                widget["sources"] = sources
                return True

        # Handle safety action with missing channel in actions
        if entity_id in self.config.safety_actions:
            action = self.config.safety_actions[entity_id]
            if orphan_id in action.actions:
                del action.actions[orphan_id]
                return True

        return False
