#!/usr/bin/env python3
"""Generate self-signed TLS certificates for MQTT broker.

Creates a CA and server certificate for securing MQTT communication
between the PC and remote cRIO nodes.

Usage:
    python scripts/generate_tls_certs.py           # Generate if missing
    python scripts/generate_tls_certs.py --force    # Regenerate all certs

Output (in config/tls/):
    ca.crt       - CA certificate (distribute to clients)
    ca.key       - CA private key (keep secure)
    server.crt   - Server certificate
    server.key   - Server private key

Certificate validity: 1 year.
"""

import argparse
import logging
import socket
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [TLS-SETUP] %(levelname)s %(message)s'
)
logger = logging.getLogger('TLSSetup')

CERT_VALIDITY_DAYS = 365  # 1 year

def _restrict_key_permissions(key_path: Path) -> None:
    """Restrict private key file to owner-only access."""
    import os
    if os.name != 'nt':
        key_path.chmod(0o600)
    else:
        try:
            import subprocess
            username = os.environ.get('USERNAME', '')
            if username:
                subprocess.run(
                    ['icacls', str(key_path), '/inheritance:r',
                     '/grant:r', f'{username}:(R,W)'],
                    capture_output=True, timeout=10
                )
        except Exception as e:
            logger.warning(f"Could not restrict permissions on {key_path}: {e}")

def generate_certificates(output_dir: Path, force: bool = False) -> bool:
    """Generate CA and server certificates.

    Returns True on success.
    """
    try:
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
    except ImportError:
        logger.error(
            "cryptography package not installed. "
            "Install with: pip install cryptography"
        )
        return False

    output_dir.mkdir(parents=True, exist_ok=True)

    ca_cert_path = output_dir / "ca.crt"
    ca_key_path = output_dir / "ca.key"
    server_cert_path = output_dir / "server.crt"
    server_key_path = output_dir / "server.key"

    # Check if certs already exist
    if not force and all(p.exists() for p in [
        ca_cert_path, ca_key_path, server_cert_path, server_key_path
    ]):
        logger.info("TLS certificates already exist. Use --force to regenerate.")
        return True

    logger.info("Generating TLS certificates...")

    # === Generate CA ===
    ca_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    ca_name = x509.Name([
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "NISystem"),
        x509.NameAttribute(NameOID.COMMON_NAME, "NISystem MQTT CA"),
    ])

    now = datetime.now(timezone.utc)
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=CERT_VALIDITY_DAYS))
        .add_extension(
            x509.BasicConstraints(ca=True, path_length=0),
            critical=True,
        )
        .sign(ca_key, hashes.SHA256())
    )

    # Write CA cert and key
    with open(ca_cert_path, "wb") as f:
        f.write(ca_cert.public_bytes(serialization.Encoding.PEM))

    with open(ca_key_path, "wb") as f:
        f.write(ca_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ))

    _restrict_key_permissions(ca_key_path)

    logger.info(f"  CA certificate: {ca_cert_path}")
    logger.info(f"  CA key:         {ca_key_path}")

    # === Generate Server Certificate ===
    server_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    # Collect hostnames for SAN
    # Include all likely broker IPs so TLS hostname verification succeeds
    # from any remote node (cRIO, Opto22, GC) regardless of network topology.
    import ipaddress

    hostname = socket.gethostname()
    san_dns = {"localhost", hostname}
    san_ips = {
        ipaddress.IPv4Address("127.0.0.1"),
        ipaddress.IPv4Address("192.168.1.1"),   # Default USB Ethernet (PC side)
        ipaddress.IPv4Address("10.10.10.1"),     # Common plant network
    }

    # Try to add all local IPs from all network interfaces
    try:
        import subprocess
        # Use socket to get primary IP
        local_ip = socket.gethostbyname(hostname)
        san_ips.add(ipaddress.IPv4Address(local_ip))
    except Exception:
        pass

    # Try to discover additional interface IPs (Windows and Linux)
    try:
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            try:
                san_ips.add(ipaddress.IPv4Address(info[4][0]))
            except (ValueError, IndexError):
                pass
    except Exception:
        pass

    san_names = [x509.DNSName(name) for name in sorted(san_dns)]
    san_names += [x509.IPAddress(ip) for ip in sorted(san_ips)]

    logger.info(f"  SAN entries: {[str(n) for n in san_names]}")

    server_name = x509.Name([
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "NISystem"),
        x509.NameAttribute(NameOID.COMMON_NAME, hostname),
    ])

    server_cert = (
        x509.CertificateBuilder()
        .subject_name(server_name)
        .issuer_name(ca_cert.subject)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=CERT_VALIDITY_DAYS))
        .add_extension(
            x509.SubjectAlternativeName(san_names),
            critical=False,
        )
        .add_extension(
            x509.BasicConstraints(ca=False, path_length=None),
            critical=True,
        )
        .sign(ca_key, hashes.SHA256())
    )

    # Write server cert and key
    with open(server_cert_path, "wb") as f:
        f.write(server_cert.public_bytes(serialization.Encoding.PEM))

    with open(server_key_path, "wb") as f:
        f.write(server_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ))

    _restrict_key_permissions(server_key_path)

    logger.info(f"  Server cert:    {server_cert_path}")
    logger.info(f"  Server key:     {server_key_path}")
    logger.info("TLS certificates generated successfully.")
    logger.info(f"  Validity: {CERT_VALIDITY_DAYS} days ({CERT_VALIDITY_DAYS // 365} years)")
    logger.info(f"  SANs: localhost, {hostname}, 127.0.0.1, 192.168.1.1")

    return True

def main():
    parser = argparse.ArgumentParser(
        description="Generate TLS certificates for NISystem MQTT"
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Regenerate certificates even if they exist",
    )
    parser.add_argument(
        "--output-dir", type=str, default=None,
        help="Output directory (default: config/tls/)",
    )
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    output_dir = (
        Path(args.output_dir)
        if args.output_dir
        else project_root / "config" / "tls"
    )

    success = generate_certificates(output_dir, force=args.force)
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
