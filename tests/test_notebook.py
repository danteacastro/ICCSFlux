"""
Notebook System Tests

Verifies fixes from the notebook audit. Mike captures observations during
test runs; the notebook is the durable record. Silent failures here destroy
the audit trail.

Bugs fixed:
  CRITICAL
    - No delete function existed at all. Now deleteEntry/deleteExperiment
      with two-step confirm + reason prompt + archive to separate storage
      key for audit retrieval.
    - localStorage save errors silently swallowed → console.error only.
      Now sets lastSaveError ref; banner displays it.
    - MQTT file save was fire-and-forget. Now subscribes to the saved
      response, tracks savePending + lastSavedAt, has 8s ack timeout.
    - 2s autosave debounce + no unsaved-changes guard. Now flushPendingSave
      runs on beforeunload + visibilitychange:hidden + before each export.
    - onUnmounted cleared the module-singleton's saveTimeout on every
      component unmount, cancelling pending writes for live consumers.
      Removed; lifecycle moved to module-level page events.

  HIGH
    - PDF export inserted untrusted strings into HTML → stored XSS.
      Every user-derived value now goes through escapeHtml.
    - Markdown table cells with `|` broke the rendered table. Now
      escapeMarkdownCell escapes pipes, backslashes, and newlines.
    - File merge preferred file always, clobbering local edits. Now picks
      whichever side has the newer "last modified" (creation OR last
      amendment), order-independent.
    - 500ms hardcoded delay before loadFromFile raced subscribe setup.
      Replaced with subscribe-first then watch-driven load.
    - window.open() popup blocker silently failed. Now falls back to
      downloading the HTML file with a clear message.

  MEDIUM
    - Snapshot accepted NaN/Infinity. Now filters via Number.isFinite.
    - Template placeholders ({experiment}, {operator}, {date}, {time})
      were never substituted. Now applyTemplatePlaceholders replaces them.
    - Quick note title was always `Note - HH:MM:SS` (unsearchable).
      Now uses first non-empty content line, truncated to 60 chars.
"""

import pytest
from pathlib import Path


