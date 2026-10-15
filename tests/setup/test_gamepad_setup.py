# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES.
# SPDX-License-Identifier: Apache-2.0

"""Validate USB startup boundaries and installation without changing host devices."""

import ast
import ctypes as c
import importlib.util
from pathlib import Path
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).parents[2]
spec = importlib.util.spec_from_file_location("setup_gamepads", ROOT / "scripts/setup_gamepads.py")
setup_gamepads = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup_gamepads)


@pytest.fixture
def usb(monkeypatch):
    library = Mock()
    transfers = []

    def pointer(out, value):
        out._obj.value = value
        return 0

    def descriptor(device, out):
        out._obj.vendor, out._obj.product = 0x057E, 0x2069
        return 0

    def transfer(handle, endpoint, data, length, count, timeout):
        if endpoint == 0x02:
            transfers.append(bytes(data[:length]))
            count._obj.value = length
        else:
            assert endpoint == 0x82
            response = transfers[-1][:4]
            c.memmove(data, response, len(response))
            count._obj.value = len(response)
        return 0

    library.libusb_init.side_effect = lambda out: pointer(out, 1)
    library.libusb_wrap_sys_device.side_effect = lambda ctx, fd, out: pointer(out, 2)
    library.libusb_get_device_descriptor.side_effect = descriptor
    library.libusb_claim_interface.return_value = 0
    library.libusb_bulk_transfer.side_effect = transfer
    monkeypatch.setattr(setup_gamepads, "find_library", lambda _: "libusb.so")
    monkeypatch.setattr(setup_gamepads.c, "CDLL", lambda _: library)
    opened, closed = Mock(return_value=123), Mock()
    monkeypatch.setattr(setup_gamepads.os, "open", opened)
    monkeypatch.setattr(setup_gamepads.os, "close", closed)
    return library, transfers, opened, closed


def test_startup_preserves_kernel_hid_driver(usb):
    library, transfers, opened, closed = usb
    setup_gamepads.initialize("/dev/bus/usb/001/019")
    opened.assert_called_once_with(
        "/dev/bus/usb/001/019", setup_gamepads.os.O_RDWR | setup_gamepads.os.O_NOFOLLOW
    )
    assert [command[3] for command in transfers] == [0x0A, 0x0D]
    assert transfers[0][8] == 0x09  # Standard HID report, not the opaque vendor report.
    assert library.libusb_claim_interface.call_args.args[1] == 1
    assert library.libusb_release_interface.call_args.args[1] == 1
    library.libusb_detach_kernel_driver.assert_not_called()
    library.libusb_reset_device.assert_not_called()
    library.libusb_close.assert_called_once()
    library.libusb_exit.assert_called_once()
    closed.assert_called_once_with(123)


def test_other_usb_device_is_never_claimed(usb):
    library, transfers, _, closed = usb

    def descriptor(device, out):
        out._obj.vendor, out._obj.product = 0x054C, 0x0CE6
        return 0

    library.libusb_get_device_descriptor.side_effect = descriptor
    with pytest.raises(ValueError, match="only supports"):
        setup_gamepads.initialize("/dev/bus/usb/001/019")
    assert not transfers
    library.libusb_claim_interface.assert_not_called()
    library.libusb_close.assert_called_once()
    closed.assert_called_once_with(123)


@pytest.mark.parametrize("failure", ["timeout", "short_write", "bad_response"])
def test_transfer_failure_releases_only_claimed_interface(usb, failure):
    library, _, _, closed = usb
    transfer = library.libusb_bulk_transfer.side_effect

    def fail(handle, endpoint, data, length, count, timeout):
        result = transfer(handle, endpoint, data, length, count, timeout)
        if failure == "timeout":
            return -7
        if failure == "short_write" and endpoint == 0x02:
            count._obj.value -= 1
        if failure == "bad_response" and endpoint == 0x82:
            data[3] = b"\xff"
        return result

    library.libusb_bulk_transfer.side_effect = fail
    with pytest.raises(RuntimeError):
        setup_gamepads.initialize("/dev/bus/usb/001/019")
    assert library.libusb_release_interface.call_args.args[1] == 1
    library.libusb_close.assert_called_once()
    library.libusb_exit.assert_called_once()
    closed.assert_called_once_with(123)


def test_invalid_path_never_opens_a_device(usb):
    _, _, opened, _ = usb
    with pytest.raises(ValueError, match="USB device path"):
        setup_gamepads.initialize("/dev/input/event267")
    opened.assert_not_called()


