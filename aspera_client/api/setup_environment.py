"""High-level Python API for setting up Aspera SDK, keys, and configurations."""

from __future__ import annotations

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
    CertificateBuilder,
    Name,
    NameAttribute,
    Certificate,
    BasicConstraints,
    SubjectKeyIdentifier,
    AuthorityKeyIdentifier,
)
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives.serialization import (
    PrivateFormat,
    NoEncryption,
    load_der_private_key,
)

from ..models.environment import AsperaEnvironment

_BYPASS_DER_PATH = Path(__file__).parent.parent / "data" / "bypass_rsa.der"
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


def _download_file(url: str, dest_path: str, quiet: bool = False) -> None:
    """Download a file from URL to dest_path."""
    context = ssl.create_default_context()
    req = urllib.request.Request(url, headers={"User-Agent": "aspera-client/0.1.0"})
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
                if total and not quiet:
                    pct = downloaded / total * 100
                    print(f"  Downloading: {pct:.1f}%", end="\r", file=sys.stderr)
        if not quiet:
            print(file=sys.stderr)


def _extract_sdk_archive(archive_path: str, dest_dir: str, quiet: bool = False) -> None:
    """Extract SDK archive (tar.gz) to dest_dir, extracting only runtime folders."""
    if not quiet:
        print(f"  Extracting to {dest_dir}...", file=sys.stderr)
    with tarfile.open(archive_path, "r:gz") as tar:
        all_names = tar.getnames()

        top_level = ""
        for n in all_names:
            parts = n.split("/")
            if len(parts) > 1 and parts[0]:
                top_level = parts[0]
                break

        extract_map = {}
        for member in tar.getmembers():
            parts = member.name.split("/")

            if top_level and len(parts) > 1 and parts[0] == top_level:
                effective_parts = parts[1:]
            else:
                effective_parts = parts

            if member.isdir() and effective_parts == [] and top_level:
                continue

            if member.isdir():
                if effective_parts and effective_parts[0] in _RUNTIME_FOLDERS:
                    new_name = "/".join(effective_parts)
                    extract_map[member.name] = new_name
            elif member.isfile():
                if effective_parts and effective_parts[0] in _RUNTIME_FOLDERS:
                    if ".." in member.name:
                        if not quiet:
                            print(
                                f"  Skipping suspicious path: {member.name}",
                                file=sys.stderr,
                            )
                        continue
                    new_name = "/".join(effective_parts)
                    extract_map[member.name] = new_name

        for member in tar.getmembers():
            if member.name not in extract_map:
                continue
            member.name = extract_map[member.name]

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


def _generate_self_signed_cert(private_key: rsa.RSAPrivateKey) -> Certificate:
    """Generate a self-signed X.509 certificate from an RSA private key."""
    subject = issuer = Name(
        [
            NameAttribute(NameOID.COUNTRY_NAME, "FR"),
            NameAttribute(NameOID.ORGANIZATION_NAME, "Test"),
            NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, "Test"),
            NameAttribute(NameOID.COMMON_NAME, "Test"),
        ]
    )

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


def _fetch_sdk_locations() -> list[dict[str, str]]:
    """Fetch SDK location data from IBM SDK location service."""
    context = ssl.create_default_context()
    req = urllib.request.Request(
        SDK_LOCATION_URL,
        headers={"User-Agent": "aspera-client/0.1.0"},
    )
    with urllib.request.urlopen(req, context=context, timeout=30) as response:
        import yaml

        return yaml.safe_load(response.read().decode("utf-8"))


def _write_ascp_version_meta(
    ascp_path: str, env: AsperaEnvironment | None = None
) -> None:
    """Create metadata XML file based on ascp version."""
    env = env or AsperaEnvironment()
    client_dir = Path(env.client_dir)

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

    meta_path = client_dir / "meta-data.xml"
    meta_content = f"<product><name>IBM Aspera Transfer SDK</name><version>{version}</version></product>"
    _write_file_restricted(str(meta_path), meta_content.encode("utf-8"), 0o644)


def generate_bypass_key(env: AsperaEnvironment | None = None) -> tuple[str, str]:
    """Generate bypass RSA private key from embedded DER data."""
    env = env or AsperaEnvironment()
    client_dir = Path(env.client_dir)
    client_dir.mkdir(parents=True, exist_ok=True)

    pem_path = str(client_dir / "aspera_bypass_rsa.pem")

    if os.path.exists(pem_path):
        return pem_path, Path(pem_path).read_text(encoding="utf-8")

    try:
        der_data = _BYPASS_DER_PATH.read_bytes()
    except FileNotFoundError:
        raise RuntimeError(
            f"Bypass key file not found: {_BYPASS_DER_PATH}. "
            "Run 'install_tools()' to install it."
        ) from None
    key = load_der_private_key(der_data, password=None)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=NoEncryption(),
    )

    _write_file_restricted(pem_path, pem, 0o644)

    return pem_path, pem.decode("utf-8")


