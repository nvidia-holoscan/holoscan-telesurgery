// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES.
// SPDX-License-Identifier: Apache-2.0
#include <nanobind/nanobind.h>
#include <nanobind/stl/optional.h>
#include <nanobind/stl/string.h>
#include <nanobind/stl/vector.h>

#include <hololink/core/enumerator.hpp>
#include <set>

#include "capture.hpp"

namespace nb = nanobind;
NB_MODULE(_hsb, module) {
  nb::module_::import_("holoscan");
  module.def(
      "discover",
      [] {
        std::set<std::string> addresses;
        hololink::Enumerator::enumerated(
            [&](hololink::Metadata& metadata) {
              if (auto ip = metadata.get<std::string>("peer_ip")) addresses.insert(*ip);
              return true;
            },
            std::make_shared<hololink::Timeout>(0.5F));
        return std::vector<std::string>(addresses.begin(), addresses.end());
      },
      nb::call_guard<nb::gil_scoped_release>());
  nb::class_<telesurgery::CaptureFrame>(module, "CaptureFrame")
      .def_ro("tensor", &telesurgery::CaptureFrame::tensor)
      .def_ro("host_received_ns", &telesurgery::CaptureFrame::host_received_ns)
      .def_ro("buffer_ready_ns", &telesurgery::CaptureFrame::buffer_ready_ns);
  nb::class_<telesurgery::Capture>(module, "Capture")
      .def(nb::init<const std::string&, int, int, int, bool>(), nb::arg("address"), nb::arg("mode"),
           nb::arg("expander"), nb::arg("gpu"), nb::arg("reset"),
           nb::call_guard<nb::gil_scoped_release>())
      .def("read", &telesurgery::Capture::read, nb::call_guard<nb::gil_scoped_release>())
      .def("close", &telesurgery::Capture::close, nb::call_guard<nb::gil_scoped_release>())
      .def_prop_ro("bayer_format", &telesurgery::Capture::bayer_format);
}
