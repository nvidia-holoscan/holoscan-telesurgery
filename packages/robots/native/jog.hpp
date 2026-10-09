// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <algorithm>
#include <array>
#include <cmath>
#include <ruckig/ruckig.hpp>
#include <stdexcept>

namespace telesurgery {
using Joints = std::array<double, 7>;
constexpr double default_speed = 10.0 * M_PI / 180;
constexpr Joints joint_lower{-2.8973, -1.7628, -2.8973, -3.0718, -2.8973, -0.0175, -2.8973};
constexpr Joints joint_upper{2.8973, 1.7628, 2.8973, -0.0698, 2.8973, 3.7525, 2.8973};

inline void validate_target(const Joints& goal) {
  for (size_t i = 0; i < goal.size(); ++i) {
    if (!std::isfinite(goal[i]) || goal[i] < joint_lower[i] || goal[i] > joint_upper[i])
      throw std::invalid_argument("Franka target is outside Panda joint limits");
  }
}

inline void validate_speed(double speed) {
  if (!std::isfinite(speed) || speed < 0.0034906585 || speed > 0.3490658504)
    throw std::invalid_argument("Franka speed must be between 0.2 and 20 degrees/s");
}

inline void validate_delta(const Joints& delta) {
  for (double value : delta) {
    if (!std::isfinite(value) || std::abs(value) > 0.087266463)
      throw std::invalid_argument("Franka jog must be finite and no larger than 5 degrees");
  }
}

inline Joints target(const Joints& measured, const Joints& delta) {
  Joints result{};
  for (size_t i = 0; i < result.size(); ++i) result[i] = measured[i] + delta[i];
  return result;
}

inline bool reached(const Joints& goal, const Joints& measured, double tolerance = 0.000174533) {
  for (size_t i = 0; i < goal.size(); ++i) {
    if (std::abs(goal[i] - measured[i]) > tolerance) return false;
  }
  return true;
}

// A local, synchronized position trajectory. Ruckig carries velocity and
// acceleration through target changes and computes a separate braking trajectory.
class JointMotion {
 public:
  JointMotion(const Joints& position, const Joints& velocity, const Joints& acceleration,
              const Joints& goal, double speed) {
    validate_target(goal);
    validate_speed(speed);
    input_.current_position = position;
    input_.current_velocity = velocity;
    input_.current_acceleration = acceleration;
    input_.target_position = goal;
    input_.target_velocity.fill(0.0);
    input_.target_acceleration.fill(0.0);
    input_.max_velocity.fill(speed);
    input_.max_acceleration.fill(0.2);
    input_.max_jerk.fill(2.0);
    input_.synchronization = ruckig::Synchronization::Time;
    check(generator_.calculate(input_, output.trajectory));
  }

  const Joints& advance(const Joints& goal, bool stopping, double period) {
    if (stopping) {
      braking_ = true;
      input_.control_interface = ruckig::ControlInterface::Velocity;
      input_.synchronization = ruckig::Synchronization::None;
    }
    if (!braking_) input_.target_position = goal;
    generator_.delta_time = period;
    const auto result = generator_.update(input_, output);
    check(result);
    finished = result == ruckig::Result::Finished;
    output.pass_to_input(input_);
    validate_target(output.new_position);
    return output.new_position;
  }

  double duration() const { return output.trajectory.get_duration(); }
  ruckig::OutputParameter<7> output;
  bool finished{false};

 private:
  static void check(ruckig::Result result) {
    if (result < ruckig::Result::Working)
      throw std::runtime_error("Franka trajectory calculation failed: " +
                               std::to_string(static_cast<int>(result)));
  }
  ruckig::Ruckig<7> generator_{0.001};
  ruckig::InputParameter<7> input_;
  bool braking_{false};
};
}  // namespace telesurgery
