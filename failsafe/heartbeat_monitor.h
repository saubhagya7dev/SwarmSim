// SwarmSim failsafe supervisor - embedded-style C++ port of swarmsim/supervisor.py.
//
// Pure state machine: no heap, no exceptions, no STL, no dynamic dispatch. The only inputs
// per tick are the time, the age of the last peer message, the age of the last GPS fix and
// an on-ground flag, so it can run on a microcontroller (an ESP32 or Arduino-class board)
// next to the flight controller. tests/test_cpp_conformance.py replays recorded simulator
// traces through both implementations and requires identical mode sequences.
#pragma once

namespace swarmsim {

enum Mode : int {
    FORMATION = 0,     // normal flight
    HOLD = 1,          // no peer heard for link_timeout: hold position
    FAILSAFE_GPS = 2,  // no GPS fix for gps_timeout: hover on dead reckoning
    LANDING = 3,       // GPS failsafe lasted gps_land_after: controlled descent (latched)
    LANDED = 4,        // on the ground (terminal)
    FAILED = 5         // vehicle failure signalled from outside (terminal)
};

struct Params {
    double link_timeout;    // [s] with no peer heard -> HOLD
    double link_recovery;   // [s] of continuous reception needed to leave HOLD
    double gps_timeout;     // [s] with no accepted fix -> GPS failsafe
    double gps_recovery;    // [s] of fixes needed to leave GPS failsafe
    double gps_land_after;  // [s] in GPS failsafe before landing
    double hb_timeout;      // [s] a peer message counts as "recent" for recovery streaks
};

class HeartbeatMonitor {
public:
    explicit HeartbeatMonitor(const Params& p)
        : p_(p), mode_(FORMATION), t_gps_lost_(0.0), gps_ok_since_(0.0), have_gps_ok_(false),
          in_streak_(false), streak_start_(0.0) {}

    // Advance one tick. Returns true when the mode changed.
    bool step(double t, double link_age, double gps_age, bool on_ground) {
        const Mode old = mode_;
        if (old == FAILED) return false;

        if (link_age < p_.hb_timeout) {
            if (!in_streak_) { in_streak_ = true; streak_start_ = t; }
        } else {
            in_streak_ = false;
        }

        const bool gps_lost = gps_age > p_.gps_timeout;
        if (gps_lost) {
            have_gps_ok_ = false;
        } else if (!have_gps_ok_) {
            have_gps_ok_ = true;
            gps_ok_since_ = t;
        }

        Mode m = mode_;
        if (m == LANDED) {
            // terminal
        } else if (m == LANDING) {
            if (on_ground) mode_ = LANDED;
        } else {
            if (gps_lost) {
                if (m == FORMATION || m == HOLD) {
                    mode_ = FAILSAFE_GPS;
                    t_gps_lost_ = t;
                } else if (m == FAILSAFE_GPS && (t - t_gps_lost_) >= p_.gps_land_after) {
                    mode_ = LANDING;
                }
            } else {
                if (m == FAILSAFE_GPS && (t - gps_ok_since_) >= p_.gps_recovery) {
                    mode_ = FORMATION;
                }
            }
            m = mode_;
            if (m == FORMATION || m == HOLD) {
                if (link_age > p_.link_timeout) {
                    mode_ = HOLD;
                } else if (m == HOLD && in_streak_ && (t - streak_start_) >= p_.link_recovery) {
                    mode_ = FORMATION;
                }
            }
        }
        return mode_ != old;
    }

    void force_failed() { mode_ = FAILED; }
    Mode mode() const { return mode_; }

private:
    Params p_;
    Mode mode_;
    double t_gps_lost_;
    double gps_ok_since_;
    bool have_gps_ok_;
    bool in_streak_;
    double streak_start_;
};

}  // namespace swarmsim
