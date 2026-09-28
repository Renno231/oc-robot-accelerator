package ocelot.spike;

import java.util.*;
import java.util.concurrent.*;
import java.util.function.BooleanSupplier;

/** One native machine's temporal owner. Only globally idle waiting may be skipped. */
public final class RunnerScheduler implements AutoCloseable {
    static final Object LOCK=new Object();
    private static volatile RunnerScheduler active;
    private final Thread serverThread=Thread.currentThread();
    private final boolean accelerated;
    private final BooleanSupplier externalIdle;
    private final PriorityQueue<Ticket> pending=new PriorityQueue<>(Comparator.comparingLong(ticket->ticket.due));
    private final Set<Ticket> running=new HashSet<>();
    private Runnable machine;
    private long skippedNanos,creditedMillis,workerPasses;
    private volatile boolean closed;
    private Throwable failure;
    private static final int QUEUE_LIMIT=256;

    private RunnerScheduler(boolean accelerated,BooleanSupplier externalIdle) {
        this.accelerated=accelerated;this.externalIdle=externalIdle;
    }
    static RunnerScheduler bind(boolean accelerated,BooleanSupplier externalIdle) {
        synchronized(LOCK) {
            if(active!=null && !active.closed) throw new IllegalStateException("scheduler_already_owned");
            active=new RunnerScheduler(accelerated,externalIdle);return active;
        }
    }
    void attach(Runnable target) {
        synchronized(LOCK) {
            if(machine!=null || target==null || closed) throw new IllegalStateException("scheduler_machine_ownership");
            machine=target;
        }
    }
    private long now() {return System.nanoTime()+skippedNanos;}

    /** Exact native Machine.switchTo hook. Legacy and unrelated machines pass through. */
    public static ScheduledFuture<?> schedule(ScheduledExecutorService executor,Runnable task,long delay,TimeUnit unit) {
        synchronized(LOCK) {
            RunnerScheduler owner=active;
            if(owner==null || task!=owner.machine) return executor.schedule(task,delay,unit);
            long nanos=unit.toNanos(delay);
            if(nanos<0 || nanos>TimeUnit.MILLISECONDS.toNanos(12)) throw new IllegalStateException("scheduler_delay");
            Ticket ticket=owner.new Ticket(executor,task,owner.now()+nanos);
            if(owner.closed) ticket.cancel(false);
            else {
                if(owner.pending.size()+owner.running.size()>=QUEUE_LIMIT) throw new IllegalStateException("scheduler_queue_limit");
                owner.pending.add(ticket);
                try {ticket.timer=executor.schedule(ticket::timerFired,nanos,TimeUnit.NANOSECONDS);}
                catch(RejectedExecutionException error) {ticket.cancel(false);owner.failure=error;throw error;}
                LOCK.notifyAll();
            }
            return ticket;
        }
    }

