"""Tests for SDK installation: platform names, archive formats and version order."""

from __future__ import annotations

import importlib
import io
import os
import stat
import tarfile
import zipfile
from pathlib import Path

import pytest

from aspera_client import AsperaEnvironment

# The package exports a function of the same name, which shadows the module attribute.
setup = importlib.import_module("aspera_client.api.setup_environment")

ASCP = b"#!/bin/sh\necho 'ascp version 1.1.9'\n"
TOP = "ibm-aspera-transfer-sdk-1.1.9"


def make_zip(path: Path) -> None:
    """An SDK archive laid out as IBM ships it for macOS."""
    with zipfile.ZipFile(path, "w") as zf:
        for name, data, mode in (
            (f"{TOP}/bin/ascp", ASCP, 0o755),
            (f"{TOP}/sbin/transferd", b"x", 0o755),
            (f"{TOP}/etc/aspera.conf", b"<CONF/>", 0o644),
            (f"{TOP}/api/transfer.proto", b"x", 0o644),
        ):
            info = zipfile.ZipInfo(name)
            info.external_attr = (stat.S_IFREG | mode) << 16
            zf.writestr(info, data)


def make_tar(path: Path) -> None:
    """An SDK archive laid out as IBM ships it for Linux."""
    with tarfile.open(path, "w:gz") as tar:
        for name, data, mode in (
            (f"{TOP}/bin/ascp", ASCP, 0o755),
            (f"{TOP}/etc/aspera.conf", b"<CONF/>", 0o644),
            (f"{TOP}/api/transfer.proto", b"x", 0o644),
        ):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = mode
            tar.addfile(info, io.BytesIO(data))


@pytest.mark.parametrize(
    "system, machine, expected",
    [
        ("Darwin", "arm64", "osx-arm64"),
        ("Darwin", "x86_64", "osx-x86_64"),
        ("Linux", "aarch64", "linux-arm64"),
        ("Linux", "x86_64", "linux-x86_64"),
        ("Linux", "s390x", "linux-s390"),
        ("Windows", "AMD64", "windows-x86_64"),
    ],
)
def test_platform_names_follow_ibm_listing(
    monkeypatch, system, machine, expected
) -> None:
    monkeypatch.setattr(setup.platform, "system", lambda: system)
    monkeypatch.setattr(setup.platform, "machine", lambda: machine)
    assert setup._get_platform_info()[0] == expected


def test_versions_are_ordered_numerically() -> None:
    versions = ["1.1.9", "1.1.10", "1.1.2"]
    assert max(versions, key=setup._version_key) == "1.1.10"


@pytest.mark.parametrize("make", [make_zip, make_tar])
def test_extract_keeps_runtime_folders_and_permissions(tmp_path, make) -> None:
    archive = tmp_path / "sdk"
    make(archive)
    dest = tmp_path / "out"
    setup._extract_sdk_archive(str(archive), str(dest), quiet=True)

    assert (dest / "bin" / "ascp").read_bytes() == ASCP
    assert os.access(dest / "bin" / "ascp", os.X_OK)
    assert (dest / "etc" / "aspera.conf").exists()
    assert not (dest / "api").exists()
    if make is make_zip:
        assert os.access(dest / "sbin" / "transferd", os.X_OK)


def test_zip_entry_outside_destination_is_skipped(tmp_path) -> None:
    archive = tmp_path / "sdk.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(f"{TOP}/bin/ascp", ASCP)
        zf.writestr(f"{TOP}/bin/../../evil", b"x")
    dest = tmp_path / "out"
    setup._extract_sdk_archive(str(archive), str(dest), quiet=True)
    assert (dest / "bin" / "ascp").exists()
    assert not (tmp_path / "evil").exists()


def test_zip_symlinks_inside_the_sdk_are_kept(tmp_path) -> None:
    archive = tmp_path / "sdk.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(f"{TOP}/lib/libfoo.so.1", b"lib")
        for name, link in (
            (f"{TOP}/lib/libfoo.so", "libfoo.so.1"),
            (f"{TOP}/lib/escape", "../../../outside"),
        ):
            info = zipfile.ZipInfo(name)
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            zf.writestr(info, link)
    dest = tmp_path / "out"
    setup._extract_sdk_archive(str(archive), str(dest), quiet=True)
    assert os.readlink(dest / "lib" / "libfoo.so") == "libfoo.so.1"
    assert (dest / "lib" / "libfoo.so").read_bytes() == b"lib"
    assert not (dest / "lib" / "escape").exists()
    assert not (dest / "lib" / "escape").is_symlink()


