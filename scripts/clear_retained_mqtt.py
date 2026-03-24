"""Clear retained MQTT acquire messages after cRIO deploy.

Usage: python scripts/clear_retained_mqtt.py [mqtt_user] [mqtt_pass]
If no credentials supplied, connects anonymously.
"""
import sys

try:
    import paho.mqtt.client as mqtt
except ImportError:
    print("paho-mqtt not installed, skipping retained message cleanup")
    sys.exit(0)

def main():
    mqtt_user = sys.argv[1] if len(sys.argv) > 1 else None
    mqtt_pass = sys.argv[2] if len(sys.argv) > 2 else None

    try:
        c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, 'deploy-cleanup')
        if mqtt_user:
            c.username_pw_set(mqtt_user, mqtt_pass)
        c.connect('localhost', 1883)
        c.publish('nisystem/nodes/crio-001/system/acquire/start', b'', retain=True)
        c.publish('nisystem/nodes/crio-001/system/acquire/stop', b'', retain=True)
        c.loop(0.5)
        c.disconnect()
        print("Retained acquire messages cleared")
    except Exception as e:
        print(f"Could not clear retained messages (broker may not be running): {e}")

if __name__ == '__main__':
    main()