class TestNotebookComposableFixes:

    def _read(self):
        return (Path(__file__).parent.parent / "dashboard" / "src" / "composables" / "useNotebook.ts").read_text(encoding='utf-8')

    def _read_tab(self):
        return (Path(__file__).parent.parent / "dashboard" / "src" / "components" / "NotebookTab.vue").read_text(encoding='utf-8')

    def _read_types(self):
        return (Path(__file__).parent.parent / "dashboard" / "src" / "types" / "notebook.ts").read_text(encoding='utf-8')

    # --- CRITICAL: delete functions ---

    def test_delete_entry_function_exists(self):
        content = self._read()
        assert "function deleteEntry(id: string, reason: string)" in content

    def test_delete_experiment_function_exists(self):
        content = self._read()
        assert "function deleteExperiment(id: string, reason: string)" in content

    def test_delete_entry_appends_audit_amendment(self):
        """Deleted entries must be archived with a tombstone amendment so
        the audit trail records who/when/why."""
        content = self._read()
        idx = content.find("function deleteEntry")
        body = content[idx:idx + 1500]
        assert "tombstone" in body.lower() or "__deleted__" in body
        assert "archiveDeletedEntry" in body
        assert "entries.value.splice" in body

    def test_archive_keys_defined(self):
        types = self._read_types()
        assert "NOTEBOOK_ARCHIVE_KEY" in types
        assert "EXPERIMENTS_ARCHIVE_KEY" in types

    def test_delete_buttons_in_ui(self):
        content = self._read_tab()
        assert "entry-delete-btn" in content
        assert "exp-delete-btn" in content
        # Click handler must call our wrapper which prompts for reason
        assert "deleteEntry(entry.id" in content
        assert "deleteExperiment(exp.id" in content

    def test_delete_ui_requires_reason(self):
        content = self._read_tab()
        # The wrapper must prompt for a reason (audit requirement)
        idx = content.find("function deleteEntry(id: string")
        body = content[idx:idx + 600]
        assert "prompt(" in body
        assert "required" in body.lower()

    # --- CRITICAL: error state surfaced ---

    def test_save_error_ref_exposed(self):
        content = self._read()
        assert "lastSaveError = ref" in content
        assert "savePending = ref" in content
        assert "lastSavedAt = ref" in content
        # Returned from composable
        assert "lastSaveError," in content
        assert "savePending," in content

    def test_localstorage_failure_sets_error(self):
        content = self._read()
        idx = content.find("function saveEntries")
        body = content[idx:idx + 500]
        assert "lastSaveError.value =" in body, "Local save failure must set error ref"

    def test_save_status_banner_in_ui(self):
        content = self._read_tab()
        assert "save-status-banner" in content
        # All three states wired
        assert 'class="save-status-banner error"' in content
        assert 'class="save-status-banner pending"' in content
        assert 'class="save-status-banner ok"' in content

    def test_mqtt_save_response_handler(self):
        content = self._read()
        assert "function handleNotebookSaved" in content
        assert "nisystem/notebook/saved" in content
        # Must subscribe to the response
        idx = content.find("function initialize")
        body = content[idx:idx + 1500]
        assert "subscribe('nisystem/notebook/saved', handleNotebookSaved)" in body

    def test_save_ack_timeout(self):
        content = self._read()
        assert "saveAckTimeout" in content
        # Must clear pending state on timeout
        idx = content.find("saveAckTimeout = window.setTimeout")
        body = content[idx:idx + 500]
        assert "lastSaveError.value" in body
        assert "savePending.value = false" in body

    # --- CRITICAL: flush on page lifecycle ---

    def test_flush_pending_save_function(self):
        content = self._read()
        assert "function flushPendingSave" in content

    def test_flush_called_before_export(self):
        content = self._read()
        for fn in ("function exportToPdf", "function exportToMarkdown", "function exportToText"):
            idx = content.find(fn)
            body = content[idx:idx + 200]
            assert "flushPendingSave()" in body, f"{fn} must flush before exporting"

    def test_beforeunload_listener_registered(self):
        content = self._read()
        assert "beforeunload" in content
        assert "flushPendingSave" in content
        # Visibility change is a more reliable signal on mobile
        assert "visibilitychange" in content
        assert "visibilityState === 'hidden'" in content

    def test_listeners_registered_once(self):
        content = self._read()
        assert "listenersRegistered" in content
        # Guarded against double-registration
        idx = content.find("listenersRegistered")
        body = content[idx:idx + 800]
        assert "if (!listenersRegistered" in content

    # --- CRITICAL: singleton lifecycle ---

    def test_no_onunmounted_clobber(self):
        """onUnmounted clearing saveTimeout on every component unmount was
        the bug — must be removed."""
        content = self._read()
        # We don't import or use onUnmounted anywhere
        assert "onUnmounted" not in content

    def test_save_timeout_module_level(self):
        content = self._read()
        # Module-level let, not inside the useNotebook closure
        # Find first occurrence; it should be before `export function useNotebook`
        first = content.find("let saveTimeout")
        export_idx = content.find("export function useNotebook")
        assert first > 0 and first < export_idx, \
            "saveTimeout must live at module scope so it survives component unmount"

    # --- HIGH: HTML escape ---

    def test_escape_html_helper_exists(self):
        content = self._read()
        assert "function escapeHtml" in content
        # Must escape all five dangerous chars
        idx = content.find("function escapeHtml")
        body = content[idx:idx + 400]
        assert "&amp;" in body
        assert "&lt;" in body
        assert "&gt;" in body
        assert "&quot;" in body
        assert "&#39;" in body

    def test_pdf_export_uses_escape_html(self):
        content = self._read()
        idx = content.find("function buildExportHtml")
        body = content[idx:idx + 3000]
        # Title, time, content, tags, and snapshot fields must all be escaped
        assert "escapeHtml(e.title)" in body
        assert "escapeHtml(e.content)" in body
        assert "escapeHtml(t)" in body  # tags
        assert "escapeHtml(ch)" in body  # channel name
        assert "escapeHtml(v.unit)" in body  # unit

    # --- HIGH: markdown pipe escape ---

    def test_markdown_cell_escape_helper(self):
        content = self._read()
        assert "function escapeMarkdownCell" in content
        idx = content.find("function escapeMarkdownCell")
        body = content[idx:idx + 300]
        # Must escape pipe
        assert "\\\\|" in body or "\\|" in body
        # Must collapse newlines so they don't break rows
        assert "\\n" in body or "\\r" in body

    def test_markdown_table_uses_escape(self):
        content = self._read()
        # Search inside exportToMarkdown specifically (not the PDF builder).
        idx = content.find("function exportToMarkdown")
        assert idx > 0
        body = content[idx:idx + 2500]
        assert "escapeMarkdownCell" in body

    # --- HIGH: merge picks newer entry ---

    def test_merge_uses_last_modified_helper(self):
        content = self._read()
        assert "function entryLastModified" in content
        assert "function experimentLastModified" in content
        assert "function mergeById" in content

    def test_merge_compares_timestamps(self):
        """The merge helper must compare numeric timestamps, not just
        rely on Map insertion order."""
        content = self._read()
        idx = content.find("function mergeById")
        body = content[idx:idx + 800]
        assert "lastModified" in body
        # Must explicitly check newer-than before replacing
        assert ">=" in body or ">" in body

    # --- HIGH: hardcoded delay removed ---

    def test_no_500ms_hardcoded_delay(self):
        content = self._read()
        # The exact pattern from the bug
        assert "setTimeout(loadFromFile, 500)" not in content
        # Replaced with subscribe-then-watch
        idx = content.find("function initialize")
        body = content[idx:idx + 1200]
        # Subscribe BEFORE issuing load — order matters
        sub_idx = body.find("subscribe('nisystem/notebook/loaded'")
        assert sub_idx > 0
        # The watcher fires loadFromFile when connected, no delay needed
        assert "if (connected) loadFromFile()" in body

    # --- HIGH: popup-block fallback ---

    def test_popup_block_fallback(self):
        content = self._read()
        idx = content.find("function exportToPdf")
        body = content[idx:idx + 1500]
        assert "downloadFile(" in body  # fallback path
        # User-visible explanation
        assert "Pop-up blocked" in body or "popup" in body.lower()

    # --- MEDIUM: NaN filtered ---

    def test_snapshot_filters_nan(self):
        content = self._read()
        idx = content.find("function captureDataSnapshot")
        body = content[idx:idx + 500]
        assert "Number.isFinite" in body, \
            "Snapshot must reject NaN/Infinity, not just non-numbers"

    # --- MEDIUM: template placeholders ---

    def test_template_placeholder_substitution(self):
        content = self._read()
        assert "function applyTemplatePlaceholders" in content
        idx = content.find("function applyTemplatePlaceholders")
        body = content[idx:idx + 600]
        # Regex literals use escaped braces — match either form
        assert "experiment" in body
        assert "operator" in body
        assert "date" in body
        assert "time" in body
        # And we substitute via .replace
        assert ".replace(" in body

    def test_addfromtemplate_applies_placeholders(self):
        content = self._read()
        idx = content.find("function addFromTemplate")
        body = content[idx:idx + 500]
        assert "applyTemplatePlaceholders" in body

    # --- MEDIUM: quick note title ---

    def test_quick_note_title_uses_content_first_line(self):
        content = self._read()
        idx = content.find("function addQuickNote")
        body = content[idx:idx + 700]
        # Must derive title from content's first non-empty line, not just timestamp
        assert "firstLine" in body or "split(/\\r?\\n/)" in body
        # Must still fall back to timestamp form when content is empty
        assert "Note - " in body

    # --- ID generation ---

    def test_id_generation_uses_crypto_when_available(self):
        content = self._read()
        idx = content.find("function generateId")
        body = content[idx:idx + 500]
        assert "crypto.randomUUID" in body
        # Fallback includes a counter (defeats same-ms collisions)
        assert "idCounter" in body


