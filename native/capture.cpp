// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES.
// SPDX-License-Identifier: Apache-2.0
#include "capture.hpp"

#include <cuda.h>
#include <time.h>

#include <capture_metadata_traits.hpp>
#include <hololink/core/data_channel.hpp>
#include <hololink/core/enumerator.hpp>
#include <hololink/core/hololink.hpp>
#include <hololink/operators/capture_metadata_utils.hpp>
#include <hololink/operators/csi_to_bayer/csi_to_bayer.hpp>
#include <hololink/operators/image_processor/image_processor.hpp>
#include <hololink/operators/linux_receiver/linux_receiver_op.hpp>
#include <hololink/sensors/camera/imx274/native_imx274_sensor.hpp>
#include <holoscan/core/compile.hpp>
#include <holoscan/core/connection_options.hpp>
#include <holoscan/core/execution_context.hpp>
#include <holoscan/core/graph.hpp>
#include <holoscan/core/operator.hpp>
#include <holoscan/core/operator_spec.hpp>
#include <holoscan/core/port.hpp>
#include <holoscan/core/run.hpp>
#include <holoscan/core/run_session.hpp>
#include <holoscan/core/temporal_contract.hpp>
#include <holoscan/time/realtime_clock.hpp>
#include <mutex>
#include <stdexcept>
#include <utility>

#include "legacy_hsb.hpp"

namespace telesurgery {
namespace {
void check_cuda(CUresult result) {
  if (result != CUDA_SUCCESS) {
    const char* message = nullptr;
    cuGetErrorString(result, &message);
    throw std::runtime_error(message ? message : "CUDA driver failure");
  }
}

struct Mailbox {
  std::mutex mutex;
  std::optional<CaptureFrame> frame;
};

class CaptureSink : public holoscan::Operator<> {
 public:
  explicit CaptureSink(std::shared_ptr<Mailbox> mailbox) : mailbox_(std::move(mailbox)) {}
  holoscan::Input<holoscan::Tensor> tensor{"tensor"};
  holoscan::Input<hololink::CaptureMetadataT> metadata{"metadata"};

  void setup(holoscan::OperatorSpec& spec) override {
    spec.input(tensor, "tensor")
        .expects_tensor(holoscan::TensorInputSpec{
            .representation = {.memory_kind = holoscan::MemoryKind::kCudaDevice}})
        .queue_depth(2U)
        .accepts_projected_tensor();
    spec.input(metadata, "metadata").queue_depth(2U);
  }

  holoscan::Contract contract() const override {
    holoscan::Contract result;
    result
        .trigger(holoscan::OnAligned{.ports = holoscan::ports(tensor, metadata),
                                     .window = hololink::operators::kMetadataPairingWindow})
        .input(tensor, holoscan::Exact{})
        .input(metadata, holoscan::Exact{});
    return result;
  }

  holoscan::expected<void, holoscan::Error> compute(holoscan::ExecutionContext& context) override {
    auto pair = hololink::operators::receive_paired_tensor_metadata(tensor, metadata);
    if (!pair) return holoscan::make_unexpected(std::move(pair).error());
    timespec buffer_ready{};
    clock_gettime(CLOCK_MONOTONIC, &buffer_ready);
    // A receive lease ends on callback return. An owning device copy allows Python
    // to consume asynchronously without retaining a finite SDK pool lease.
    // Runtime-pool tensors require an explicit consumer stream for readiness.
    auto owned = pair->tensor.data.copy(context.cuda_stream().get());
    if (!owned) return holoscan::make_unexpected(std::move(owned).error());
    auto ready = owned->synchronize_for_host();
    if (!ready) return ready;
    const auto& data = pair->metadata.data;
    CaptureFrame frame{
        std::move(*owned),
        static_cast<std::uint64_t>(data.received_s) * 1000000000ULL + data.received_ns,
        static_cast<std::uint64_t>(buffer_ready.tv_sec) * 1000000000ULL + buffer_ready.tv_nsec};
    std::lock_guard lock(mailbox_->mutex);
    mailbox_->frame = std::move(frame);
    return {};
  }

 private:
  std::shared_ptr<Mailbox> mailbox_;
};
}  // namespace

struct Capture::Impl {
  CUdevice device{};
  CUcontext context{};
  std::shared_ptr<hololink::DataChannel> channel;
  std::shared_ptr<hololink::sensors::NativeImx274Sensor> camera;
  std::shared_ptr<Mailbox> mailbox = std::make_shared<Mailbox>();
  std::optional<holoscan::RunSession> session;
  bool link_started = false;

