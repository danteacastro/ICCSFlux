# -*- coding: utf-8 -*-
"""
Simple project loading test - verifies backend loads DHW project correctly
"""
import pytest
from pathlib import Path


def test_dhw_project_loads_successfully(mqtt_client):
    """Test that dhw_test_system.json loads correctly via MQTT"""
    base = "nisystem"

    # Verify project file exists
    project_file = Path(__file__).parent.parent / "config" / "projects" / "dhw_test_system.json"
    assert project_file.exists(), f"Project file not found: {project_file}"

    print(f"\n[OK] Project file found: {project_file.name}")

    # Subscribe to project/loaded topic
    mqtt_client.subscribe_and_wait(f"{base}/project/loaded", timeout=2.0)

    # Send load command
    print(f"[>>] Sending project load command...")
    mqtt_client.publish(f"{base}/project/load", {"filename": "dhw_test_system.json"})

    # Wait for response
    msg = mqtt_client.wait_for_new_message(f"{base}/project/loaded", timeout=5.0)
    assert msg is not None, "[!!] No response from backend within 5s"

    payload = msg['payload']
    print(f"[<<] Received response: success={payload.get('success')}")

    # Verify success
    assert payload['success'], f"[FAIL] Project load failed: {payload.get('message')}"

    # Verify project data is included
    assert 'project' in payload, "[FAIL] No project data in response"
    project_data = payload['project']

    # Basic structure checks
    assert project_data.get('type') == 'nisystem-project'
    assert project_data.get('name') == 'DHW Test System'
    assert 'layout' in project_data

    layout = project_data['layout']
    print(f"\n[INFO] Layout structure:")
    print(f"   - Grid: {layout.get('gridColumns')} cols x {layout.get('rowHeight')}px rows")
    print(f"   - Current page: {layout.get('currentPageId')}")
    print(f"   - Total pages: {len(layout.get('pages', []))}")

    # Verify pages
    pages = layout.get('pages', [])
    assert len(pages) == 2, f"Expected 2 pages, got {len(pages)}"

    for page in pages:
        widget_count = len(page.get('widgets', []))
        print(f"   - {page.get('name')}: {widget_count} widgets (id: {page.get('id')})")

    # Verify main page
    main_page = next((p for p in pages if p['id'] == 'main'), None)
    assert main_page is not None, "Main page not found"
    assert len(main_page['widgets']) >= 10, f"Main page should have 24 widgets, got {len(main_page['widgets'])}"

    # Verify alarms page
    alarms_page = next((p for p in pages if p['id'] == 'alarms'), None)
    assert alarms_page is not None, "Alarms page not found"
    assert len(alarms_page['widgets']) >= 1, f"Alarms page should have 3 widgets, got {len(alarms_page['widgets'])}"

    print(f"\n[PASS] PROJECT LOAD TEST PASSED")
    print(f"   Main page: {len(main_page['widgets'])} widgets")
    print(f"   Alarms page: {len(alarms_page['widgets'])} widgets")
    print(f"   Total widgets across all pages: {sum(len(p['widgets']) for p in pages)}")


if __name__ == '__main__':
    pytest.main([__file__, '-v', '-s'])
