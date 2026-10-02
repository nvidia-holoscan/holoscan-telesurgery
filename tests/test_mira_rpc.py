# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

import json
import threading

import pytest
from telesurgery_core.adapters.mira import delta
from telesurgery_core.adapters.sim_robot import SimRobot
from telesurgery_core.transport.rpc import RpcClient


@pytest.mark.parametrize("reject", [False, True])
def test_rpc_ids_responses_and_failure_without_retry(reject):
    pytest.importorskip("websocket")
    serve = pytest.importorskip("websockets.sync.server").serve
    observed = []

    def handle(socket):
        request = json.loads(socket.recv())
        observed.append(request)
        reply = {"jsonrpc": "2.0", "id": request["id"]}
        reply["error" if reject else "result"] = "fixture"
        socket.send(json.dumps(reply))

    with serve(handle, "127.0.0.1", 0) as server:
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        client = RpcClient(f"ws://127.0.0.1:{server.socket.getsockname()[1]}")
        try:
            request = delta([1, 0, 0, 0], [0, 0, 0, 0])
            if reject:
                with pytest.raises(RuntimeError, match="rejected"):
                    client.send(request)
            else:
                assert client.send(request) == "fixture"
        finally:
            client.close()
            server.shutdown()
            thread.join(timeout=2)
    assert len(observed) == 1
    assert observed[0]["id"] == 1


def test_sim_rpc_updates_both_arms_and_rejects_partial_bad_request():
    robot = SimRobot()
    original = {arm: list(pose) for arm, pose in robot.pose.items()}
    with pytest.raises(ValueError):
        robot.apply(
            {
                "method": "set_mira_cartesian_delta",
                "params": {"left": [1, 0, 0, 0], "right": [float("nan"), 0, 0, 0]},
            }
        )
    assert robot.pose == original
    robot.apply(
        {
            "method": "set_mira_cartesian_delta",
            "params": {"left": [1, 0, 0, 0], "right": [0, 1, 0, 0]},
        }
    )
    assert robot.pose["left"][0] == pytest.approx(original["left"][0] + 1)
    assert robot.pose["right"][1] == pytest.approx(original["right"][1] - 1)
