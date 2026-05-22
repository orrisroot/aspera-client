"""SDK installation and key management for Aspera transfers."""

from __future__ import annotations

import base64
import datetime
import os
import platform
import ssl
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509 import (
    CertificateBuilder, Name, NameAttribute, Certificate,
    BasicConstraints, SubjectKeyIdentifier, AuthorityKeyIdentifier,
)
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives.serialization import (
    Encoding, PrivateFormat, NoEncryption, load_der_private_key,
)

SDK_DIR = Path.home() / ".aspera" / "connect"
SDK_BIN_DIR = SDK_DIR / "bin"
CLIENT_DIR = SDK_DIR / "client"

# Embedded RSA bypass key in DER format (Base64-encoded)
_BYPASS_RSA_DER_B64 = "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"

_RUNTIME_FOLDERS = ("bin", "lib", "sbin", "aspera", "etc")
SDK_LOCATION_URL = "https://ibm.biz/sdk_location"


def _get_platform_info() -> tuple[str, str]:
    """Get platform name and architecture for SDK download."""
    sys_name = platform.system().lower()
    machine = platform.machine().lower()

    arch_map = {
        "x86_64": "x86_64",
        "amd64": "x86_64",
        "aarch64": "aarch64",
        "arm64": "aarch64",
        "i686": "i386",
        "i386": "i386",
        "x86": "i386",
    }
    arch = arch_map.get(machine, machine)

    if sys_name == "darwin":
        platform_name = f"osx-{arch}"
    elif sys_name == "linux":
        platform_name = f"linux-{arch}"
    else:
        platform_name = f"{sys_name}-{arch}"

    return platform_name, arch


def _download_file(url: str, dest_path: str) -> None:
    """Download a file from URL to dest_path."""
    context = ssl.create_default_context()
    req = urllib.request.Request(url, headers={"User-Agent": "aspera-client/0.2.0"})
    with urllib.request.urlopen(req, context=context, timeout=120) as response:
        total = response.getheader("Content-Length", 0)
        total = int(total) if total else 0
        downloaded = 0
        with open(dest_path, "wb") as f:
            while True:
                chunk = response.read(8192)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if total:
                    pct = downloaded / total * 100
                    print(f"  Downloading: {pct:.1f}%", end="\r", file=sys.stderr)
        print(file=sys.stderr)


def _extract_sdk_archive(archive_path: str, dest_dir: str) -> None:
    """Extract SDK archive (tar.gz) to dest_dir, extracting only runtime folders.

    Handles archives with or without a top-level directory prefix.
    Strips the top-level directory so files land directly in dest_dir.
    """
    print(f"  Extracting to {dest_dir}...", file=sys.stderr)
    with tarfile.open(archive_path, "r:gz") as tar:
        all_names = tar.getnames()

        # Detect top-level directory prefix from first file entry
        top_level = ""
        for n in all_names:
            parts = n.split("/")
            if len(parts) > 1 and parts[0]:
                top_level = parts[0]
                break

        # Build set of member names to extract (with rewritten paths)
        extract_map = {}  # original_name -> new_name
        for member in tar.getmembers():
            parts = member.name.split("/")

            if top_level and len(parts) > 1 and parts[0] == top_level:
                effective_parts = parts[1:]
            else:
                effective_parts = parts

            # Skip the top-level directory entry itself
            if member.isdir() and effective_parts == [] and top_level:
                continue

            if member.isdir():
                if effective_parts and effective_parts[0] in _RUNTIME_FOLDERS:
                    new_name = "/".join(effective_parts)
                    extract_map[member.name] = new_name
            elif member.isfile():
                if effective_parts and effective_parts[0] in _RUNTIME_FOLDERS:
                    if ".." in member.name:
                        print(f"  Skipping suspicious path: {member.name}", file=sys.stderr)
                        continue
                    new_name = "/".join(effective_parts)
                    extract_map[member.name] = new_name

        # Extract with rewritten paths
        for member in tar.getmembers():
            if member.name not in extract_map:
                continue
            member.name = extract_map[member.name]

        # Sort so directories come before files
        sorted_members = sorted(tar.getmembers(), key=lambda m: (not m.isdir(), m.name))
        tar.extractall(path=dest_dir, members=sorted_members)

    bin_dir = Path(dest_dir) / "bin"
    if bin_dir.exists():
        for f in bin_dir.iterdir():
            if f.is_file():
                try:
                    os.chmod(f, 0o755)
                except OSError:
                    pass


