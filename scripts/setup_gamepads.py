#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Install automatic USB startup for Nintendo Switch 2 Pro controllers."""

import argparse
import ctypes as c
import os
import re
import subprocess
import sys
from ctypes.util import find_library
from pathlib import Path

HELPER = Path("/usr/local/libexec/telesurgery-gamepads")
RULE = Path("/etc/udev/rules.d/70-telesurgery-gamepads.rules")
USB_DEVICES = Path("/sys/bus/usb/devices")
# Report 0x09 is the standard HID report described by this controller. Unlike
# the extended 0x05 report, Linux can expose it to both joydev and browsers.
# Protocol: github.com/ndeadly/switch2_controller_research/blob/master/commands.md
COMMANDS = (
    bytes.fromhex("03 91 00 0a 00 04 00 00 09 00 00 00"),
    bytes.fromhex("03 91 00 0d 00 08 00 00 01 00 ff ff ff ff ff ff"),
)


class Descriptor(c.Structure):
    _fields_ = [
        ("length", c.c_uint8),
        ("type", c.c_uint8),
        ("usb", c.c_uint16),
        ("device_class", c.c_uint8),
        ("subclass", c.c_uint8),
        ("protocol", c.c_uint8),
        ("packet_size", c.c_uint8),
        ("vendor", c.c_uint16),
        ("product", c.c_uint16),
        ("version", c.c_uint16),
        ("manufacturer", c.c_uint8),
        ("name", c.c_uint8),
        ("serial", c.c_uint8),
        ("configurations", c.c_uint8),
    ]


def initialize(device):
    """Enable HID reports using only the vendor interface; leave HID attached."""
    if not re.fullmatch(r"/dev/bus/usb/\d{3}/\d{3}", str(device)):
        raise ValueError("Expected a USB device path")
    library = find_library("usb-1.0")
    if not library:
        raise RuntimeError("Install libusb-1.0-0")
    usb = c.CDLL(library)
    signatures = {
        "libusb_init": ([c.POINTER(c.c_void_p)], c.c_int),
        "libusb_exit": ([c.c_void_p], None),
        "libusb_wrap_sys_device": ([c.c_void_p, c.c_ssize_t, c.POINTER(c.c_void_p)], c.c_int),
        "libusb_get_device": ([c.c_void_p], c.c_void_p),
        "libusb_get_device_descriptor": ([c.c_void_p, c.POINTER(Descriptor)], c.c_int),
        "libusb_claim_interface": ([c.c_void_p, c.c_int], c.c_int),
        "libusb_release_interface": ([c.c_void_p, c.c_int], c.c_int),
        "libusb_close": ([c.c_void_p], None),
        "libusb_bulk_transfer": (
            [c.c_void_p, c.c_uint8, c.c_void_p, c.c_int, c.POINTER(c.c_int), c.c_uint],
            c.c_int,
        ),
    }
    for name, (args, result) in signatures.items():
        function = getattr(usb, name)
        function.argtypes, function.restype = args, result

    def check(result):
        if result < 0:
            raise RuntimeError(f"Nintendo USB initialization failed (libusb {result})")

    context, handle = c.c_void_p(), c.c_void_p()
    claimed = False
    fd = os.open(device, os.O_RDWR | os.O_NOFOLLOW)
    try:
        check(usb.libusb_init(c.byref(context)))
        check(usb.libusb_wrap_sys_device(context, fd, c.byref(handle)))
        descriptor = Descriptor()
        check(usb.libusb_get_device_descriptor(usb.libusb_get_device(handle), c.byref(descriptor)))
        if (descriptor.vendor, descriptor.product) != (0x057E, 0x2069):
            raise ValueError("This initializer only supports the Switch 2 Pro controller")
        # Interface 1 has bulk endpoints 0x02/0x82. Do not reset the device or
        # detach interface 0: the kernel owns its normal gamepad input stream.
        check(usb.libusb_claim_interface(handle, 1))
        claimed = True
        for command in COMMANDS:
            transferred = c.c_int()
            payload = c.create_string_buffer(command)
            check(
                usb.libusb_bulk_transfer(
                    handle, 0x02, payload, len(command), c.byref(transferred), 500
                )
            )
            if transferred.value != len(command):
                raise RuntimeError("Incomplete Nintendo USB command")
            response = c.create_string_buffer(64)
            check(usb.libusb_bulk_transfer(handle, 0x82, response, 64, c.byref(transferred), 500))
            if (
                transferred.value < 4
                or response.raw[0] != command[0]
                or response.raw[3] != command[3]
            ):
                raise RuntimeError("Unexpected Nintendo USB response")
    finally:
        if claimed:
            usb.libusb_release_interface(handle, 1)
        if handle:
            usb.libusb_close(handle)
        if context:
            usb.libusb_exit(context)
        os.close(fd)


def connected_devices():
    for entry in USB_DEVICES.iterdir():
        vendor, product = entry / "idVendor", entry / "idProduct"
        if not vendor.exists() or not product.exists():
            continue
        if (vendor.read_text().strip(), product.read_text().strip()) != ("057e", "2069"):
            continue
        bus, address = int((entry / "busnum").read_text()), int((entry / "devnum").read_text())
        yield f"/dev/bus/usb/{bus:03d}/{address:03d}"


def helper_matches(source, target):
    """Compare the installed --device helper, ignoring its bundled installer.

    Older installs contain this whole script. Changes to setup's own checks
    must not require replacing an otherwise identical root-owned USB helper.
    Parse the installed file without importing or executing it.
    """
    import ast

    def device_code(path):
        tree = ast.parse(path.read_text())
        tree.body = [
            node
            for node in tree.body
            if not (
                isinstance(node, ast.FunctionDef)
                and node.name in {"install", "connected_devices", "helper_matches"}
            )
        ]
        return ast.dump(tree)

    try:
        return device_code(source) == device_code(target)
    except (OSError, SyntaxError, UnicodeError):
        return False


def install():
    source = Path(__file__).resolve()
    rule = source.parent / "udev" / RULE.name
    helper_current = helper_matches(source, HELPER)
    rule_current = RULE.exists() and RULE.read_bytes() == rule.read_bytes()
    usb_available = bool(find_library("usb-1.0"))
    if helper_current and rule_current and usb_available:
        print("Automatic Nintendo USB startup is configured.")
        return
    if os.geteuid() != 0:
        changes = [
            str(path)
            for path, current in ((HELPER, helper_current), (RULE, rule_current))
            if not current
        ]
        if not usb_available:
            changes.append("libusb-1.0-0")
        print("Gamepad setup needs sudo to install/update: " + ", ".join(changes), flush=True)
        subprocess.run(["sudo", sys.executable, str(source)], check=True)
        return
    if not usb_available:
        subprocess.run(["apt-get", "update"], check=True)
        subprocess.run(["apt-get", "install", "-y", "libusb-1.0-0"], check=True)
    if not helper_current:
        subprocess.run(["install", "-D", "-m", "644", str(source), str(HELPER)], check=True)
    if not rule_current:
        subprocess.run(["install", "-D", "-m", "644", str(rule), str(RULE)], check=True)
        subprocess.run(["udevadm", "control", "--reload-rules"], check=True)
    # Initialize controllers already connected during installation. On later
    # setup runs, leave active devices alone; udev handles each new connection.
    for device in connected_devices():
        initialize(device)
    print("Nintendo controllers will initialize automatically when connected.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", help="Initialize one USB device (used by udev)")
    args = parser.parse_args()
    if args.device:
        initialize(args.device)
    else:
        install()


if __name__ == "__main__":
    main()
