# Safety Hardening Verification Test Plan

**Bench Hardware:**
- cDAQ-9189 (local USB/Ethernet, 6 NI modules, 50 channels)
- cRIO at 192.168.1.20 (6 NI modules, 96 channels, node `crio-001`)
- cFP at 192.168.1.30:502 (4 Modbus modules, 7 channels, node `cfp-001`)
- Opto22 groov EPIC/RIO (if available on bench)

**Prerequisites:**
- ICCSFlux running (`NISystem Start.bat`)
- MQTT broker on localhost:1883
- Dashboard open in browser at localhost:5173
- MQTT credentials from `config/mqtt_credentials.json`

---

## Setup: MQTT Monitor Terminal

Open a PowerShell terminal and run this to monitor all safety traffic:

```powershell
# Read credentials
$creds = Get-Content config\mqtt_credentials.json | ConvertFrom-Json
$user = $creds.backend.username
$pass = $creds.backend.password

# Monitor all safety, alarm, interlock, and status topics
vendor\mosquitto\mosquitto_sub.exe -h localhost -p 1883 -u $user -P $pass -v `
  -t "nisystem/nodes/+/safety/#" `
  -t "nisystem/nodes/+/alarms/#" `
  -t "nisystem/nodes/+/interlock/#" `
  -t "nisystem/nodes/+/status/system" `
  -t "nisystem/nodes/+/status/degraded" `
  -t "nisystem/nodes/+/status/stale_channels" `
  -t "nisystem/nodes/+/status/groov_mqtt"
```

Leave this running in a separate terminal throughout all tests.

---

## Test 1: Safety MQTT Retain Flags (cDAQ — DAQ Service)

**What we're verifying:** Safety state messages (`safety/status`, `safety/latch/state`) are retained on the broker so reconnecting clients get current state immediately.

### Steps

1. **Start the system** and load the Boiler Combustion Research cDAQ project
2. **Start acquisition** from the dashboard
3. **Open Safety tab**, arm the safety latch
4. **Verify in MQTT monitor:** You should see:
   ```
   nisystem/nodes/node-001/safety/latch/state {"latchId":...,"state":"ARMED",...}
   ```
5. **Close the MQTT monitor terminal** (Ctrl+C)
6. **Re-open the MQTT monitor** with the same command
7. **Immediately check:** The retained `safety/latch/state` message should appear right away without waiting for the next publish cycle

### Pass Criteria
- On reconnection, `safety/latch/state` appears within 1 second (retained message)
- On reconnection, `safety/status` appears within 1 second (retained message)
- Trip events (`safety/trip`) do NOT appear on reconnection (not retained — correct)

---

## Test 2: DAQ Service Last Will & Testament (cDAQ)

**What we're verifying:** When the DAQ service crashes, the broker publishes an offline message automatically.

### Steps

1. **Start the system** and verify `status/system` shows online:
   ```powershell
   vendor\mosquitto\mosquitto_sub.exe -h localhost -p 1883 -u $user -P $pass -v `
     -t "nisystem/nodes/+/status/system" -C 1
   ```
   Should show: `{"status":"online",...}`

2. **Kill the DAQ service process** — open Task Manager, find the DAQ service Python process, and End Task (simulates crash)

3. **Check the MQTT monitor:** Within 60 seconds (keepalive timeout), the broker should publish:
   ```
   nisystem/nodes/node-001/status/system {"status":"offline","reason":"unexpected_disconnect"}
   ```

4. **Restart the DAQ service** and verify it publishes online status again, overwriting the retained offline message

### Pass Criteria
- Offline LWT message appears after DAQ service is killed (within keepalive period)
- Message has `retain=true` (visible if using `-v` verbose mode)
- After restart, online status overwrites the offline message

---

## Test 3: Safety Evaluation Timing (cDAQ)

**What we're verifying:** Safety evaluation warnings appear in logs when evaluation takes >10ms.

### Steps

1. **Load the Boiler project** with all 50 channels
2. **Configure 10+ interlocks** in the Safety tab with complex conditions (multiple channel_value conditions per interlock, AND logic)
3. **Start acquisition**
4. **Check DAQ service logs** for:
   ```
   [SCAN] Safety evaluation took XX.Xms (>10ms)
   ```

### Pass Criteria
- If evaluation is fast (<10ms): no warnings in log (normal operation confirmed)
- If evaluation exceeds 10ms: warning appears with actual timing
- Either outcome is a pass — we're verifying the instrumentation works

### Note
With 50 channels and 10 interlocks at 10 Hz scan rate, evaluation should be well under 10ms. To deliberately trigger the warning, create 50+ interlocks with multiple conditions each.

---

## Test 4: Enhanced Disconnect/Reconnect Logging (cDAQ)

**What we're verifying:** DAQ service logs distinguish first connection, reconnection, clean disconnect, and unexpected disconnect.

### Steps

1. **Start the system** — check DAQ service log for:
   ```
   Connected to MQTT broker
   ```
   (First connection — NOT "Reconnected")

2. **Stop the Mosquitto broker** (kill the process)
3. **Check DAQ service log** for:
   ```
   Disconnected from MQTT broker unexpectedly (rc=...)
   ```

