// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <franka/model.h>
#include <franka/robot.h>
#include <nanobind/nanobind.h>
#include <nanobind/stl/array.h>
#include <nanobind/stl/pair.h>
#include <nanobind/stl/string.h>

#include <atomic>
#include <chrono>
#include <iomanip>
#include <memory>
#include <mutex>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <thread>
#include <utility>

#include "cartesian.hpp"
#include "jog.hpp"

namespace nb = nanobind;
using Clock = std::chrono::steady_clock;

// Python/Holoscan owns admission and supplies bounded targets. Only this native
// worker owns the 1 kHz FCI loop; it never calls Python or waits for a mailbox lock.
class Controller {
 public:
  explicit Controller(const std::string& address)
      : robot_(std::make_unique<franka::Robot>(address)) {
    state_ = robot_->readOnce();
    // Load during connection, never after accepting a time-sensitive jog.
    model_ = std::make_unique<franka::Model>(robot_->loadModel());
    observed_ = Clock::now();
  }
  ~Controller() { hold(); }

  franka::RobotState read() {
    if (!robot_) throw std::runtime_error("Franka controller is disconnected");
    if (!running_) {
      reap();
      state_ = robot_->readOnce();
      observed_ = Clock::now();
    }
    std::lock_guard lock(mutex_);
    if (Clock::now() - observed_ > std::chrono::milliseconds(100)) {
      stopped_ = true;
      throw std::runtime_error("Franka control feedback is stale");
    }
    return state_;
  }

  void jog(const std::array<double, 7>& delta, bool step = false,
           double speed = telesurgery::default_speed) {
    telesurgery::validate_delta(delta);
    telesurgery::validate_speed(speed);
    if (needs_release_) {
      throw std::runtime_error("Franka input timed out; release input before retrying");
    }
    if (!running_) {
      const auto state = read();
      const auto goal = telesurgery::target(state.q, delta);
      start(state, goal, step, false, speed);
    } else {
      std::unique_lock lock(mutex_);
      if (homing_) throw std::runtime_error("Stop Franka Home before manual control");
      if (cartesian_) throw std::runtime_error("Stop tool motion before joint control");
      // Finish libfranka's handoff before starting another motion. Do not lose
      // a fresh tap that arrives as the previous trajectory completes.
      if (finishing_) {
        lock.unlock();
        reap();
        jog(delta, step, speed);
        return;
      }
      if (stopped_) throw std::runtime_error("Franka is stopping; release input before retrying");
      if (speed != speed_) throw std::runtime_error("Release input before changing Franka speed");
      const auto goal = telesurgery::target(step ? command_ : state_.q, delta);
      telesurgery::validate_target(goal);
      command_ = goal;
      step_ = step;  // Update the active trajectory; never wait for the previous target.
      speed_ = speed;
      updated_ = Clock::now();
    }
  }

  void jog_cartesian(const telesurgery::Twist& command, double speed = telesurgery::default_speed) {
    telesurgery::validate_cartesian(command);
    telesurgery::validate_speed(speed);
    if (needs_release_)
      throw std::runtime_error("Franka input timed out; release input before retrying");
    if (!running_) {
      const auto state = read();
      start(state, state.q_d, false, false, speed, command);
    } else {
      std::lock_guard lock(mutex_);
      if (!cartesian_) throw std::runtime_error("Stop joint motion before tool control");
      if (stopped_) throw std::runtime_error("Franka is stopping; release input before retrying");
      if (speed != speed_) throw std::runtime_error("Release input before changing Franka speed");
      twist_ = command;
      updated_ = Clock::now();
    }
  }

  void home(const telesurgery::Joints& goal, double speed = telesurgery::default_speed) {
    telesurgery::validate_speed(speed);
    if (running_) throw std::runtime_error("Stop the current Franka motion before Home");
    if (needs_release_) throw std::runtime_error("Release control before Home");
    const auto state = read();
    start(state, goal, true, true, speed);
  }

  void hold() {
    stopped_ = true;
    if (worker_.joinable()) worker_.join();
    needs_release_ = false;
  }

  bool active() const { return running_; }
  bool homing() const { return running_ && homing_; }
  bool stopping() const { return running_ && stopped_; }