@pytest.fixture
def installation(tmp_path, monkeypatch):
    monkeypatch.setattr(setup_gamepads, "HELPER", tmp_path / "helper")
    monkeypatch.setattr(setup_gamepads, "RULE", tmp_path / "70-telesurgery-gamepads.rules")
    devices = tmp_path / "devices"
    devices.mkdir()
    monkeypatch.setattr(setup_gamepads, "USB_DEVICES", devices)
    monkeypatch.setattr(setup_gamepads.os, "geteuid", lambda: 0)
    monkeypatch.setattr(setup_gamepads, "find_library", lambda _: "libusb.so")
    run, initialize = Mock(), Mock()
    monkeypatch.setattr(setup_gamepads.subprocess, "run", run)
    monkeypatch.setattr(setup_gamepads, "initialize", initialize)
    for name, product in [("1-3", "2069"), ("1-4", "2009")]:
        entry = devices / name
        entry.mkdir()
        for key, value in {
            "idVendor": "057e",
            "idProduct": product,
            "busnum": "1",
            "devnum": "19",
        }.items():
            (entry / key).write_text(value + "\n")
    return run, initialize


def test_installer_enables_only_matching_connected_controllers(installation):
    run, initialize = installation
    setup_gamepads.install()
    commands = [call.args[0] for call in run.call_args_list]
    assert sum(command[0] == "install" for command in commands) == 2
    assert commands[-1] == ["udevadm", "control", "--reload-rules"]
    initialize.assert_called_once_with("/dev/bus/usb/001/019")


@pytest.mark.parametrize("uid", [0, 1000])
def test_repeating_setup_skips_sudo_and_leaves_connected_device_alone(
    installation, monkeypatch, uid
):
    run, initialize = installation
    monkeypatch.setattr(setup_gamepads.os, "geteuid", lambda: uid)
    setup_gamepads.HELPER.write_bytes((ROOT / "scripts/setup_gamepads.py").read_bytes())
    setup_gamepads.RULE.write_bytes((ROOT / "scripts/udev" / setup_gamepads.RULE.name).read_bytes())
    setup_gamepads.install()
    run.assert_not_called()
    initialize.assert_not_called()


def test_changed_device_helper_requests_installation_once(installation, monkeypatch):
    run, initialize = installation
    setup_gamepads.HELPER.write_text("outdated helper")
    monkeypatch.setattr(setup_gamepads.os, "geteuid", lambda: 1000)
    setup_gamepads.install()
    run.assert_called_once_with(
        ["sudo", setup_gamepads.sys.executable, str(ROOT / "scripts/setup_gamepads.py")],
        check=True,
    )
    initialize.assert_not_called()


def test_old_bundled_installer_needs_no_privileged_update(installation, monkeypatch):
    run, initialize = installation
    monkeypatch.setattr(setup_gamepads.os, "geteuid", lambda: 1000)
    tree = ast.parse((ROOT / "scripts/setup_gamepads.py").read_text())
    tree.body = [
        node
        for node in tree.body
        if not (isinstance(node, ast.FunctionDef) and node.name == "helper_matches")
    ]
    old_installer = ast.parse('def install():\n    raise RuntimeError("old installer")').body[0]
    tree.body = [
        old_installer if isinstance(node, ast.FunctionDef) and node.name == "install" else node
        for node in tree.body
    ]
    setup_gamepads.HELPER.write_text(ast.unparse(tree))
    setup_gamepads.RULE.write_bytes((ROOT / "scripts/udev" / setup_gamepads.RULE.name).read_bytes())
    setup_gamepads.install()
    run.assert_not_called()
    initialize.assert_not_called()


@pytest.mark.parametrize(
    "before,after",
    [
        ("03 91 00 0a", "03 91 00 0b"),
        ("def initialize(device):", "def initialize(device, extra=None):"),
        ("if args.device:", "if not args.device:"),
    ],
)
def test_device_behavior_changes_still_require_installation(
    installation, monkeypatch, before, after
):
    run, initialize = installation
    monkeypatch.setattr(setup_gamepads.os, "geteuid", lambda: 1000)
    source = (ROOT / "scripts/setup_gamepads.py").read_text()
    assert before in source
    setup_gamepads.HELPER.write_text(source.replace(before, after))
    setup_gamepads.RULE.write_bytes((ROOT / "scripts/udev" / setup_gamepads.RULE.name).read_bytes())
    setup_gamepads.install()
    assert run.call_args.args[0][0] == "sudo"
    initialize.assert_not_called()


def test_missing_usb_library_is_repaired_with_current_rules(installation, monkeypatch):
    run, initialize = installation
    setup_gamepads.HELPER.write_bytes((ROOT / "scripts/setup_gamepads.py").read_bytes())
    setup_gamepads.RULE.write_bytes((ROOT / "scripts/udev" / setup_gamepads.RULE.name).read_bytes())
    monkeypatch.setattr(setup_gamepads, "find_library", lambda _: None)
    setup_gamepads.install()
    assert [call.args[0] for call in run.call_args_list] == [
        ["apt-get", "update"],
        ["apt-get", "install", "-y", "libusb-1.0-0"],
    ]
    initialize.assert_called_once_with("/dev/bus/usb/001/019")
