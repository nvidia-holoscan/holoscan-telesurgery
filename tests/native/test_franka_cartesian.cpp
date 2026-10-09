// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Production Cartesian planner checks; no FCI connection or robot movement.
#include <cassert>
#include <limits>

#include "cartesian.hpp"

using namespace telesurgery;

int main() {
  Joints start{};
  for (size_t i = 0; i < 7; ++i) start[i] = (joint_lower[i] + joint_upper[i]) / 2;
  Jacobian jacobian{};
  for (size_t i = 0; i < 6; ++i) jacobian[i * 6 + i] = 1;
  for (double bad : {1.01, -1.01, std::numeric_limits<double>::quiet_NaN(),
                     std::numeric_limits<double>::infinity()}) {
    Twist command{};
    command[0] = bad;
    bool rejected = false;
    try {
      validate_cartesian(command);
    } catch (const std::invalid_argument&) {
      rejected = true;
    }
    assert(rejected);
  }
  for (double speed_deg : {0.2, 4.0, 20.0}) {
    const double speed = speed_deg * M_PI / 180;
    for (size_t axis = 0; axis < 6; ++axis) {
      for (double sign : {-1.0, 1.0}) {
        Twist command{};
        command[axis] = sign;
        const auto velocity = cartesian_velocity(jacobian, start, command, speed);
        for (size_t i = 0; i < 7; ++i) {
          assert(std::abs(velocity[i]) <= speed + 1e-9);
          assert(i == axis ? velocity[i] * sign > 0 : velocity[i] == 0);
        }
        CartesianMotion motion(start, {}, {}, speed);
        Joints previous = start, acceleration{};
        double braking = 0;
        for (int cycle = 0; cycle < 5000; ++cycle) {
          if (cycle == 1500) command[axis] *= -1;
          const bool stopping = cycle >= 4000;
          const double dt = cycle % 10 == 0 ? .002 : .001;
          motion.advance(jacobian, previous, command, stopping, dt);
          for (size_t i = 0; i < 7; ++i) {
            assert(std::abs(motion.output.new_velocity[i]) <= speed + 1e-9);
            assert(std::abs(motion.output.new_acceleration[i]) <= 1.0 + 1e-9);
            assert(std::abs(motion.output.new_acceleration[i] - acceleration[i]) <= 10 * dt + 1e-7);
            assert(std::abs(motion.output.new_position[i] - previous[i]) <= speed * dt + 1e-9);
          }
          previous = motion.output.new_position;
          acceleration = motion.output.new_acceleration;
          if (!stopping)
            assert(!motion.finished);  // Sustained input never becomes a discrete step.
          else {
            braking += dt;
            if (motion.finished) break;
          }
        }
        assert(motion.finished && braking < .6);
        assert(reached({}, motion.output.new_velocity, 1e-8));
        assert(reached({}, motion.output.new_acceleration, 1e-8));
        // A late network refresh cannot cancel a stop already in progress.
        motion.advance(jacobian, previous, command, false, .001);
        assert(motion.finished && reached({}, motion.output.new_velocity, 1e-8));
      }
    }
  }
  Twist diagonal{1, 1, 1, 1, 1, 1};
  for (const Jacobian& j : {Jacobian{}, jacobian}) {
    const auto velocity = cartesian_velocity(j, start, diagonal, default_speed);
    for (double value : velocity) assert(std::isfinite(value) && std::abs(value) <= default_speed);
  }
  // Approaching a joint boundary must taper before braking room is exhausted.
  for (double sign : {-1.0, 1.0}) {
    auto position = start;
    position[0] = sign > 0 ? joint_upper[0] - .2 : joint_lower[0] + .2;
    CartesianMotion motion(position, {}, {}, 20 * M_PI / 180);
    Twist command{};
    command[0] = sign;
    for (int i = 0; i < 30000; ++i) {
      position = motion.advance(jacobian, position, command, false, .001);
      validate_target(position);
    }
    assert(sign > 0 ? position[0] < joint_upper[0] : position[0] > joint_lower[0]);
    assert(std::abs(motion.output.new_velocity[0]) < 1e-5);
    command[0] *= -1;
    for (int i = 0; i < 500; ++i)
      position = motion.advance(jacobian, position, command, false, .001);
    assert(motion.output.new_velocity[0] * sign < 0);  // Moving away remains possible.
  }
  CartesianMotion stalled(start, {}, {}, default_speed);
  auto measured = start;
  measured[0] += .1;
  bool rejected = false;
  try {
    stalled.advance(jacobian, measured, diagonal, false, .001);
  } catch (const std::runtime_error&) {
    rejected = true;
  }
  assert(rejected);
}
