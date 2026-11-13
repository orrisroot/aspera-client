"""High-level Python API for setting up Aspera SDK, keys, and configurations."""

from __future__ import annotations

import datetime
import os
import platform
import re
import shutil
import ssl
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
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
# Finder adds this folder of resource forks to the zips it makes.
_MACOS_METADATA = "__MACOSX/"
SDK_LOCATION_URL = "https://ibm.biz/sdk_location"


def _get_platform_info() -> tuple[str, str]:
    """Get platform name and architecture for SDK download, in IBM's naming."""
    sys_name = platform.system().lower()
    machine = platform.machine().lower()

    # The names IBM's SDK listing uses (https://ibm.biz/sdk_location).
    arch_map = {
        "x86_64": "x86_64",
        "amd64": "x86_64",
        "aarch64": "arm64",
        "arm64": "arm64",
        "ppc64le": "ppc64le",
        "ppc64": "ppc64",
        "s390x": "s390",
    }
    arch = arch_map.get(machine, machine)

    if sys_name == "darwin":
        platform_name = f"osx-{arch}"
    else:
        platform_name = f"{sys_name}-{arch}"

    return platform_name, arch


def _version_key(version: str) -> tuple[int, ...]:
    """Order versions numerically, so 1.1.10 comes after 1.1.9."""
    return tuple(int(x) for x in re.findall(r"\d+", version))


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


def _top_level(names: list[str]) -> str:
    """The folder wrapping the SDK, or "" when the archive has none.

    Files beside the folder (a README, .DS_Store) do not count, nor does Finder's
    __MACOSX folder.
    """
    folders = {
        n.split("/", 1)[0]
        for n in names
        if "/" in n.strip("/") or n.endswith("/")
        if not n.startswith(_MACOS_METADATA)
    }
    if len(folders) == 1:
        folder = folders.pop()
        # An unwrapped archive holding only bin/ has no wrapper to strip.
        if folder not in _RUNTIME_FOLDERS:
            return folder
    return ""


def _runtime_parts(name: str, top_level: str, quiet: bool) -> list[str] | None:
    """The path to extract an entry to, or None for an entry left out.

    Only the runtime folders are kept, and nothing may leave the destination.
    """
    if name.startswith(_MACOS_METADATA):
        return None
    parts = [p for p in name.split("/") if p and p != "."]
    if top_level and parts and parts[0] == top_level:
        parts = parts[1:]
    if not parts or parts[0] not in _RUNTIME_FOLDERS:
        return None
    if ".." in parts or name.startswith("/"):
        if not quiet:
            print(f"  Skipping suspicious path: {name}", file=sys.stderr)
        return None
    return parts


def _within(root: str | Path, path: str | Path) -> bool:
    """Whether path, following the symlinks already on disk, stays inside root."""
    root = os.path.realpath(root)
    path = os.path.realpath(path)
    return path == root or path.startswith(root + os.sep)


def _extract_sdk_archive(archive_path: str, dest_dir: str, quiet: bool = False) -> None:
    """Extract SDK archive (tar.gz, or zip on macOS) to dest_dir, extracting only runtime folders."""
    if not quiet:
        print(f"  Extracting to {dest_dir}...", file=sys.stderr)
    if zipfile.is_zipfile(archive_path):
        _extract_zip_archive(archive_path, dest_dir, quiet=quiet)
    else:
        _extract_tar_archive(archive_path, dest_dir, quiet=quiet)

    # An archive may not carry permissions (a zip made off Unix), and these hold
    # only programs.
    for folder in ("bin", "sbin"):
        exe_dir = Path(dest_dir) / folder
        if exe_dir.is_dir():
            for f in exe_dir.iterdir():
                if f.is_file() and not f.is_symlink():
                    try:
                        os.chmod(f, 0o755)
                    except OSError:
                        pass


def _extract_zip_archive(archive_path: str, dest_dir: str, quiet: bool = False) -> None:
    """Extract the runtime folders of a zip, as IBM ships the SDK for macOS."""
    with zipfile.ZipFile(archive_path) as zf:
        top_level = _top_level(zf.namelist())
        for info in zf.infolist():
            parts = _runtime_parts(info.filename, top_level, quiet)
            if parts is None:
                continue
            target = Path(dest_dir, *parts)
            # Checked against the disk, not the name: a link extracted earlier can
            # turn a harmless-looking path into one leading out of dest_dir.
            if not _within(dest_dir, target.parent):
                if not quiet:
                    print(
                        f"  Skipping path leaving the SDK: {info.filename}",
                        file=sys.stderr,
                    )
                continue
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            # zipfile keeps the Unix file type and permissions in the upper bits,
            # but extracts every entry as a regular file without them.
            unix_mode = info.external_attr >> 16
            if stat.S_ISLNK(unix_mode):
                link = zf.read(info).decode("utf-8")
                if not _within(dest_dir, target.parent / link):
                    if not quiet:
                        print(
                            f"  Skipping link leaving the SDK: {info.filename}",
                            file=sys.stderr,
                        )
                    continue
                if target.is_symlink() or target.is_file():
                    target.unlink()
                elif target.exists():
                    if not quiet:
                        print(
                            f"  Skipping link over a folder: {info.filename}",
                            file=sys.stderr,
                        )
                    continue
                os.symlink(link, target)
                continue
            with zf.open(info) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
            if unix_mode & 0o777:
                os.chmod(target, unix_mode & 0o777)