  // Pure model evaluation; never reads or commands the robot. Tool frames come
  // from the same measured snapshot as the reference joints.
  auto kinematics(const telesurgery::Joints& q, const std::array<double, 16>& flange,
                  const std::array<double, 16>& tool) const {
    telesurgery::validate_target(q);
    return std::make_pair(model_->pose(franka::Frame::kEndEffector, q, flange, tool),
                          model_->zeroJacobian(franka::Frame::kEndEffector, q, flange, tool));
  }

  void close() {
    hold();
    robot_.reset();  // Release FCI even if a Python traceback retains this controller.
  }

 private:
  void start(const franka::RobotState& state, const telesurgery::Joints& goal, bool step, bool home,
             double speed, std::optional<telesurgery::Twist> twist = std::nullopt) {
    if (state.robot_mode != franka::RobotMode::kIdle || state.current_errors) {
      throw std::runtime_error("Franka is not idle (mode " +
                               std::to_string(static_cast<int>(state.robot_mode)) + ", faults " +
                               static_cast<std::string>(state.current_errors) +
                               "); wait for motion to finish or check Desk");
    }
    telesurgery::validate_target(goal);
    step_ = step;
    homing_ = home;
    cartesian_ = twist.has_value();
    finishing_ = false;
    stopped_ = false;
    {
      std::lock_guard lock(mutex_);
      command_ = goal;
      twist_ = twist.value_or(telesurgery::Twist{});
      speed_ = speed;
      updated_ = Clock::now();
    }
    running_ = true;
    try {
      worker_ = std::thread([this] { control(); });
    } catch (...) {
      running_ = false;
      throw;
    }
  }

  void reap() {
    if (worker_.joinable()) worker_.join();
    if (!error_.empty()) throw std::runtime_error(std::exchange(error_, {}));
  }

  void control() noexcept {
    try {
      telesurgery::Joints goal, measured{};
      Clock::time_point updated;
      double speed;
      bool step, timed_out = false;
      std::optional<telesurgery::JointMotion> motion;
      std::optional<telesurgery::CartesianMotion> tool_motion;
      telesurgery::Twist twist{};
      std::chrono::duration<double> deadline{0.2};
      {
        std::lock_guard lock(mutex_);
        goal = command_;
        updated = updated_;
        speed = speed_;
        step = step_;
        twist = twist_;
      }
      robot_->control(
          [&](const franka::RobotState& state, franka::Duration period) -> franka::JointPositions {
            measured = state.q;
            {
              std::unique_lock lock(mutex_, std::try_to_lock);
              if (lock.owns_lock()) {
                state_ = state;
                observed_ = Clock::now();
                goal = command_;
                updated = updated_;
                step = step_;
                twist = twist_;
              }
            }
            if (!motion && !tool_motion) {
              // Start from the last desired state to avoid a command discontinuity.
              if (cartesian_) {
                tool_motion.emplace(state.q_d, state.dq_d, state.ddq_d, speed);
              } else {
                motion.emplace(state.q_d, state.dq_d, state.ddq_d, goal, speed);
                if (step) deadline = std::chrono::duration<double>(motion->duration() + 5.0);
              }
              return state.q_d;
            }
            if (!step) deadline = std::chrono::duration<double>(0.2);
            if (!stopped_ && Clock::now() - updated > deadline) {
              stopped_ = true;
              needs_release_ = true;
              timed_out = true;
            }
            if (tool_motion) {
              const auto jacobian = model_->zeroJacobian(franka::Frame::kEndEffector, state);
              franka::JointPositions output(
                  tool_motion->advance(jacobian, state.q, twist, stopped_, period.toSec()));
              if (tool_motion->finished) return franka::MotionFinished(output);
              return output;
            }
            const auto& position = motion->advance(goal, stopped_, period.toSec());
            if (step) deadline = std::chrono::duration<double>(motion->duration() + 5.0);
            franka::JointPositions output(position);
            // Planning completion and measured arrival are separate. Hold the
            // final reference briefly for tracking; never chase encoder noise.
            const double tolerance = (homing_ ? 0.05 : 0.01) * M_PI / 180;
            if (motion->finished) {
              if (stopped_) return franka::MotionFinished(output);
              if (step && telesurgery::reached(goal, state.q, tolerance)) {
                std::unique_lock lock(mutex_, std::try_to_lock);
                // A fresh held-key command wins over an old step completion.
                if (lock.owns_lock() && step_ && updated_ == updated) {
                  finishing_ = true;
                  return franka::MotionFinished(output);
                }
              }
            }
            return output;
          },
          franka::ControllerMode::kJointImpedance, true);
      if (step && timed_out) {
        size_t joint = 0;
        for (size_t i = 1; i < goal.size(); ++i)
          if (std::abs(goal[i] - measured[i]) > std::abs(goal[joint] - measured[joint])) joint = i;
        std::ostringstream message;
        message << "Franka " << (homing_ ? "Home" : "step") << " stopped after " << std::fixed
                << std::setprecision(1) << deadline.count() << " s: J" << joint + 1 << " remained "
                << std::setprecision(2) << std::abs(goal[joint] - measured[joint]) * 180 / M_PI
                << " degrees from target";
        throw std::runtime_error(message.str());
      }
    } catch (const std::exception& error) {
      error_ = error.what();
    } catch (...) {
      error_ = "Franka control failed";
    }
    stopped_ = true;
    running_ = false;
  }