def generate_fallback_keys(env: AsperaEnvironment | None = None) -> tuple[str, str]:
    """Generate self-signed fallback certificate and private key."""
    env = env or AsperaEnvironment()
    client_dir = Path(env.client_dir)
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


def install_sdk(
    version: str | None = None,
    quiet: bool = False,
    env: AsperaEnvironment | None = None,
) -> tuple[str, str, str]:
    """Install Aspera Transfer SDK."""
    env = env or AsperaEnvironment()
    sdk_dir = Path(env.base_dir)
    sdk_bin_dir = Path(env.bin_dir)

    platform_name, arch = _get_platform_info()
    if not quiet:
        print(f"  Platform: {platform_name}/{arch}", file=sys.stderr)

    sdk_locations = _fetch_sdk_locations()

    platform_entries = [
        loc for loc in sdk_locations if loc["platform"] == platform_name
    ]
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
    if not quiet:
        print(f"  SDK version: {sdk_version}", file=sys.stderr)
        print(f"  URL: {sdk_url}", file=sys.stderr)

    if sdk_dir.exists() and any(sdk_dir.iterdir()):
        backup_dir = f"{sdk_dir}.{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"
        if not quiet:
            print(f"  Backing up existing SDK to {backup_dir}", file=sys.stderr)
        import shutil

        shutil.move(str(sdk_dir), backup_dir)

    if not quiet:
        print("  Downloading SDK...", file=sys.stderr)
    with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        _download_file(sdk_url, tmp_path, quiet=quiet)
        _extract_sdk_archive(tmp_path, str(sdk_dir), quiet=quiet)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    ascp_path = sdk_bin_dir / "ascp"
    if not ascp_path.exists():
        for candidate in sdk_dir.rglob("ascp"):
            if candidate.is_file() and not candidate.suffix:
                ascp_path = candidate
                break

    if not ascp_path.exists():
        raise RuntimeError(f"ascp binary not found after extraction in {sdk_dir}")

    for f in sdk_bin_dir.iterdir():
        if f.is_file():
            try:
                os.chmod(f, 0o755)
            except OSError:
                pass

    _write_ascp_version_meta(str(ascp_path), env)

    return "IBM Aspera Transfer SDK", sdk_version, str(sdk_dir)


def generate_aspera_conf(env: AsperaEnvironment | None = None) -> str:
    """Copy aspera.conf from SDK's etc directory."""
    env = env or AsperaEnvironment()
    client_dir = Path(env.client_dir)
    client_dir.mkdir(parents=True, exist_ok=True)
    conf_path = str(client_dir / "aspera.conf")

    if os.path.exists(conf_path):
        return conf_path

    sdk_conf = Path(env.base_dir) / "etc" / "aspera.conf"
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


def setup_environment(
    install_sdk_flag: bool = True,
    bypass_key_flag: bool = True,
    fallback_key_flag: bool = True,
    version: str | None = None,
    quiet: bool = False,
    env: AsperaEnvironment | None = None,
) -> dict[str, Any]:
    """Setup Aspera environment: SDK installation, key generation, and configuration."""
    env = env or AsperaEnvironment()

    results: dict[str, Any] = {
        "sdk": None,
        "bypass_key": None,
        "fallback_keys": None,
        "aspera_conf": None,
    }

    if install_sdk_flag:
        try:
            sdk_name, sdk_version, sdk_dir = install_sdk(
                version=version, quiet=quiet, env=env
            )
            results["sdk"] = {
                "name": sdk_name,
                "version": sdk_version,
                "directory": sdk_dir,
            }
            if not quiet:
                print(f"SDK installed: {sdk_name} {sdk_version} at {sdk_dir}")
        except Exception as e:
            if not quiet:
                print(f"SDK installation failed: {e}", file=sys.stderr)
            results["sdk_error"] = str(e)

    if bypass_key_flag:
        try:
            pem_path, _ = generate_bypass_key(env=env)
            results["bypass_key"] = pem_path
            if not quiet:
                print(f"Bypass key created: {pem_path}")
        except Exception as e:
            if not quiet:
                print(f"Bypass key generation failed: {e}", file=sys.stderr)
            results["bypass_key_error"] = str(e)

    if fallback_key_flag:
        try:
            key_path, cert_path = generate_fallback_keys(env=env)
            results["fallback_keys"] = {
                "key": key_path,
                "certificate": cert_path,
            }
            if not quiet:
                print(f"Fallback keys created: {key_path}, {cert_path}")
        except Exception as e:
            if not quiet:
                print(f"Fallback key generation failed: {e}", file=sys.stderr)
            results["fallback_keys_error"] = str(e)

    if Path(env.base_dir).exists():
        try:
            conf_path = generate_aspera_conf(env=env)
            results["aspera_conf"] = conf_path
            if not quiet:
                print(f"aspera.conf created: {conf_path}")
        except Exception as e:
            if not quiet:
                print(f"aspera.conf generation failed: {e}", file=sys.stderr)
            results["aspera_conf_error"] = str(e)

    return results
