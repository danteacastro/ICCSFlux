"""Read MQTT credentials and print user:pass for deploy_crio_v2.bat.

Usage: python scripts/read_mqtt_creds.py
Output: username:password (single line, colon-separated)
Exit code 1 if file missing or unreadable.
"""
import json
import sys

def main():
    try:
        with open('config/mqtt_credentials.json', 'r') as f:
            d = json.load(f)
        user = d['backend']['username']
        password = d['backend']['password']
        print(f"{user}:{password}")
    except (FileNotFoundError, KeyError, json.JSONDecodeError) as e:
        print(f"Error reading credentials: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == '__main__':
    main()