  std::unique_ptr<franka::Robot> robot_;
  std::unique_ptr<franka::Model> model_;
  franka::RobotState state_{};
  std::mutex mutex_;
  std::array<double, 7> command_{};
  telesurgery::Twist twist_{};
  Clock::time_point updated_, observed_;
  std::thread worker_;
  bool step_{false};
  bool homing_{false};
  bool cartesian_{false};
  bool finishing_{false};
  double speed_{telesurgery::default_speed};
  std::atomic<bool> running_{false}, stopped_{true}, needs_release_{false};
  std::string error_;
};

NB_MODULE(_franka, m) {
  nb::class_<Controller>(m, "Controller")
      .def(nb::init<const std::string&>(), nb::call_guard<nb::gil_scoped_release>())
      .def("jog", &Controller::jog, nb::arg("delta"), nb::arg("step") = false,
           nb::arg("speed") = telesurgery::default_speed, nb::call_guard<nb::gil_scoped_release>())
      .def("jog_cartesian", &Controller::jog_cartesian, nb::arg("command"),
           nb::arg("speed") = telesurgery::default_speed, nb::call_guard<nb::gil_scoped_release>())
      .def("home", &Controller::home, nb::arg("goal"),
           nb::arg("speed") = telesurgery::default_speed, nb::call_guard<nb::gil_scoped_release>())
      .def("hold", &Controller::hold, nb::call_guard<nb::gil_scoped_release>())
      .def("close", &Controller::close, nb::call_guard<nb::gil_scoped_release>())
      .def("kinematics", &Controller::kinematics, nb::call_guard<nb::gil_scoped_release>())
      .def("read", [](Controller& controller) {
        franka::RobotState state;
        {
          nb::gil_scoped_release release;
          state = controller.read();
        }
        nb::dict result;
        result["q"] = state.q;
        result["dq"] = state.dq;
        result["tau_J"] = state.tau_J;
        result["O_T_EE"] = state.O_T_EE;
        result["F_T_EE"] = state.F_T_EE;
        result["EE_T_K"] = state.EE_T_K;
        result["device_time_ms"] = state.time.toMSec();
        result["faults"] = static_cast<std::string>(state.current_errors);
        result["control_active"] = controller.active();
        result["home_active"] = controller.homing();
        result["stopping"] = controller.stopping();
        const char* mode = "other";
        switch (state.robot_mode) {
          case franka::RobotMode::kIdle:
            mode = "idle";
            break;
          case franka::RobotMode::kMove:
            mode = "moving";
            break;
          case franka::RobotMode::kGuiding:
            mode = "guiding";
            break;
          case franka::RobotMode::kReflex:
            mode = "reflex";
            break;
          case franka::RobotMode::kUserStopped:
            mode = "user stopped";
            break;
          case franka::RobotMode::kAutomaticErrorRecovery:
            mode = "recovering";
            break;
          default:
            break;
        }
        result["mode"] = mode;
        return result;
      });
}
