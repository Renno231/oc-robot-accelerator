package ocelot.spike;

import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
import org.junit.Test;
import static org.junit.Assert.*;

public class RunnerSchedulerTest {
    @Test public void runningLuaDoesNotFreezeWorldTickOpportunitiesOrBecomeIdleTime() throws Exception {
        ScheduledExecutorService pool=Executors.newSingleThreadScheduledExecutor();
        CountDownLatch entered=new CountDownLatch(1),release=new CountDownLatch(1);
        Runnable task=()->{entered.countDown();try {release.await();} catch(InterruptedException e) {Thread.currentThread().interrupt();}};
        try(RunnerScheduler owner=RunnerScheduler.bind(true,()->true)) {
            owner.attach(task);ScheduledFuture<?> work=RunnerScheduler.schedule(pool,task,0,TimeUnit.MILLISECONDS);
            assertTrue(entered.await(1,TimeUnit.SECONDS));
            // The server can return from its native pacer and tick while the worker is still executing.
            assertTrue(RunnerScheduler.sleep(1));assertFalse(work.isDone());assertEquals(0,owner.skippedNanos());
            release.countDown();work.get(1,TimeUnit.SECONDS);
        } finally {release.countDown();pool.shutdownNow();}
    }
    @Test public void idleTimeCreditIsExactAndNotAForcedTick() throws Exception {
        try(RunnerScheduler owner=RunnerScheduler.bind(true,()->true)) {
            RunnerScheduler.sleep(10);
            long skipped=TimeUnit.NANOSECONDS.toMillis(owner.skippedNanos());assertTrue(skipped>0);
            assertEquals(7+skipped,RunnerScheduler.credit(7));assertEquals(7,RunnerScheduler.credit(7));
        }
    }
    @Test public void unknownAsyncWorkPreventsTimeJump() throws Exception {
        AtomicBoolean idle=new AtomicBoolean(false);
        try(RunnerScheduler owner=RunnerScheduler.bind(true,idle::get)) {
            RunnerScheduler.sleep(1);assertEquals(0,owner.skippedNanos());
            idle.set(true);RunnerScheduler.sleep(10);assertTrue(owner.skippedNanos()>0);
        }
    }
    @Test public void pendingDelayIsDispatchedAtTheNextEventOffTheServerThread() throws Exception {
        ScheduledExecutorService pool=Executors.newSingleThreadScheduledExecutor();Thread server=Thread.currentThread();
        AtomicInteger calls=new AtomicInteger();Runnable task=()->{assertNotSame(server,Thread.currentThread());calls.incrementAndGet();};
        try(RunnerScheduler owner=RunnerScheduler.bind(true,()->true)) {
            owner.attach(task);ScheduledFuture<?> work=RunnerScheduler.schedule(pool,task,12,TimeUnit.MILLISECONDS);
            RunnerScheduler.sleep(50);work.get(1,TimeUnit.SECONDS);assertEquals(1,calls.get());
            assertEquals(1,owner.workerPasses());assertTrue(owner.skippedNanos()>0);
        } finally {pool.shutdownNow();}
    }
    @Test public void zeroDelayRequeuesHaveNoPerTickResumeQuota() throws Exception {
        ScheduledExecutorService pool=Executors.newSingleThreadScheduledExecutor();AtomicInteger calls=new AtomicInteger();
        CountDownLatch done=new CountDownLatch(1);
        Runnable task=new Runnable() {public void run() {
            if(calls.incrementAndGet()<600) RunnerScheduler.schedule(pool,this,0,TimeUnit.MILLISECONDS);else done.countDown();
        }};
        try(RunnerScheduler owner=RunnerScheduler.bind(true,()->true)) {
            owner.attach(task);RunnerScheduler.schedule(pool,task,0,TimeUnit.MILLISECONDS);
            // No artificial tick(), grant(), or batch refill is needed to execute more than 256 resumes.
            assertTrue(done.await(2,TimeUnit.SECONDS));assertEquals(600,calls.get());assertEquals(0,owner.skippedNanos());
        } finally {pool.shutdownNow();}
    }
    @Test public void unrelatedTasksRemainNativeAndCloseCancelsPendingWork() throws Exception {
        ScheduledExecutorService pool=Executors.newSingleThreadScheduledExecutor();AtomicInteger calls=new AtomicInteger();
        CountDownLatch occupied=new CountDownLatch(1),release=new CountDownLatch(1);
        Runnable task=calls::incrementAndGet;
        try(RunnerScheduler owner=RunnerScheduler.bind(true,()->true)) {
            owner.attach(task);
            RunnerScheduler.schedule(pool,()->calls.addAndGet(10),0,TimeUnit.MILLISECONDS).get(1,TimeUnit.SECONDS);
            pool.execute(()->{occupied.countDown();try {release.await();}catch(InterruptedException e) {Thread.currentThread().interrupt();}});
            assertTrue(occupied.await(1,TimeUnit.SECONDS));
            ScheduledFuture<?> work=RunnerScheduler.schedule(pool,task,12,TimeUnit.MILLISECONDS);
            owner.close();assertTrue(work.isCancelled());assertEquals(10,calls.get());
            assertTrue(RunnerScheduler.schedule(pool,task,0,TimeUnit.MILLISECONDS).isCancelled());
        } finally {release.countDown();pool.shutdownNow();}
    }
    @Test public void workerFailureIsRetainedForTheRuntimeOwner() throws Exception {
        ScheduledExecutorService pool=Executors.newSingleThreadScheduledExecutor();Runnable task=()->{throw new IllegalStateException("broken");};
        try(RunnerScheduler owner=RunnerScheduler.bind(true,()->true)) {
            owner.attach(task);ScheduledFuture<?> future=RunnerScheduler.schedule(pool,task,0,TimeUnit.MILLISECONDS);
            try {future.get(1,TimeUnit.SECONDS);fail();}catch(ExecutionException expected) {assertEquals("broken",expected.getCause().getMessage());}
            // Future completion may precede FutureTask.done; synchronize through a later pool task.
            pool.submit(()->{}).get(1,TimeUnit.SECONDS);
            try {owner.checkProgress();fail();}catch(IllegalStateException expected) {assertEquals("worker_dispatch_failure",expected.getMessage());}
        } finally {pool.shutdownNow();}
    }
    @Test public void reservedTaskWaitingForHostThreadIsNotQuiescent() throws Exception {
        ScheduledExecutorService pool=Executors.newSingleThreadScheduledExecutor();
        CountDownLatch occupied=new CountDownLatch(1),release=new CountDownLatch(1);
        pool.execute(()->{occupied.countDown();try {release.await();}catch(InterruptedException e) {Thread.currentThread().interrupt();}});
        Runnable task=()->{};
        try(RunnerScheduler owner=RunnerScheduler.bind(true,()->true)) {
            assertTrue(occupied.await(1,TimeUnit.SECONDS));owner.attach(task);
            ScheduledFuture<?> work=RunnerScheduler.schedule(pool,task,0,TimeUnit.MILLISECONDS);
            RunnerScheduler.sleep(1);assertFalse(work.isDone());assertEquals(0,owner.skippedNanos());
            release.countDown();work.get(1,TimeUnit.SECONDS);
        } finally {release.countDown();pool.shutdownNow();}
    }
    @Test public void rejectedTimerDoesNotLeakPendingOwnership() {
        ScheduledExecutorService pool=Executors.newSingleThreadScheduledExecutor();pool.shutdownNow();Runnable task=()->{};
        try(RunnerScheduler owner=RunnerScheduler.bind(true,()->true)) {
            owner.attach(task);
            try {RunnerScheduler.schedule(pool,task,12,TimeUnit.MILLISECONDS);fail();}catch(RejectedExecutionException expected) {}
            try {owner.checkProgress();fail();}catch(IllegalStateException expected) {assertEquals("worker_dispatch_failure",expected.getMessage());}
        }
    }
    @Test public void environmentTimeIncludesOnlySkippedIdleAndPacerCreditsItOnce() throws Exception {
        try(RunnerScheduler owner=RunnerScheduler.bind(true,()->true)) {
            long hostBefore=System.currentTimeMillis();RunnerScheduler.sleep(50);
            long logical=RunnerScheduler.environmentMillis(),hostAfter=System.currentTimeMillis();
            long skipped=TimeUnit.NANOSECONDS.toMillis(owner.skippedNanos());
            assertTrue(logical>=hostBefore+skipped);assertTrue(logical<=hostAfter+skipped);
            assertEquals(3+skipped,Pacing.nextAccumulator(3));assertEquals(3,Pacing.nextAccumulator(3));
            assertTrue(Math.abs(RunnerScheduler.environmentCalendar().getTimeInMillis()-RunnerScheduler.environmentMillis())<100);
        }
    }
    @Test public void pacedReferenceNeverSkipsIdleTime() throws Exception {
        try(RunnerScheduler owner=RunnerScheduler.bind(false,()->true)) {
            RunnerScheduler.sleep(1);assertEquals(0,owner.skippedNanos());assertEquals(7,RunnerScheduler.credit(7));
        }
    }
}