4. **Restart the Mosquitto broker**
5. **Check DAQ service log** for:
   ```
   Reconnected to MQTT broker (was disconnected)
   ```

### Pass Criteria
- First connection: "Connected to MQTT broker"
- Unexpected disconnect: "unexpectedly" in message
- Reconnection: "Reconnected" in message
- Clean shutdown: "clean" in message

---

## Test 5: cRIO Communication Watchdog (cRIO at 192.168.1.20)

**What we're verifying:** cRIO applies safe state and transitions to IDLE when PC contact is lost for >30 seconds.

### Steps

1. **Load cRIO Test project** and push config to cRIO
2. **Start acquisition** — verify cRIO is in ACQUIRING state
3. **Verify channels are publishing** in the MQTT monitor:
   ```
   nisystem/nodes/crio-001/values {...}
   ```
4. **Wire a known voltage to a Mod2 analog output** (e.g., 5V to AO channel) — verify it holds
5. **Disconnect the Ethernet cable** from the PC (or block port 1883 with a firewall rule)
6. **Wait 35 seconds**
7. **Check MQTT monitor** (you won't see this until reconnected, but the cRIO will log it):
   ```
   nisystem/nodes/crio-001/safety/comm_watchdog {"tripped":true,"elapsed_s":30.1,...}
   ```
8. **Reconnect the Ethernet cable**
9. **Check:**
   - cRIO should publish `safety/comm_watchdog {"tripped":false,...}` (recovery)
   - cRIO should be in IDLE state (acquisition stopped)
   - All outputs should be at safe state values (0V / off)

### Pass Criteria
- After 30s of no contact: cRIO transitions to IDLE
- Analog outputs go to 0V (or configured safe value)
- Digital outputs go to OFF (or configured safe state)
- `safety/comm_watchdog` tripped=true message published
- On reconnect: tripped=false message published

### Alternative (without unplugging cable)
Stop the DAQ service (which sends heartbeats) but leave the MQTT broker running. The cRIO will still see MQTT connected but no DAQ commands, triggering the comm watchdog.

---

## Test 6: cRIO Safety Evaluation Timing (cRIO at 192.168.1.20)

**What we're verifying:** cRIO logs warning when safety evaluation takes >10ms.

### Steps

1. **SSH into the cRIO:**
   ```
   ssh admin@192.168.1.20
   ```
2. **Check cRIO logs** (typically in `/var/log/nisystem/` or stdout):
   ```
   tail -f /var/log/nisystem/crio_node.log
   ```
3. **Push a config with several interlocks** from the Safety tab
4. **Start acquisition**
5. **Monitor for:** `Safety evaluation took XX.Xms (>10ms)`

### Pass Criteria
- Same as Test 3 — instrumentation is present and functional

---

## Test 7: cFP Communication and Safety (cFP at 192.168.1.30)

**What we're verifying:** cFP node reads Modbus I/O, publishes values, and handles COMM_FAIL.

### Steps

1. **Verify cFP node is running** — check MQTT for:
   ```
   nisystem/nodes/cfp-001/status/system {"status":"online",...}
   ```

2. **Verify Modbus reads** — check for channel values:
   ```
   nisystem/nodes/cfp-001/values {"AI01":..., "DI01":..., ...}
   ```

3. **Read physical I/O:**
   - Apply a known voltage to AI01 (cFP-AI-110 slot 1) — verify value appears in MQTT
   - Toggle DI01 input — verify state change in MQTT
   - Command DO01 output from dashboard — verify relay activates

4. **Test COMM_FAIL — Modbus disconnect:**
   - Disconnect the Ethernet cable from the cFP-1808 backplane
   - Wait for the cFP node to detect the Modbus read failure
   - **Check MQTT monitor** for COMM_FAIL alarm:
     ```
     nisystem/nodes/cfp-001/alarms/event {"channel":"AI01","alarm_type":"comm_fail",...}
     ```
   - Reconnect the cable — verify COMM_FAIL clears

5. **Test safe state command:**
   - Set DO01 to ON from dashboard
   - Send safe-state command: publish to `nisystem/nodes/cfp-001/commands/safe-state`
   - Verify DO01 goes OFF (safe state)

### Pass Criteria
- Modbus reads appear at configured scan rate (1 Hz)
- COMM_FAIL alarm fires within 10 seconds of cable disconnect
- COMM_FAIL clears when cable reconnected
- Safe state command zeros all outputs

---

## Test 8: Opto22 Stale Channel COMM_FAIL (if Opto22 on bench)

**What we're verifying:** When groov MQTT stops updating a channel for >10 seconds, COMM_FAIL alarm fires.

### Steps

1. **Start the Opto22 node** with a project config
2. **Verify groov MQTT I/O** is flowing — check status:
   ```
   nisystem/nodes/opto22-001/values {...}
   ```

3. **Simulate stale I/O** — Stop the groov Manage MQTT broker on the Opto22 device (or disconnect the I/O module)

4. **Wait 10-15 seconds**

5. **Check MQTT monitor for:**
   ```
   nisystem/nodes/opto22-001/status/stale_channels {"channels":["ch1","ch2"],...}
   nisystem/nodes/opto22-001/alarms/event {"channel":"ch1","alarm_type":"comm_fail",...}
   ```

6. **Restore groov MQTT** — verify:
   - Stale channels list clears
   - COMM_FAIL alarms clear
   - Values resume publishing

### Pass Criteria
- Stale detection triggers within 10s of groov MQTT data stop
- COMM_FAIL alarm fires for each stale channel (new behavior from Fix 3)
- Alarms clear automatically when data resumes

---

## Test 9: Opto22 Communication Watchdog (if Opto22 on bench)

**What we're verifying:** Opto22 applies safe state when PC contact is lost for >30 seconds.

### Steps

1. **Start Opto22 node** and begin acquisition
2. **Set a digital output to ON** from the dashboard
3. **Stop the DAQ service** (simulates PC contact loss)
4. **Wait 35 seconds**
5. **Check Opto22 node log for:**
   ```
   COMMUNICATION WATCHDOG: No commands received for 30.1s (timeout=30s) — transitioning to safe state
   ```
6. **Check MQTT for:**
   ```
   nisystem/nodes/opto22-001/safety/comm_watchdog {"tripped":true,...}
   ```
7. **Verify:** Digital output went to OFF (safe state), node is in IDLE

8. **Restart DAQ service** — check for:
   ```
   nisystem/nodes/opto22-001/safety/comm_watchdog {"tripped":false,...}
   ```

### Pass Criteria
- Same behavior as cRIO comm watchdog (Test 5)
- Safe state applied after 30s timeout
- Recovery published on contact restoration

---

## Test 10: End-to-End Interlock Trip (All Platforms)

**What we're verifying:** Complete interlock lifecycle across the safety hardening changes.

### Steps (using cRIO as example)

1. **Create an interlock** in the Safety tab:
   - Name: "High Temperature Trip"
   - Condition: `channel_value` on thermocouple channel `tag_32` (Mod5/ai0) > 50.0
   - Control: `set_output` on digital output `tag_64` (Mod4/port0/line0) to 0

2. **Arm the safety latch** from the Safety tab

3. **Verify MQTT retain:**
   ```
   nisystem/nodes/node-001/safety/latch/state {"state":"ARMED",...}
   ```

4. **Heat the thermocouple** above 50 degrees (or use a thermocouple simulator)

5. **Verify trip sequence in MQTT monitor:**
   ```
   # 1. Interlock fails
   nisystem/nodes/node-001/interlock/status {...,"satisfied":false,...}

   # 2. System trips
   nisystem/nodes/node-001/safety/trip {"reason":"Interlock failed: High Temperature Trip",...}

   # 3. Latch state changes
   nisystem/nodes/node-001/safety/latch/state {"state":"TRIPPED",...}

   # 4. Output set to safe value
   # (verify on hardware: DO channel goes OFF)
   ```

6. **Cool the thermocouple** below 50 degrees
7. **Reset the trip** from the Safety tab
8. **Verify recovery** in MQTT

### Pass Criteria
- Trip event published with QoS 1 (reliable delivery)
- Latch state retained on broker (test by reconnecting MQTT monitor)
- Physical output driven to safe state
- Reset works and system returns to ARMED

---

## Quick Reference: What Each Test Verifies

| Test | Fix | Platform | Method |
|------|-----|----------|--------|
| 1 | Retain flags | cDAQ | Reconnect MQTT client, check retained messages |
| 2 | DAQ LWT | cDAQ | Kill DAQ process, check offline message |
| 3 | Safety timing | cDAQ | Check logs under load |
| 4 | Disconnect handler | cDAQ | Stop/restart MQTT broker |
| 5 | Comm watchdog | cRIO | Unplug Ethernet, verify safe state |
| 6 | Safety timing | cRIO | SSH logs under load |
| 7 | COMM_FAIL + safety | cFP | Unplug Modbus cable, verify alarms |
| 8 | Stale -> COMM_FAIL | Opto22 | Stop groov MQTT, verify alarms |
| 9 | Comm watchdog | Opto22 | Stop DAQ service, verify safe state |
| 10 | Full trip lifecycle | All | Heat TC, verify interlock trip chain |

---

## Troubleshooting

**No MQTT messages appearing:**
- Verify broker is running: `netstat -an | findstr 1883`
- Check credentials: `type config\mqtt_credentials.json`
- Try anonymous on WebSocket: `mosquitto_sub -h localhost -p 9002 -t "#"`

**cRIO not responding:**
- Ping: `ping 192.168.1.20`
- SSH check: `ssh admin@192.168.1.20 "ps | grep crio"`
- Redeploy: `deploy_crio_v2.bat 192.168.1.20`

**cFP Modbus not connecting:**
- Verify: `ping 192.168.1.30`
- Check Modbus port: `Test-NetConnection 192.168.1.30 -Port 502`

**Retained messages not appearing:**
- Clear old retained messages: publish empty payload with retain flag
  ```
  mosquitto_pub -h localhost -p 1883 -u backend -P <pass> -t "topic" -r -n
  ```
