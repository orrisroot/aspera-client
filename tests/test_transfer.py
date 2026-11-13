"""Tests for the ascp run: interrupts, retries and what is printed."""

from __future__ import annotations

import argparse
import os
from unittest.mock import MagicMock

import pytest

from aspera_client.cli import cmd_download
from aspera_client.core import transfer

TOKEN_DATA = {
    "transfer_specs": [
        {
            "transfer_spec": {
                "remote_host": "hsts.example.invalid",
                "token": "secret",
                "source_root": "/data",
                "paths": [{"source": "/a.bin"}],
            }
        }
    ]
}
RETRYABLE = min(transfer.RETRYABLE_EXIT_CODES)


def fake_ascp(monkeypatch, *return_codes: int, on_start=None) -> MagicMock:
    """Popen whose successive processes exit with the given codes."""
    codes = iter(return_codes)

    def start(cmd, **kwargs):
        if on_start:
            on_start()
        process = MagicMock()
        process.returncode = next(codes)
        return process

    popen = MagicMock(side_effect=start)
    monkeypatch.setattr(transfer.subprocess, "Popen", popen)
    monkeypatch.setattr(transfer.time, "sleep", lambda _: None)
    return popen


def test_interrupt_stops_ascp_and_propagates(monkeypatch, tmp_path, capsys) -> None:
    file_list = tmp_path / "files.txt"
    file_list.write_text("/a\n/b\n")
    process = MagicMock()
    process.wait.side_effect = [KeyboardInterrupt, 0]
    popen = MagicMock(return_value=process)
    monkeypatch.setattr(transfer.subprocess, "Popen", popen)

    with pytest.raises(KeyboardInterrupt):
        transfer._execute_ascp(
            cmd=["ascp"], env={}, file_list_path=str(file_list), quiet=True
        )

    process.terminate.assert_called_once()
    popen.assert_called_once()  # not retried
    assert not file_list.exists()
    assert capsys.readouterr() == ("", "")  # the interrupt says it, not this


def test_retries_keep_the_file_list_until_done(monkeypatch, tmp_path) -> None:
    file_list = tmp_path / "files.txt"
    file_list.write_text("/a\n/b\n")
    seen = []
    popen = fake_ascp(
        monkeypatch, RETRYABLE, 0, on_start=lambda: seen.append(file_list.exists())
    )

    code = transfer._execute_ascp(
        cmd=["ascp"], env={}, file_list_path=str(file_list), quiet=True
    )

    assert code == 0
    assert popen.call_count == 2
    assert seen == [True, True]
    assert not file_list.exists()


def test_quiet_success_prints_nothing(monkeypatch, capsys) -> None:
    fake_ascp(monkeypatch, RETRYABLE, 0)
    transfer._execute_ascp(cmd=["ascp"], env={}, file_list_path=None, quiet=True)
    assert capsys.readouterr() == ("", "")


def test_failure_is_reported_even_when_quiet(monkeypatch, capsys) -> None:
    fake_ascp(monkeypatch, 1)
    assert (
        transfer._execute_ascp(cmd=["ascp"], env={}, file_list_path=None, quiet=True)
        == 1
    )
    out, err = capsys.readouterr()
    assert out == ""
    assert err.count("Transfer failed with exit code 1") == 1


def test_success_is_reported_once(monkeypatch, tmp_path, capsys) -> None:
    ascp = tmp_path / "ascp"
    ascp.write_text("")
    monkeypatch.setattr(transfer, "get_ascp_path", lambda: str(ascp))
    fake_ascp(monkeypatch, 0)

    transfer.download_with_progress(
        token_data=TOKEN_DATA,
        local_dest=str(tmp_path / "out"),
        quiet=False,
        bypass_key=str(ascp),
    )

    out, err = capsys.readouterr()
    assert out.count("Transfer completed successfully") == 1
    assert "Final ascp command" in err
    assert "secret" not in out + err
    # The bypass key authenticates the token, so no key warning.
    assert "no SSH private key" not in err


def test_missing_keys_are_warned_even_when_quiet(monkeypatch, tmp_path, capsys) -> None:
    ascp = tmp_path / "ascp"
    ascp.write_text("")
    monkeypatch.setattr(transfer, "get_ascp_path", lambda: str(ascp))
    fake_ascp(monkeypatch, 0)
    transfer.download_with_progress(
        token_data=TOKEN_DATA, local_dest=str(tmp_path / "out"), quiet=True
    )
    assert "no SSH private key" in capsys.readouterr().err


def test_bypass_key_without_a_token_is_warned(monkeypatch, tmp_path, capsys) -> None:
    ascp = tmp_path / "ascp"
    ascp.write_text("")
    monkeypatch.setattr(transfer, "get_ascp_path", lambda: str(ascp))
    fake_ascp(monkeypatch, 0)
    spec = dict(TOKEN_DATA["transfer_specs"][0]["transfer_spec"], token="")
    transfer.download_with_progress(
        token_data={"transfer_specs": [{"transfer_spec": spec}]},
        local_dest=str(tmp_path / "out"),
        quiet=True,
        bypass_key=str(ascp),
    )
    assert "no SSH private key" in capsys.readouterr().err


def test_second_interrupt_while_stopping_kills_ascp() -> None:
    process = MagicMock()
    process.wait.side_effect = KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt):
        transfer._stop_process(process)
    process.terminate.assert_called_once()
    process.kill.assert_called_once()


def test_cli_reports_an_interrupt_before_the_transfer(monkeypatch, capsys) -> None:
    # Ctrl+C while the token is requested, before ascp starts.
    monkeypatch.setattr(cmd_download, "load_config", lambda _: {})
    monkeypatch.setattr(cmd_download, "resolve_host_port", lambda *_: ("h", 443))
    monkeypatch.setattr(cmd_download, "AsperaConnection", MagicMock())
    monkeypatch.setattr(
        cmd_download, "download", MagicMock(side_effect=KeyboardInterrupt)
    )
    args = argparse.Namespace(
        config="config.yaml",
        url=None,
        user="u",
        password="p",
        remote_path=["/a"],
        local_dest=os.curdir,
        dry_run=False,
        resume=False,
        format="text",
        quiet=True,
        multi_session=1,
        gen4=False,
    )

    assert cmd_download.cmd_download(args) == 130
    assert "Interrupted" in capsys.readouterr().err
