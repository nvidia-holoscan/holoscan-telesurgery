// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES.
// SPDX-License-Identifier: Apache-2.0
#pragma once

#include <hololink/operators/linux_receiver/linux_receiver_op.hpp>
#include <hsb_ip_2510_data_channel.hpp>
#include <hsb_ip_2510_linux_receiver.hpp>

namespace telesurgery {

// Reuse the pinned vendor compatibility implementation: pre-2602 firmware has
// a different register map, and pre-2603 firmware has an 8-bit page index.
inline bool is_legacy_hsb_lite(const hololink::Metadata& metadata) {
  const auto version = metadata.get<int64_t>("hsb_ip_version").value_or(0);
  return metadata.get<std::string>("fpga_uuid").value_or("") ==
             "889b7ce3-65a5-4247-8b05-4ff1904c3359" &&
         version >= 0x2510 && version < 0x2603;
}

inline std::shared_ptr<hololink::operators::LinuxReceiver> make_legacy_linux_receiver(
    CUdeviceptr buffer, size_t buffer_size, size_t page_size, unsigned pages, int socket,
    uint64_t received_offset, unsigned queue_size) {
  return std::make_shared<hololink::module::module_core::HsbIp2510LinuxReceiver>(
      buffer, buffer_size, page_size, pages, socket, received_offset, queue_size);
}
}  // namespace telesurgery