def _write_file_restricted(path: str, content: bytes, mode: int = 0o644) -> str:
    """Write file with restricted permissions."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        f.write(content)
    os.chmod(path, mode)
    return path


def generate_bypass_key() -> tuple[str, str]:
    """Generate bypass RSA private key from embedded DER data.

    Returns:
        Tuple of (pem_path, key_pem)
    """
    client_dir = CLIENT_DIR
    client_dir.mkdir(parents=True, exist_ok=True)

    pem_path = str(client_dir / "aspera_bypass_rsa.pem")

    if os.path.exists(pem_path):
        return pem_path, Path(pem_path).read_text(encoding="utf-8")

    der_data = base64.b64decode(_BYPASS_RSA_DER_B64)
    key = load_der_private_key(der_data, password=None)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=NoEncryption(),
    )

    _write_file_restricted(pem_path, pem, 0o644)

    return pem_path, pem.decode("utf-8")


def _generate_self_signed_cert(private_key: rsa.RSAPrivateKey) -> Certificate:
    """Generate a self-signed X.509 certificate from an RSA private key."""
    from cryptography.hazmat.primitives.asymmetric import padding

    subject = issuer = Name([
        NameAttribute(NameOID.COUNTRY_NAME, "FR"),
        NameAttribute(NameOID.ORGANIZATION_NAME, "Test"),
        NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, "Test"),
        NameAttribute(NameOID.COMMON_NAME, "Test"),
    ])

    now = datetime.datetime.now(datetime.timezone.utc)
    pub_key = private_key.public_key()

    cert = (
        CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(pub_key)
        .serial_number(1)
        .not_valid_before(now - datetime.timedelta(seconds=5))
        .not_valid_after(now + datetime.timedelta(seconds=365 * 24 * 3600))
    )

    cert = cert.add_extension(
        BasicConstraints(ca=True, path_length=None),
        critical=True,
    )
    cert = cert.add_extension(
        SubjectKeyIdentifier.from_public_key(pub_key),
        critical=False,
    )
    cert = cert.add_extension(
        AuthorityKeyIdentifier.from_issuer_public_key(pub_key),
        critical=False,
    )

    cert = cert.sign(private_key, hashes.SHA256())
    return cert


def generate_fallback_keys() -> tuple[str, str]:
    """Generate self-signed fallback certificate and private key.

    Returns:
        Tuple of (key_path, cert_path)
    """
    client_dir = CLIENT_DIR
    client_dir.mkdir(parents=True, exist_ok=True)

    key_path = str(client_dir / "aspera_fallback_cert_private_key.pem")
    cert_path = str(client_dir / "aspera_fallback_cert.pem")

    if os.path.exists(key_path) and os.path.exists(cert_path):
        return key_path, cert_path

    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=4096,
    )

    cert = _generate_self_signed_cert(private_key)

    key_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=NoEncryption(),
    )
    _write_file_restricted(key_path, key_pem, 0o644)

    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    _write_file_restricted(cert_path, cert_pem, 0o644)

    return key_path, cert_path


def install_sdk(version: str | None = None) -> tuple[str, str, str]:
    """Install Aspera Transfer SDK.

    Args:
        version: Specific SDK version to install. None = latest.

    Returns:
        Tuple of (sdk_name, sdk_version, install_dir)
    """
    platform_name, arch = _get_platform_info()
    print(f"  Platform: {platform_name}/{arch}", file=sys.stderr)

    sdk_locations = _fetch_sdk_locations()

    platform_entries = [loc for loc in sdk_locations if loc["platform"] == platform_name]
    if not platform_entries:
        available = set(loc["platform"] for loc in sdk_locations)
        raise RuntimeError(
            f"No SDK available for platform '{platform_name}'. "
            f"Available: {sorted(available)}"
        )

    if version:
        version_entries = [e for e in platform_entries if e["version"] == version]
        if not version_entries:
            versions = sorted(set(e["version"] for e in platform_entries))
            raise RuntimeError(
                f"Version '{version}' not found for {platform_name}. "
                f"Available: {versions}"
            )
        selected = version_entries[0]
    else:
        selected = max(platform_entries, key=lambda e: e["version"])

    sdk_url = selected["url"]
    sdk_version = selected["version"]
    print(f"  SDK version: {sdk_version}", file=sys.stderr)
    print(f"  URL: {sdk_url}", file=sys.stderr)

    if SDK_DIR.exists() and any(SDK_DIR.iterdir()):
        backup_dir = f"{SDK_DIR}.{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"
        print(f"  Backing up existing SDK to {backup_dir}", file=sys.stderr)
        import shutil
        shutil.move(str(SDK_DIR), backup_dir)

    print("  Downloading SDK...", file=sys.stderr)
    with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        _download_file(sdk_url, tmp_path)
        _extract_sdk_archive(tmp_path, str(SDK_DIR))
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    ascp_path = SDK_BIN_DIR / "ascp"
    if not ascp_path.exists():
        for candidate in SDK_DIR.rglob("ascp"):
            if candidate.is_file() and not candidate.suffix:
                ascp_path = candidate
                break

    if not ascp_path.exists():
        raise RuntimeError(f"ascp binary not found after extraction in {SDK_DIR}")

    for f in SDK_BIN_DIR.iterdir():
        if f.is_file():
            try:
                os.chmod(f, 0o755)
            except OSError:
                pass

    _write_ascp_version_meta(str(ascp_path))

    return "IBM Aspera Transfer SDK", sdk_version, str(SDK_DIR)


def _fetch_sdk_locations() -> list[dict[str, str]]:
    """Fetch SDK location data from IBM SDK location service."""
    context = ssl.create_default_context()
    req = urllib.request.Request(
        SDK_LOCATION_URL,
        headers={"User-Agent": "aspera-client/0.2.0"},
    )
    with urllib.request.urlopen(req, context=context, timeout=30) as response:
        import yaml
        return yaml.safe_load(response.read().decode("utf-8"))


def _write_ascp_version_meta(ascp_path: str) -> None:
    """Create metadata XML file based on ascp version."""
    try:
        result = subprocess.run(
            [ascp_path, "-A"],
            capture_output=True,
            timeout=10,
        )
        if result.returncode == 0:
            output = result.stdout.decode("utf-8", errors="replace")
            import re
            m = re.search(r"version ([0-9.]+)", output)
            version = m.group(1) if m else "unknown"
        else:
            version = "unknown"
    except Exception:
        version = "unknown"

    meta_path = CLIENT_DIR / "meta-data.xml"
    meta_content = f"<product><name>IBM Aspera Transfer SDK</name><version>{version}</version></product>"
    _write_file_restricted(str(meta_path), meta_content.encode("utf-8"), 0o644)


def generate_aspera_conf() -> str:
    """Copy aspera.conf from SDK's etc directory.

    Returns:
        Path to aspera.conf
    """
    client_dir = CLIENT_DIR
    client_dir.mkdir(parents=True, exist_ok=True)
    conf_path = str(client_dir / "aspera.conf")

    if os.path.exists(conf_path):
        return conf_path

    sdk_conf = SDK_DIR / "etc" / "aspera.conf"
    if sdk_conf.exists():
        import shutil
        shutil.copy2(str(sdk_conf), conf_path)
        os.chmod(conf_path, 0o644)
        return conf_path

    conf_content = b"""<?xml version='1.0' encoding='UTF-8'?>
