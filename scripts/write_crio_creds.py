"""Generate cRIO credential JSON file for deploy_crio_v2.bat.

Usage: python scripts/write_crio_creds.py <mqtt_user> <mqtt_pass> <broker> <port> <tls_enabled> <tls_ca_cert>
Output: _crio_creds_tmp.json (in current directory)
"""
import json
import sys

def main():
    if len(sys.argv) < 7:
        print(f"Usage: {sys.argv[0]} <mqtt_user> <mqtt_pass> <broker> <port> <tls_enabled> <tls_ca_cert>")
        sys.exit(1)

    mqtt_user = sys.argv[1]
    mqtt_pass = sys.argv[2]
    broker = sys.argv[3]
    port = int(sys.argv[4])
    tls_enabled = sys.argv[5].lower() == 'true'
    tls_ca_cert = sys.argv[6] if sys.argv[6] else ''

    creds = {
        'mqtt_user': mqtt_user,
        'mqtt_pass': mqtt_pass,
        'broker': broker,
        'port': port,
        'tls_enabled': tls_enabled,
        'tls_ca_cert': tls_ca_cert,
        'node_id': 'crio-001',
    }

    out_path = '_crio_creds_tmp.json'
    with open(out_path, 'w') as f:
        json.dump(creds, f, indent=2)

    print(f"Credential file written: {out_path}")
    print(f"  user={mqtt_user} broker={broker} port={port} tls={tls_enabled}")

if __name__ == '__main__':
    main()
