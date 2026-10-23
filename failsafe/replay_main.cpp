// Replays a recorded trace through the C++ supervisor and prints the resulting mode per tick.
//
// Input (stdin), first line: link_timeout link_recovery gps_timeout gps_recovery gps_land_after hb_timeout
// then one line per tick:    t link_age gps_age on_ground
// Output (stdout): one integer mode per line.
#include <cstdio>

#include "heartbeat_monitor.h"

int main() {
    swarmsim::Params p{};
    if (std::scanf("%lf %lf %lf %lf %lf %lf", &p.link_timeout, &p.link_recovery, &p.gps_timeout,
                   &p.gps_recovery, &p.gps_land_after, &p.hb_timeout) != 6) {
        std::fprintf(stderr, "bad parameter line\n");
        return 2;
    }
    swarmsim::HeartbeatMonitor mon(p);
    double t, link_age, gps_age;
    int ground;
    while (std::scanf("%lf %lf %lf %d", &t, &link_age, &gps_age, &ground) == 4) {
        mon.step(t, link_age, gps_age, ground != 0);
        std::printf("%d\n", static_cast<int>(mon.mode()));
    }
    return 0;
}