<CONF version="2">
<default>
    <file_system>
        <resume_suffix>.aspera-ckpt</resume_suffix>
        <partial_file_suffix>.partial</partial_file_suffix>
    </file_system>
</default>
</CONF>
"""
    _write_file_restricted(conf_path, conf_content, 0o644)
    return conf_path


def setup_complete(
    install_sdk_flag: bool = True,
    bypass_key_flag: bool = True,
    fallback_key_flag: bool = True,
    version: str | None = None,
) -> dict[str, Any]:
    """Run complete setup: SDK installation, key generation, and configuration."""
    results: dict[str, Any] = {
        "sdk": None,
        "bypass_key": None,
        "fallback_keys": None,
        "aspera_conf": None,
    }

    if install_sdk_flag:
        try:
            sdk_name, sdk_version, sdk_dir = install_sdk(version=version)
            results["sdk"] = {
                "name": sdk_name,
                "version": sdk_version,
                "directory": sdk_dir,
            }
            print(f"SDK installed: {sdk_name} {sdk_version} at {sdk_dir}")
        except Exception as e:
            print(f"SDK installation failed: {e}", file=sys.stderr)
            results["sdk_error"] = str(e)

    if bypass_key_flag:
        try:
            pem_path, _ = generate_bypass_key()
            results["bypass_key"] = pem_path
            print(f"Bypass key created: {pem_path}")
        except Exception as e:
            print(f"Bypass key generation failed: {e}", file=sys.stderr)
            results["bypass_key_error"] = str(e)

    if fallback_key_flag:
        try:
            key_path, cert_path = generate_fallback_keys()
            results["fallback_keys"] = {
                "key": key_path,
                "certificate": cert_path,
            }
            print(f"Fallback keys created: {key_path}, {cert_path}")
        except Exception as e:
            print(f"Fallback key generation failed: {e}", file=sys.stderr)
            results["fallback_keys_error"] = str(e)

    if SDK_DIR.exists():
        try:
            conf_path = generate_aspera_conf()
            results["aspera_conf"] = conf_path
            print(f"aspera.conf created: {conf_path}")
        except Exception as e:
            print(f"aspera.conf generation failed: {e}", file=sys.stderr)
            results["aspera_conf_error"] = str(e)

    return results
