# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Read a bounded log tail without loading an entire build or simulator log."""

import os
import time


def read_log(path):
    text, updated = "", None
    try:
        with path.open("rb") as stream:
            info = os.fstat(stream.fileno())
            offset = max(0, info.st_size - 32768)
            stream.seek(offset)
            if offset:
                stream.readline()
            text = stream.read(32768).decode(errors="replace")
            updated = max(0, int(time.time() - info.st_mtime))
    except FileNotFoundError:
        pass
    return {
        "path": str(path),
        "text": "\n".join(text.splitlines()[-100:]),
        "updated_seconds_ago": updated,
    }
