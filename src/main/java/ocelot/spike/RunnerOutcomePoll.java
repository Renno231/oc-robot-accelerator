package ocelot.spike;

/** Wall-clock sampling of runner-owned files; native machine execution is unchanged. */
final class RunnerOutcomePoll {
    static final long INTERVAL_NANOS=10000000L;
    private boolean first=true;
    private long last;
    boolean due(long now,boolean running) {
        if(!first && running && now-last<INTERVAL_NANOS)return false;
        first=false;last=now;return true;
    }
}