# ===================================================================
# Logic replicas
# ===================================================================

class TestEscapeHelpers:
    """Replicate the JS escape helpers in Python to verify the rules."""

    def escape_html(self, s):
        return (s.replace('&', '&amp;')
                 .replace('<', '&lt;')
                 .replace('>', '&gt;')
                 .replace('"', '&quot;')
                 .replace("'", '&#39;'))

    def escape_md_cell(self, s):
        return (s.replace('\\', '\\\\')
                 .replace('|', '\\|')
                 .replace('\n', ' '))

    def test_xss_payload_neutered(self):
        """A note titled with an XSS payload must not produce executable HTML."""
        title = '<img src=x onerror=alert(1)>'
        out = self.escape_html(title)
        assert '<' not in out
        assert '>' not in out
        assert 'onerror' in out  # text preserved, but not as attribute

    def test_quote_escape(self):
        """Attribute injection via " must also be neutered."""
        title = '" onclick="alert(1)'
        out = self.escape_html(title)
        assert '"' not in out

    def test_pipe_in_channel_name(self):
        """Channel name with a pipe must not split table cells."""
        ch = 'Pump|Tank'
        out = self.escape_md_cell(ch)
        assert out == 'Pump\\|Tank'

    def test_newline_in_unit(self):
        """A unit with a newline (mistakenly entered) must not break the row."""
        unit = 'kg\nm'
        out = self.escape_md_cell(unit)
        assert '\n' not in out


