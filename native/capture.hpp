// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES.
// SPDX-License-Identifier: Apache-2.0
#pragma once

#include <cstdint>
#include <holoscan/core/domain/tensor.hpp>
#include <memory>
#include <optional>
#include <string>

namespace telesurgery {

/// Carry an owned Bayer16 tensor, receive metadata and application buffer handoff time.
struct CaptureFrame {
  holoscan::Tensor tensor;
  std::uint64_t host_received_ns{};
  std::uint64_t buffer_ready_ns{};
};

/// Own the SDK 5 receiver graph and its IMX274 hardware for one camera session.
class Capture {
 public:
  Capture(const std::string& address, int mode, int expander, int gpu, bool reset);
  ~Capture();
  Capture(const Capture&) = delete;
  Capture& operator=(const Capture&) = delete;
  /// Return the newest frame once; no pending frame means an empty optional.
  std::optional<CaptureFrame> read();
  /// Stop and join the receiver before releasing hardware and CUDA ownership.
  void close();
  /// Return the sensor Bayer arrangement used by GPU demosaic.
  int bayer_format() const;

 private:
  struct Impl;
  std::unique_ptr<Impl> impl_;
};
}  // namespace telesurgery