def test_tar_extracts_only_the_runtime_folders(tmp_path) -> None:
    archive = tmp_path / "sdk.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        for name, data in (
            (f"{TOP}/bin/ascp", ASCP),
            (f"{TOP}/api/transferd.proto", b"x"),
            (f"{TOP}/bin/../../evil", b"x"),
        ):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o755
            tar.addfile(info, io.BytesIO(data))
        link = tarfile.TarInfo(f"{TOP}/lib/libstdc++.so.6")
        link.type = tarfile.SYMTYPE
        link.linkname = "libstdc++.so.6.0.28"
        tar.addfile(link)
    dest = tmp_path / "out"
    setup._extract_sdk_archive(str(archive), str(dest), quiet=True)
    assert sorted(os.listdir(dest)) == ["bin", "lib"]
    assert os.readlink(dest / "lib" / "libstdc++.so.6") == "libstdc++.so.6.0.28"
    assert not (tmp_path / "evil").exists()


@pytest.mark.parametrize(
    "names, expected",
    [
        ([f"{TOP}/", f"{TOP}/bin/ascp"], TOP),
        # Finder's resource forks do not count as a wrapper.
        (["__MACOSX/._x", f"{TOP}/bin/ascp"], TOP),
        # An unwrapped archive has nothing to strip.
        (["bin/ascp", "lib/x"], ""),
        (["bin/ascp"], ""),
        # Loose files beside the wrapper do not hide it.
        (["README.txt", ".DS_Store", f"{TOP}/bin/ascp"], TOP),
    ],
)
def test_top_level(names, expected) -> None:
    assert setup._top_level(names) == expected


def test_zip_made_by_finder_is_extracted(tmp_path) -> None:
    archive = tmp_path / "sdk.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(f"__MACOSX/{TOP}/bin/._ascp", b"fork")
        info = zipfile.ZipInfo(f"{TOP}/bin/ascp")
        info.external_attr = (stat.S_IFREG | 0o755) << 16
        zf.writestr(info, ASCP)
    dest = tmp_path / "out"
    setup._extract_sdk_archive(str(archive), str(dest), quiet=True)
    assert (dest / "bin" / "ascp").read_bytes() == ASCP
    assert sorted(os.listdir(dest)) == ["bin"]


def symlink_entry(name: str, link: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name)
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    return info


def test_zip_chain_of_links_cannot_leave_the_destination(tmp_path) -> None:
    archive = tmp_path / "sdk.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(symlink_entry("lib/a", ".."), "..")
        zf.writestr(symlink_entry("lib/a/b", ".."), "..")
        zf.writestr("lib/a/b/evil", b"x")
    dest = tmp_path / "out"
    setup._extract_sdk_archive(str(archive), str(dest), quiet=True)
    assert not (tmp_path / "evil").exists()
    assert not (tmp_path / "b").exists()


def test_zip_link_over_a_folder_is_skipped(tmp_path) -> None:
    archive = tmp_path / "sdk.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(f"{TOP}/lib/Versions/x", b"x")
        zf.writestr(symlink_entry(f"{TOP}/lib/Versions", "A"), "A")
    dest = tmp_path / "out"
    setup._extract_sdk_archive(str(archive), str(dest), quiet=True)
    assert (dest / "lib" / "Versions" / "x").exists()


def test_zip_without_unix_modes_still_gets_executables(tmp_path) -> None:
    archive = tmp_path / "sdk.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        for name in (f"{TOP}/bin/ascp", f"{TOP}/sbin/transferd"):
            info = zipfile.ZipInfo(name)
            info.create_system = 0  # made off Unix: no mode bits
            zf.writestr(info, ASCP)
    dest = tmp_path / "out"
    setup._extract_sdk_archive(str(archive), str(dest), quiet=True)
    assert os.access(dest / "bin" / "ascp", os.X_OK)
    assert os.access(dest / "sbin" / "transferd", os.X_OK)


def test_zip_with_a_readme_beside_the_wrapper(tmp_path) -> None:
    archive = tmp_path / "sdk.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("README.txt", b"x")
        zf.writestr(f"{TOP}/bin/ascp", ASCP)
    dest = tmp_path / "out"
    setup._extract_sdk_archive(str(archive), str(dest), quiet=True)
    assert (dest / "bin" / "ascp").read_bytes() == ASCP


