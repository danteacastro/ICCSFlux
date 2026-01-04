"""
Test project loading and widget rendering E2E
This test verifies that:
1. Projects load correctly via MQTT
2. Widget data is transmitted to frontend
3. All expected widgets are present
"""
import pytest
import json
import time
from pathlib import Path

def test_dhw_project_load_and_widget_count(mqtt_client):
    """Test loading dhw_test_system.json and verify widgets are loaded"""
    base = "nisystem"

    # Load the DHW test project
    project_file = Path(__file__).parent.parent / "config" / "projects" / "dhw_test_system.json"
    assert project_file.exists(), f"Project file not found: {project_file}"

    print(f"\n[TEST] Loading project: {project_file.name}")

    # Subscribe and wait for confirmation
    mqtt_client.subscribe_and_wait(f"{base}/project/loaded", timeout=2.0)

    # Send load command
    mqtt_client.publish(
        f"{base}/project/load",
        {"filename": "dhw_test_system.json"}
    )

    # Wait for project to load
    msg = mqtt_client.wait_for_new_message(f"{base}/project/loaded", timeout=5.0)
    assert msg is not None, "Project did not load within timeout"

    payload = msg['payload']
    assert payload['success'], f"Project load failed: {payload.get('message')}"

    print(f"\n[TEST] Received project/loaded: {payload.get('success')}")
    if payload.get('project'):
        layout = payload['project'].get('layout', {})
        print(f"[TEST] Pages in project: {len(layout.get('pages', []))}")
        for page in layout.get('pages', []):
            print(f"[TEST]   - {page.get('name')}: {len(page.get('widgets', []))} widgets")

    # Verify project structure
    project_data = project_loaded[0]['project']
    assert project_data['type'] == 'nisystem-project'
    assert project_data['name'] == 'DHW Test System'

    # Verify layout structure
    layout = project_data['layout']
    assert 'pages' in layout, "Project missing pages"
    assert len(layout['pages']) == 2, f"Expected 2 pages, got {len(layout['pages'])}"

    # Verify Main Dashboard page
    main_page = next((p for p in layout['pages'] if p['id'] == 'main'), None)
    assert main_page is not None, "Main page not found"
    assert main_page['name'] == 'Main Dashboard'
    assert len(main_page['widgets']) == 24, f"Expected 24 widgets on main page, got {len(main_page['widgets'])}"

    # Verify Alarms & Safety page
    alarms_page = next((p for p in layout['pages'] if p['id'] == 'alarms'), None)
    assert alarms_page is not None, "Alarms page not found"
    assert alarms_page['name'] == 'Alarms & Safety'
    assert len(alarms_page['widgets']) == 3, f"Expected 3 widgets on alarms page, got {len(alarms_page['widgets'])}"

    # Verify currentPageId is set to main
    assert layout['currentPageId'] == 'main', f"Expected currentPageId to be 'main', got {layout['currentPageId']}"

    # Verify grid settings
    assert layout['gridColumns'] == 24
    assert layout['rowHeight'] == 30

    print(f"\n[TEST] ✅ Project loaded successfully:")
    print(f"[TEST]   - Main page: {len(main_page['widgets'])} widgets")
    print(f"[TEST]   - Alarms page: {len(alarms_page['widgets'])} widgets")
    print(f"[TEST]   - Grid: {layout['gridColumns']} columns x {layout['rowHeight']}px rows")

    # Log some sample widgets to verify structure
    print(f"\n[TEST] Sample widgets from main page:")
    for widget in main_page['widgets'][:3]:
        print(f"[TEST]   - {widget.get('type')}: {widget.get('label', widget.get('channel', 'no-label'))}")


