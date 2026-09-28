package ocelot.spike;

/** Native sleep boundary; v3 credits proven idle compression, legacy fixtures retain their pacing. */
public final class Pacing {
    private Pacing() {}
    public static String mode() {
        String mode = System.getProperty("robotspike.mode", "baseline");
        accumulator(mode, 0);
        return mode;
    }
    static long accumulator(String mode, long value) {
        switch (mode) {
            case "baseline": case "paced": return value;
            case "unpaced": case "coordinated": return Math.max(51L, value);
            default: throw new IllegalArgumentException("Unknown robotspike.mode: " + mode);
        }
    }
    public static long nextAccumulator(long value) {
        return RunnerScheduler.ownsPacer()?RunnerScheduler.credit(value):accumulator(mode(),value);
    }
    public static void sleep(long millis) throws InterruptedException {
        if(RunnerScheduler.sleep(millis)) return;
        if (mode().equals("baseline") || mode().equals("paced")) Thread.sleep(millis);
        else if (Thread.interrupted()) throw new InterruptedException();
    }
}