def _extract_tar_archive(archive_path: str, dest_dir: str, quiet: bool = False) -> None:
    """Extract the runtime folders of a tar.gz, as IBM ships the SDK for Linux."""
    with tarfile.open(archive_path, "r:gz") as tar:
        top_level = _top_level(tar.getnames())
        has_data_filter = hasattr(tarfile, "data_filter")
        selected = []
        for member in tar.getmembers():
            if not (member.isdir() or member.isfile() or member.issym()):
                continue
            parts = _runtime_parts(member.name, top_level, quiet)
            if parts is None:
                continue
            if member.issym() and not has_data_filter:
                # Without the data filter nothing checks where a chain of links
                # leads, so links are left out rather than trusted.
                continue
            member.name = "/".join(parts)
            selected.append(member)

        selected.sort(key=lambda m: (not m.isdir(), m.name))
        # Only the selected members, and through the data filter, which checks each
        # path and link against the disk, so nothing outside dest_dir is written.
        if has_data_filter:
            tar.extractall(path=dest_dir, members=selected, filter="data")
        else:
            tar.extractall(path=dest_dir, members=selected)


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


def _find_ascp(sdk_dir: Path) -> Path | None:
    """The ascp binary in an unpacked SDK: bin/ascp, or wherever the archive put it."""
    ascp_path = sdk_dir / "bin" / "ascp"
    if ascp_path.is_file():
        return ascp_path
    for candidate in sdk_dir.rglob("ascp"):
        if candidate.is_file() and not candidate.suffix:
            return candidate
    return None


def install_sdk(
    version: str | None = None,
    quiet: bool = False,
    env: AsperaEnvironment | None = None,
) -> tuple[str, str, str]:
    """Install Aspera Transfer SDK."""
    env = env or AsperaEnvironment()
    sdk_dir = Path(env.base_dir)

    platform_name, arch = _get_platform_info()
    if not quiet:
        print(f"  Platform: {platform_name}/{arch}", file=sys.stderr)

    sdk_locations = _fetch_sdk_locations()

    platform_entries = [
        loc for loc in sdk_locations if loc["platform"] == platform_name
    ]
    if platform_name.startswith("osx-"):
        # IBM also ships a universal build that runs on either Mac architecture.
        platform_entries += [
            loc for loc in sdk_locations if loc["platform"] == "osx-universal"
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
        platform_entries = version_entries
    # The newest version, and of one version the build for this machine over the
    # universal one.
    selected = max(
        platform_entries,
        key=lambda e: (_version_key(e["version"]), e["platform"] == platform_name),
    )

    sdk_url = selected["url"]
    sdk_version = selected["version"]
    if not quiet:
        print(f"  SDK version: {sdk_version}", file=sys.stderr)
        print(f"  URL: {sdk_url}", file=sys.stderr)

    if not quiet:
        print("  Downloading SDK...", file=sys.stderr)
    suffix = ".zip" if sdk_url.lower().endswith(".zip") else ".tar.gz"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp_path = tmp.name

    # Unpacked aside and moved into place only once ascp is there, so a failed
    # download or extraction leaves the installed SDK as it was.
    sdk_dir.parent.mkdir(parents=True, exist_ok=True)
    staging_dir = Path(tempfile.mkdtemp(prefix=f".{sdk_dir.name}-", dir=sdk_dir.parent))
    try:
        _download_file(sdk_url, tmp_path, quiet=quiet)
        _extract_sdk_archive(tmp_path, str(staging_dir), quiet=quiet)
        staged_ascp = _find_ascp(staging_dir)
        if staged_ascp is None:
            raise RuntimeError(f"ascp binary not found after extraction in {sdk_dir}")
    except BaseException:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    if sdk_dir.exists() and any(sdk_dir.iterdir()):
        backup_dir = f"{sdk_dir}.{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"
        if not quiet:
            print(f"  Backing up existing SDK to {backup_dir}", file=sys.stderr)
        shutil.move(str(sdk_dir), backup_dir)
    elif sdk_dir.exists():
        sdk_dir.rmdir()
    os.replace(staging_dir, sdk_dir)
    ascp_path = sdk_dir / staged_ascp.relative_to(staging_dir)

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