def install_with(monkeypatch, tmp_path, write_archive, entries=None):
    monkeypatch.setattr(setup.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(setup.platform, "machine", lambda: "arm64")
    url = "https://example.invalid/sdk.zip"
    monkeypatch.setattr(
        setup, "_fetch_sdk_locations", lambda: entries or listing("osx-arm64", url)
    )
    monkeypatch.setattr(
        setup,
        "_download_file",
        lambda src, dest, quiet=False: write_archive(Path(dest)),
    )
    return AsperaEnvironment(base_dir=str(tmp_path / "sdk"))


def test_failed_install_keeps_the_installed_sdk(monkeypatch, tmp_path) -> None:
    def no_ascp(path: Path) -> None:
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr(f"{TOP}/etc/aspera.conf", b"x")

    env = install_with(monkeypatch, tmp_path, no_ascp)
    old = Path(env.base_dir) / "bin" / "ascp"
    old.parent.mkdir(parents=True)
    old.write_bytes(b"old")

    with pytest.raises(RuntimeError, match="ascp binary not found"):
        setup.install_sdk(quiet=True, env=env)

    assert old.read_bytes() == b"old"
    assert sorted(os.listdir(tmp_path)) == ["sdk"]  # no backup, no staging left


def test_install_replaces_and_backs_up_the_installed_sdk(monkeypatch, tmp_path) -> None:
    env = install_with(monkeypatch, tmp_path, make_zip)
    old = Path(env.base_dir) / "bin" / "ascp"
    old.parent.mkdir(parents=True)
    old.write_bytes(b"old")

    setup.install_sdk(quiet=True, env=env)

    assert old.read_bytes() == ASCP
    backups = [p for p in os.listdir(tmp_path) if p.startswith("sdk.")]
    assert len(backups) == 1
    assert (tmp_path / backups[0] / "bin" / "ascp").read_bytes() == b"old"


def test_requested_version_found_only_as_universal(monkeypatch, tmp_path) -> None:
    entries = [
        {"platform": "osx-arm64", "version": "1.1.9", "url": "a.zip"},
        {"platform": "osx-universal", "version": "1.1.10", "url": "u.zip"},
    ]
    env = install_with(monkeypatch, tmp_path, make_zip, entries)
    assert setup.install_sdk(version="1.1.10", quiet=True, env=env)[1] == "1.1.10"


def test_machine_build_preferred_over_universal_of_the_same_version(
    monkeypatch, tmp_path
) -> None:
    entries = [
        {"platform": "osx-universal", "version": "1.1.9", "url": "u.zip"},
        {"platform": "osx-arm64", "version": "1.1.9", "url": "a.zip"},
    ]
    fetched = []
    env = install_with(monkeypatch, tmp_path, make_zip, entries)
    monkeypatch.setattr(
        setup,
        "_download_file",
        lambda src, dest, quiet=False: (fetched.append(src), make_zip(Path(dest))),
    )
    setup.install_sdk(quiet=True, env=env)
    assert fetched == ["a.zip"]


def listing(platform_name: str, url: str) -> list[dict[str, str]]:
    return [
        {"platform": platform_name, "version": "1.1.9", "url": url},
        {"platform": platform_name, "version": "1.1.10", "url": url},
        {"platform": "linux-x86_64", "version": "1.1.9", "url": "x.tar.gz"},
    ]


@pytest.mark.parametrize(
    "listed, machine",
    [
        ("osx-arm64", "arm64"),
        # A Mac architecture IBM does not list falls back to the universal build.
        ("osx-universal", "arm64"),
    ],
)
def test_install_sdk_on_macos_unpacks_the_zip(
    monkeypatch, tmp_path, listed, machine
) -> None:
    monkeypatch.setattr(setup.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(setup.platform, "machine", lambda: machine)
    url = f"https://example.invalid/sdk-{listed}.zip"
    monkeypatch.setattr(setup, "_fetch_sdk_locations", lambda: listing(listed, url))
    fetched = []

    def fake_download(src: str, dest: str, quiet: bool = False) -> None:
        fetched.append((src, dest))
        make_zip(Path(dest))

    monkeypatch.setattr(setup, "_download_file", fake_download)
    env = AsperaEnvironment(base_dir=str(tmp_path / "sdk"))

    _, version, directory = setup.install_sdk(quiet=True, env=env)

    assert version == "1.1.10"
    assert fetched[0][0] == url
    assert fetched[0][1].endswith(".zip")
    assert os.access(Path(directory) / "bin" / "ascp", os.X_OK)
