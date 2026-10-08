// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Exercise the production trajectory without opening a physical robot connection.
#include <cassert>
#include <limits>

#include "jog.hpp"

using namespace telesurgery;

static void sample(const JointMotion& motion, const Joints& previous, const Joints& acceleration,
                   double speed, double dt) {
  const auto& output = motion.output;
  validate_target(output.new_position);
  for (size_t j = 0; j < 7; ++j) {
    assert(std::abs(output.new_velocity[j]) <= speed + 1e-9);
    assert(std::abs(output.new_acceleration[j]) <= 0.2 + 1e-9);
    assert(std::abs(output.new_acceleration[j] - acceleration[j]) <= 2.0 * dt + 1e-8);
    assert(std::abs(output.new_position[j] - previous[j]) <= speed * dt + 1e-9);
  }
}

int main() {
  Joints home{-24.475, -18.378, 13.651, -106.151, 9.422, 90.758, -21.335};
  for (auto& value : home) value *= M_PI / 180;
  validate_target(home);
  for (size_t j = 0; j < home.size(); ++j) {
    for (double bad : {-4.0, 4.0, std::numeric_limits<double>::quiet_NaN()}) {
      auto invalid = home;
      invalid[j] = bad;
      bool rejected = false;
      try {
        validate_target(invalid);
      } catch (const std::invalid_argument&) {
        rejected = true;
      }
      assert(rejected);
    }
  }
  for (double bad : {0.0, -0.1, 0.35, std::numeric_limits<double>::infinity(),
                     std::numeric_limits<double>::quiet_NaN()}) {
    bool rejected = false;
    try {
      validate_speed(bad);
    } catch (const std::invalid_argument&) {
      rejected = true;
    }
    assert(rejected);
  }
  for (double bad : {0.088, -0.088, std::numeric_limits<double>::infinity(),
                     std::numeric_limits<double>::quiet_NaN()}) {
    Joints delta{};
    delta[0] = bad;
    bool rejected = false;
    try {
      validate_delta(delta);
    } catch (const std::invalid_argument&) {
      rejected = true;
    }
    assert(rejected);
  }
  for (double speed_deg : {0.2, 2.0, 10.0, 20.0}) {
    const double speed = speed_deg * M_PI / 180;
    for (auto start : {Joints{0, -M_PI_4, 0, -3 * M_PI_4, 0, M_PI_2, 0},
                       Joints{-2.89, -1.76, -2.89, -3.07, -2.89, -0.01, -2.89},
                       Joints{2.89, 1.76, 2.89, -0.07, 2.89, 3.75, 2.89}, home}) {
      for (double stop_at : {-1.0, 0.0, 0.1, 1.0, 5.0}) {
        JointMotion motion(start, {}, {}, home, speed);
        Joints previous = start, acceleration{};
        double elapsed = 0;
        const double deadline = motion.duration() + 3;
        bool stopping = false;
        while (!motion.finished && elapsed < deadline) {
          stopping = stopping || (stop_at >= 0 && elapsed >= stop_at);
          // FCI provides elapsed time, including occasional missed packets.
          const double dt = static_cast<int>(elapsed * 1000) % 10 == 0 ? 0.002 : 0.001;
          motion.advance(home, stopping, dt);
          sample(motion, previous, acceleration, speed, dt);
          previous = motion.output.new_position;
          acceleration = motion.output.new_acceleration;
          elapsed += dt;
        }
        assert(motion.finished);
        assert(reached({}, motion.output.new_velocity, 1e-8));
        assert(reached({}, motion.output.new_acceleration, 1e-8));
        assert(stopping ? elapsed - stop_at < 3 : reached(home, previous, 1e-8));
      }
    }
    // Single taps use the same planner, including the minimum/maximum UI steps.
    for (double size : {-5.0, -1.0, -0.05, 0.05, 1.0, 5.0}) {
      Joints delta{};
      delta[4] = size * M_PI / 180;
      validate_delta(delta);
      const auto goal = target(home, delta);
      JointMotion motion(home, {}, {}, goal, speed);
      Joints previous = home, acceleration{};
      double elapsed = 0;
      const double deadline = motion.duration() + .01;
      while (!motion.finished && elapsed < deadline) {
        motion.advance(goal, false, .001);
        sample(motion, previous, acceleration, speed, .001);
        previous = motion.output.new_position;
        acceleration = motion.output.new_acceleration;
        elapsed += .001;
      }
      assert(motion.finished && reached(goal, previous, 1e-8));
    }
    // Gamepad retargeting/reversal must carry derivatives, not restart at rest.
    auto goal = home;
    goal[0] += .1;
    JointMotion motion(home, {}, {}, goal, speed);
    Joints previous = home, acceleration{};
    for (int cycle = 0; cycle < 6000; ++cycle) {
      if (cycle == 500) goal[0] = home[0] - .1;
      if (cycle == 1000) goal[0] = home[0] + .05;
      motion.advance(goal, cycle >= 1500, .001);
      sample(motion, previous, acceleration, speed, .001);
      previous = motion.output.new_position;
      acceleration = motion.output.new_acceleration;
    }
    assert(motion.finished && reached({}, motion.output.new_velocity, 1e-8));
  }
  // Every joint can transition from a tap to held input before the first target
  // is reached, using the same trajectory. Release must brake without a jump.
  const double speed = default_speed;
  for (size_t joint = 0; joint < home.size(); ++joint) {
    auto goal = home;
    goal[joint] -= M_PI / 180;
    JointMotion motion(home, {}, {}, goal, speed);
    Joints previous = home, acceleration{};
    for (int cycle = 0; cycle < 7000; ++cycle) {
      if (cycle >= 450 && cycle < 4500 && cycle % 50 == 0)
        goal[joint] = previous[joint] - M_PI / 180;
      motion.advance(goal, cycle >= 4500, .001);
      sample(motion, previous, acceleration, speed, .001);
      previous = motion.output.new_position;
      acceleration = motion.output.new_acceleration;
      if (cycle == 450) assert(!motion.finished);
    }
    assert(previous[joint] < home[joint] - 2 * M_PI / 180);
    assert(motion.finished && reached({}, motion.output.new_velocity, 1e-8));
  }
}
