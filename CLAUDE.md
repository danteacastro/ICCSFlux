# NISystem Project Instructions

## cRIO Deployment

**ALWAYS use `deploy_crio_v2.bat` when deploying changes to the cRIO.**

```cmd
deploy_crio_v2.bat [crio_host] [broker_host]
```

Default values:
- crio_host: 192.168.1.20
- broker_host: 192.168.1.1

This script:
1. Creates directory structure on cRIO
2. Deploys all crio_node_v2 module files (including channel_types.py)
3. Deploys the runner script
4. Sets permissions
5. Stops any existing service
6. Starts the new service as daemon

**DO NOT manually scp individual files** - use the deploy script to ensure all files are deployed together and the service is properly restarted.

## Device CLI

Use `device.bat` for device management operations (NOT for starting services):
- `device scan` - Discover devices
- `device deploy crio --host <ip> -r` - Deploy to cRIO
- `device logs crio --host <ip> -f` - Follow cRIO logs

## DAQ Service

The DAQ service runs on the PC and is started separately (not via device.bat).

## cRIO Hardware Notes

- cRIO modules require DIFFERENTIAL terminal configuration (not RSE)
- Use `TerminalConfiguration.DEFAULT` to let DAQmx auto-select
- Thermocouple channels need `channel_type == 'thermocouple'` check before using thermocouple setup