class TestMergeConflictResolution:
    """Replicate the merge logic so the rule is verified independently."""

    def merge_by_id(self, local, remote, last_mod):
        merged = {x['id']: x for x in local}
        for x in remote:
            existing = merged.get(x['id'])
            if existing is None or last_mod(x) >= last_mod(existing):
                merged[x['id']] = x
        return list(merged.values())

    def last_mod(self, e):
        t = e['timestamp']
        if e.get('amendments'):
            t = max(t, e['amendments'][-1]['timestamp'])
        return t

    def test_local_newer_wins(self):
        local = [{'id': 'a', 'timestamp': '2025-03-05T12:00:00Z',
                  'amendments': [{'timestamp': '2025-03-05T13:00:00Z'}]}]
        remote = [{'id': 'a', 'timestamp': '2025-03-05T12:30:00Z'}]
        merged = self.merge_by_id(local, remote, self.last_mod)
        # Local was amended at 13:00, remote saved at 12:30 — local must win
        assert merged[0]['amendments'][0]['timestamp'] == '2025-03-05T13:00:00Z'

    def test_remote_newer_wins(self):
        local = [{'id': 'a', 'timestamp': '2025-03-05T12:00:00Z'}]
        remote = [{'id': 'a', 'timestamp': '2025-03-05T13:00:00Z'}]
        merged = self.merge_by_id(local, remote, self.last_mod)
        assert merged[0]['timestamp'] == '2025-03-05T13:00:00Z'

    def test_disjoint_ids_unioned(self):
        local = [{'id': 'a', 'timestamp': '2025-03-05T12:00:00Z'}]
        remote = [{'id': 'b', 'timestamp': '2025-03-05T13:00:00Z'}]
        merged = self.merge_by_id(local, remote, self.last_mod)
        assert {x['id'] for x in merged} == {'a', 'b'}

    def test_old_buggy_behavior_loses_data(self):
        """Document the OLD bug: file always wins → local edits lost."""
        local = [{'id': 'a', 'timestamp': '2025-03-05T13:00:00Z'}]
        remote = [{'id': 'a', 'timestamp': '2025-03-05T12:00:00Z'}]
        # Old: Map([...localMap, ...fileMap]) — file overwrites local
        old = dict()
        for x in local:
            old[x['id']] = x
        for x in remote:
            old[x['id']] = x  # File wins regardless of timestamp
        assert old['a']['timestamp'] == '2025-03-05T12:00:00Z', \
            "Documenting that old behavior would have clobbered the newer local edit"
        # New behavior:
        merged = self.merge_by_id(local, remote, self.last_mod)
        assert merged[0]['timestamp'] == '2025-03-05T13:00:00Z'


class TestSnapshotFilter:
    def test_finite_only(self):
        values = {
            'PT1': float('nan'),
            'PT2': float('inf'),
            'PT3': 12.5,
            'PT4': 0,
        }
        out = {k: v for k, v in values.items() if isinstance(v, (int, float)) and v == v and abs(v) != float('inf')}
        assert 'PT1' not in out
        assert 'PT2' not in out
        assert 'PT3' in out
        assert 'PT4' in out


class TestQuickNoteTitleDerivation:
    def derive(self, content):
        first = next((s.strip() for s in (content or '').splitlines() if s.strip()), '')
        if not first:
            return 'Note - HH:MM:SS'
        if len(first) > 60:
            return first[:57] + '…'
        return first

    def test_first_line_used(self):
        assert self.derive('Pressure spike at sensor 3\nNeed to investigate') == 'Pressure spike at sensor 3'

    def test_long_title_truncated(self):
        long = 'A' * 100
        out = self.derive(long)
        assert out.endswith('…')
        assert len(out) == 58

    def test_empty_falls_back_to_timestamp(self):
        out = self.derive('')
        assert out.startswith('Note - ')


class TestTemplatePlaceholders:
    def apply(self, s, ctx):
        return (s.replace('{experiment}', ctx.get('experiment', ''))
                 .replace('{operator}', ctx.get('operator', ''))
                 .replace('{date}', ctx.get('date', ''))
                 .replace('{time}', ctx.get('time', '')))

    def test_substitution(self):
        out = self.apply('Started: {experiment}', {'experiment': 'Run-42'})
        assert out == 'Started: Run-42'

    def test_missing_placeholder_becomes_empty(self):
        out = self.apply('By {operator}', {})
        assert out == 'By '


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