  ~Impl() {
    try {
      close();
    } catch (...) { /* Destructors cannot propagate hardware errors. */
    }
  }
  void close() {
    if (session) {
      session->request_stop();
      session->wait();
      session.reset();
    }
    {
      std::lock_guard lock(mailbox->mutex);
      mailbox->frame.reset();
    }
    if (link_started) {
      channel->hololink()->stop();
      link_started = false;
    }
    camera.reset();
    channel.reset();
    if (context) {
      check_cuda(cuDevicePrimaryCtxRelease(device));
      context = nullptr;
    }
  }
};

Capture::Capture(const std::string& address, int mode, int expander, int gpu, bool reset)
    : impl_(std::make_unique<Impl>()) {
  auto& p = *impl_;
  check_cuda(cuInit(0));
  check_cuda(cuDeviceGet(&p.device, gpu));
  check_cuda(cuDevicePrimaryCtxRetain(&p.context, p.device));
  check_cuda(cuCtxSetCurrent(p.context));
  const auto metadata = hololink::Enumerator::find_channel(address);
  const bool legacy = is_legacy_hsb_lite(metadata);
  if (legacy && metadata.get<int64_t>("hsb_ip_version").value() < 0x2602) {
    p.channel = std::make_shared<hololink::module::module_core::HsbIp2510DataChannel>(metadata);
  } else {
    p.channel = std::make_shared<hololink::DataChannel>(metadata);
  }
  p.camera = std::make_shared<hololink::sensors::NativeImx274Sensor>(*p.channel, expander);
  const auto camera_mode = static_cast<hololink::sensors::imx274_mode::Mode>(mode);
  p.camera->set_mode(camera_mode);
  hololink::operators::CsiToBayerParams csi_params{.cuda_device_ordinal = gpu};
  p.camera->configure_converter(csi_params.geometry);
  csi_params.bayer_format = p.camera->get_bayer_format();
  const auto& geometry = csi_params.geometry;
  const auto frame_size = geometry.start_byte + geometry.bytes_per_line * geometry.pixel_height +
                          geometry.trailing_bytes;
  holoscan::Graph graph{"imx274_capture"};
  auto unpack = graph.op<hololink::operators::CsiToBayerOp>("unpack");
  unpack.set_params(csi_params);
  auto process = graph.op<hololink::operators::ImageProcessorOp>("process");
  process.set_params({.pixel_format = int(p.camera->get_pixel_format()),
                      .bayer_format = int(p.camera->get_bayer_format()),
                      .optical_black = 50,
                      .cuda_device_ordinal = gpu});
  auto sink = graph.op<CaptureSink>("sink", p.mailbox);
  const auto start = [camera = p.camera] { camera->start(); };
  const auto stop = [camera = p.camera] { camera->stop(); };
  auto rx = graph.op<hololink::operators::LinuxReceiverOp>("rx", p.channel, start, stop);
  rx.set_params({.frame_context = p.context,
                 .frame_size = frame_size,
                 .receiver_factory = legacy ? make_legacy_linux_receiver : nullptr});
  graph.add_flow(rx->tensor, unpack->input_tensor, {.queue_depth = 2U});
  graph.add_flow(rx->metadata, unpack->input_metadata, {.queue_depth = 2U});
  graph.add_flow(unpack->output_tensor, process->input_tensor, {.queue_depth = 2U});
  graph.add_flow(unpack->output_metadata, process->input_metadata, {.queue_depth = 2U});
  graph.add_flow(process->output_tensor, sink->tensor, {.queue_depth = 2U});
  graph.add_flow(process->output_metadata, sink->metadata, {.queue_depth = 2U});
  graph.set_default_clock(graph.add_clock<holoscan::RealtimeClock>("clock"));
  holoscan::CompileOptions options;
  for (const auto* name : {"rx", "unpack", "process"}) {
    options.deployment.bind_tensor_output_device(
        {.operator_path = name, .output_port = "tensor", .device = holoscan::DeviceId{gpu}});
  }
  auto plan = holoscan::compile(graph, std::move(options));
  if (!plan.ok()) {
    std::string message = "IMX274 graph compilation failed";
    for (const auto& error : plan.diagnostics()) message += ": " + std::string(error.token);
    throw std::runtime_error(message);
  }
  p.channel->hololink()->start();
  p.link_started = true;
  if (reset) p.channel->hololink()->reset();
  p.camera->setup_clock();
  p.camera->configure(camera_mode);
  p.camera->set_digital_gain_reg(4);
  p.session.emplace(holoscan::run_async(plan));
}

Capture::~Capture() = default;
void Capture::close() { impl_->close(); }
int Capture::bayer_format() const { return int(impl_->camera->get_bayer_format()); }
std::optional<CaptureFrame> Capture::read() {
  if (!impl_->session) throw std::runtime_error("camera is closed");
  if (impl_->session->termination() == holoscan::RunTermination::kFailed) {
    throw std::runtime_error("HSB receiver graph failed; inspect Holoscan diagnostics");
  }
  std::lock_guard lock(impl_->mailbox->mutex);
  return std::exchange(impl_->mailbox->frame, std::nullopt);
}
}  // namespace telesurgery