def test_widget_types_in_dhw_project(mqtt_system):
    """Verify all widget types are correctly specified in DHW project"""
    client, config = mqtt_system
    base = config['mqtt']['base_topic']

    project_loaded = []

    def on_project_loaded(client, userdata, message):
        payload = json.loads(message.payload.decode())
        project_loaded.append(payload)

    client.subscribe(f"{base}/project/loaded")
    client.message_callback_add(f"{base}/project/loaded", on_project_loaded)

    # Load project
    client.publish(
        f"{base}/project/load",
        json.dumps({"filename": "dhw_test_system.json"})
    )

    # Wait for load
    timeout = time.time() + 5.0
    while time.time() < timeout and len(project_loaded) == 0:
        time.sleep(0.1)

    assert len(project_loaded) > 0
    project_data = project_loaded[0]['project']

    # Collect all widgets from all pages
    all_widgets = []
    for page in project_data['layout']['pages']:
        all_widgets.extend(page['widgets'])

    # Count widget types
    widget_types = {}
    for widget in all_widgets:
        wtype = widget.get('type', 'unknown')
        widget_types[wtype] = widget_types.get(wtype, 0) + 1

    print(f"\n[TEST] Widget type distribution:")
    for wtype, count in sorted(widget_types.items()):
        print(f"[TEST]   - {wtype}: {count}")

    # Verify expected types are present
    assert 'title' in widget_types, "No title widgets found"
    assert 'numeric' in widget_types, "No numeric widgets found"
    assert 'chart' in widget_types, "No chart widgets found"
    assert 'scheduler_status' in widget_types, "No scheduler_status widget found"
    assert 'system_status' in widget_types, "No system_status widget found"
    assert 'recording_status' in widget_types, "No recording_status widget found"
    assert 'led' in widget_types, "No LED widgets found"
    assert 'alarm_summary' in widget_types, "No alarm_summary widget found"
    assert 'interlock_status' in widget_types, "No interlock_status widget found"

    # Verify total count
    total_widgets = sum(widget_types.values())
    assert total_widgets == 27, f"Expected 27 total widgets, got {total_widgets}"

    print(f"[TEST] ✅ All widget types verified ({total_widgets} total)")


def test_widget_channel_bindings(mqtt_system):
    """Verify widgets are correctly bound to channels"""
    client, config = mqtt_system
    base = config['mqtt']['base_topic']

    project_loaded = []

    def on_project_loaded(client, userdata, message):
        payload = json.loads(message.payload.decode())
        project_loaded.append(payload)

    client.subscribe(f"{base}/project/loaded")
    client.message_callback_add(f"{base}/project/loaded", on_project_loaded)

    # Load project
    client.publish(
        f"{base}/project/load",
        json.dumps({"filename": "dhw_test_system.json"})
    )

    # Wait for load
    timeout = time.time() + 5.0
    while time.time() < timeout and len(project_loaded) == 0:
        time.sleep(0.1)

    assert len(project_loaded) > 0
    project_data = project_loaded[0]['project']

    # Get all widgets
    all_widgets = []
    for page in project_data['layout']['pages']:
        all_widgets.extend(page['widgets'])

    # Check channel bindings
    single_channel_widgets = [w for w in all_widgets if 'channel' in w]
    multi_channel_widgets = [w for w in all_widgets if 'channels' in w]

    print(f"\n[TEST] Channel bindings:")
    print(f"[TEST]   - Single-channel widgets: {len(single_channel_widgets)}")
    print(f"[TEST]   - Multi-channel widgets: {len(multi_channel_widgets)}")

    # Verify charts have channels
    charts = [w for w in all_widgets if w['type'] == 'chart']
    for chart in charts:
        assert 'channels' in chart, f"Chart {chart.get('id')} missing channels"
        assert len(chart['channels']) > 0, f"Chart {chart.get('id')} has no channels"
        print(f"[TEST]     Chart '{chart.get('label')}': {len(chart['channels'])} channels")

    # Verify numeric widgets have channels
    numerics = [w for w in all_widgets if w['type'] == 'numeric']
    for numeric in numerics:
        assert 'channel' in numeric, f"Numeric {numeric.get('id')} missing channel"
        print(f"[TEST]     Numeric '{numeric.get('label')}': channel={numeric['channel']}")

    print(f"[TEST] ✅ All channel bindings verified")


if __name__ == '__main__':
    pytest.main([__file__, '-v', '-s'])
