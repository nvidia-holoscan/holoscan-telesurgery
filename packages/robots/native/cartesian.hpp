// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <Eigen/Cholesky>
#include <Eigen/Core>

#include "jog.hpp"

namespace telesurgery {
using Twist = std::array<double, 6>;
using Jacobian = std::array<double, 42>;

inline void validate_cartesian(const Twist& command) {
  for (double value : command)
    if (!std::isfinite(value) || std::abs(value) > 1.0)
      throw std::invalid_argument("Franka Cartesian input must be finite and between -1 and 1");
}

// Measured end-effector Jacobian, expressed in base axes. No robot geometry or
// tool transform is guessed: libfranka supplies the configured end-effector.
inline Joints cartesian_velocity(const Jacobian& jacobian, const Joints& position,
                                 const Twist& command, double speed) {
  validate_cartesian(command);
  validate_speed(speed);
  validate_target(position);
  using Matrix = Eigen::Matrix<double, 6, 7>;
  const Eigen::Map<const Matrix> j(jacobian.data());
  if (!j.allFinite()) throw std::runtime_error("Invalid Franka tool Jacobian");
  Eigen::Matrix<double, 6, 1> twist = Eigen::Map<const Eigen::Matrix<double, 6, 1>>(command.data());
  twist.head<3>() *= 0.10 / std::max(1.0, twist.head<3>().norm());
  twist.tail<3>() *= (30 * M_PI / 180) / std::max(1.0, twist.tail<3>().norm());
  twist *= speed / (20 * M_PI / 180);
  const Eigen::Matrix<double, 6, 6> system =
      j * j.transpose() + 0.03 * 0.03 * Eigen::Matrix<double, 6, 6>::Identity();
  Eigen::Matrix<double, 7, 1> velocity = j.transpose() * system.ldlt().solve(twist);
  if (!velocity.allFinite()) throw std::runtime_error("Invalid Franka Cartesian solution");
  velocity *= std::min(1.0, speed / std::max(1e-9, velocity.cwiseAbs().maxCoeff()));
  double scale = 1.0;
  // Slow the whole tool near any approaching joint limit, preserving direction.
  // Reserve room for the jerk-limited braking ramp, rather than clipping positions.
  for (size_t i = 0; i < position.size(); ++i) {
    if (std::abs(velocity[i]) < 1e-9) continue;
    const double room =
        velocity[i] > 0 ? joint_upper[i] - position[i] : position[i] - joint_lower[i];
    scale = std::min(scale, std::clamp((room - 0.02) / 0.15, 0.0, 1.0));
  }
  Joints result{};
  for (size_t i = 0; i < result.size(); ++i) result[i] = velocity[i] * scale;
  return result;
}

class CartesianMotion {
 public:
  CartesianMotion(const Joints& position, const Joints& velocity, const Joints& acceleration,
                  double speed)
      : speed_(speed) {
    validate_target(position);
    validate_speed(speed);
    input_.control_interface = ruckig::ControlInterface::Velocity;
    input_.synchronization = ruckig::Synchronization::Phase;
    input_.current_position = position;
    input_.current_velocity = velocity;
    input_.current_acceleration = acceleration;
    input_.target_velocity.fill(0);
    input_.target_acceleration.fill(0);
    input_.max_velocity.fill(speed);
    input_.max_acceleration.fill(1.0);
    input_.max_jerk.fill(10.0);
  }

  const Joints& advance(const Jacobian& jacobian, const Joints& measured, const Twist& command,
                        bool stopping, double period) {
    braking_ = braking_ || stopping;
    if (!braking_) {
      for (size_t i = 0; i < measured.size(); ++i)
        if (!std::isfinite(measured[i]) ||
            std::abs(input_.current_position[i] - measured[i]) > 5 * M_PI / 180)
          throw std::runtime_error("Franka tool motion tracking error");
    }
    input_.target_velocity =
        braking_ ? Joints{} : cartesian_velocity(jacobian, measured, command, speed_);
    generator_.delta_time = period;
    const auto result = generator_.update(input_, output);
    if (result < ruckig::Result::Working)
      throw std::runtime_error("Franka Cartesian trajectory calculation failed");
    finished = braking_ && result == ruckig::Result::Finished;
    output.pass_to_input(input_);
    validate_target(output.new_position);
    return output.new_position;
  }

  ruckig::OutputParameter<7> output;
  bool finished{false};

 private:
  ruckig::Ruckig<7> generator_{0.001};
  ruckig::InputParameter<7> input_;
  double speed_;
  bool braking_{false};
};
}  // namespace telesurgery