    /** Preserve the native server sleep interval; compress only its idle portions. */
    public static boolean sleep(long millis) throws InterruptedException {
        RunnerScheduler owner=active;
        if(owner==null) return false;
        owner.idleSleep(millis);return true;
    }
    private void idleSleep(long millis) throws InterruptedException {
        if(Thread.currentThread()!=serverThread) throw new IllegalStateException("scheduler_server_thread");
        if(closed) {Thread.sleep(millis);return;}
        if(millis<0 || millis>50) throw new IllegalArgumentException("server sleep outside pinned pacer bound");
        synchronized(LOCK) {
            final long end=now()+TimeUnit.MILLISECONDS.toNanos(millis);
            while(!closed) {
                if(Thread.interrupted()) throw new InterruptedException();
                long at=now();
                dispatchDue(at);
                if(at>=end) return;
                long next=end;
                for(Ticket ticket:pending) next=Math.min(next,ticket.due);
                // Both task reservation and time advancement occur under LOCK.
                // A due task awaiting its host thread is RUNNABLE, not idle.
                if(accelerated && running.isEmpty() && externalIdle.getAsBoolean()) {
                    long delta=Math.max(0,next-now());
                    skippedNanos+=delta;
                    continue;
                }
                long wait=Math.max(1,Math.min(next-now(),TimeUnit.MILLISECONDS.toNanos(1)));
                TimeUnit.NANOSECONDS.timedWait(LOCK,wait);
            }
        }
    }
    private void dispatchDue(long at) {
        while(!pending.isEmpty() && pending.peek().due<=at) {
            Ticket ticket=pending.peek();
            if(ticket.reserve()) {
                if(ticket.timer!=null) ticket.timer.cancel(false);
                try {ticket.executor.execute(ticket::runReserved);}
                catch(RejectedExecutionException error) {running.remove(ticket);ticket.cancel(false);failure=error;throw error;}
            } else pending.remove(ticket);
        }
    }
    /** Add only skipped waiting, once. Native elapsed host milliseconds remain native. */
    public static long credit(long accumulator) {
        synchronized(LOCK) {
            RunnerScheduler owner=active;
            if(owner==null) return accumulator;
            long total=TimeUnit.NANOSECONDS.toMillis(owner.skippedNanos);
            long delta=total-owner.creditedMillis;owner.creditedMillis=total;
            return Math.addExact(accumulator,delta);
        }
    }
    static boolean ownsPacer() {return active!=null;}
    public static long environmentMillis() {
        synchronized(LOCK) {
            return System.currentTimeMillis()+(active==null?0:TimeUnit.NANOSECONDS.toMillis(active.skippedNanos));
        }
    }
    public static Calendar environmentCalendar() {
        Calendar result=Calendar.getInstance();result.setTimeInMillis(environmentMillis());return result;
    }
    void checkProgress() {
        synchronized(LOCK) {
            if(failure!=null) throw new IllegalStateException("worker_dispatch_failure",failure);
            long at=System.nanoTime();
            for(Ticket ticket:running) if(at-ticket.started>=TimeUnit.SECONDS.toNanos(1))
                throw new IllegalStateException("worker_progress_limit");
        }
    }
    long workerPasses() {synchronized(LOCK) {return workerPasses;}}
    long skippedNanos() {synchronized(LOCK) {return skippedNanos;}}
    @Override public void close() {
        synchronized(LOCK) {
            closed=true;
            for(Ticket ticket:new ArrayList<>(pending)) ticket.cancel(false);
            for(Ticket ticket:new ArrayList<>(running)) ticket.cancel(true);
            LOCK.notifyAll();
            // Keep the closed owner: a late native requeue cannot escape to wall scheduling.
        }
    }
    private final class Ticket extends FutureTask<Void> implements ScheduledFuture<Void> {
        final ScheduledExecutorService executor;
        final long due;
        long started;
        ScheduledFuture<?> timer;
        Ticket(ScheduledExecutorService executor,Runnable task,long due) {super(task,null);this.executor=executor;this.due=due;}
        boolean reserve() {
            if(closed || isCancelled() || !pending.remove(this)) return false;
            started=System.nanoTime();running.add(this);workerPasses++;return true;
        }
        void timerFired() {
            synchronized(LOCK) {if(!reserve()) return;}
            runReserved();
        }
        void runReserved() {
            try {super.run();}
            finally {synchronized(LOCK) {running.remove(this);LOCK.notifyAll();}}
        }
        @Override protected void done() {
            if(!isCancelled()) try {get();}
            catch(InterruptedException error) {Thread.currentThread().interrupt();}
            catch(ExecutionException error) {synchronized(LOCK) {failure=error.getCause();}}
        }
        @Override public boolean cancel(boolean interrupt) {
            synchronized(LOCK) {
                pending.remove(this);
                if(timer!=null) timer.cancel(false);
                boolean result=super.cancel(interrupt);LOCK.notifyAll();return result;
            }
        }
        public long getDelay(TimeUnit unit) {synchronized(LOCK) {return unit.convert(due-now(),TimeUnit.NANOSECONDS);}}
        public int compareTo(Delayed other) {return Long.compare(getDelay(TimeUnit.NANOSECONDS),other.getDelay(TimeUnit.NANOSECONDS));}
    }
}
