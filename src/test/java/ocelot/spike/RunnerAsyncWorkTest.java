package ocelot.spike;

import java.util.concurrent.*;
import org.junit.Test;
import scala.runtime.AbstractFunction1;
import static org.junit.Assert.*;

public class RunnerAsyncWorkTest {
    private static void resetTracking() {
        try {
            java.lang.reflect.Field uncertain=RunnerAsyncWork.class.getDeclaredField("uncertain");
            uncertain.setAccessible(true);uncertain.setBoolean(null,false);
        } catch(ReflectiveOperationException error) {throw new AssertionError(error);}
    }
    @Test public void submissionAndFutureBothPreventJumpIncludingPreBindWork() throws Exception {
        ScheduledExecutorService pool=Executors.newSingleThreadScheduledExecutor();
        CountDownLatch entered=new CountDownLatch(1),release=new CountDownLatch(1);
        try {
            Future<?> future=(Future<?>)RunnerAsyncWork.submit(new AbstractFunction1<Object,Object>() {
                public Object apply(Object executor) {
                    assertFalse(RunnerAsyncWork.trackedIdle());
                    return pool.submit(()->{entered.countDown();try {release.await();}catch(InterruptedException e) {Thread.currentThread().interrupt();}});
                }
            },pool);
            assertTrue(entered.await(1,TimeUnit.SECONDS));
            try(RunnerScheduler owner=RunnerScheduler.bind(true,RunnerAsyncWork::trackedIdle)) {
                RunnerScheduler.sleep(1);assertEquals(0,owner.skippedNanos());
                release.countDown();future.get(1,TimeUnit.SECONDS);
                assertTrue(RunnerAsyncWork.trackedIdle());RunnerScheduler.sleep(10);assertTrue(owner.skippedNanos()>0);
            }
        } finally {release.countDown();pool.shutdownNow();}
    }
    @Test public void cancelledFutureIsNotProofItsTaskStopped() {
        FutureTask<Void> future=new FutureTask<>(()->null);
        RunnerAsyncWork.submit(new AbstractFunction1<Object,Object>() {public Object apply(Object executor) {return future;}},null);
        future.cancel(true);assertFalse(RunnerAsyncWork.trackedIdle());
        resetTracking();
    }
    @Test public void chunkQueuedThenRemovedNeverExecutesAndReleasesReservation() throws Exception {
        ThreadPoolExecutor pool=(ThreadPoolExecutor)Executors.newFixedThreadPool(1);
        CountDownLatch entered=new CountDownLatch(1),release=new CountDownLatch(1);
        Runnable task=()->fail("removed read executed");
        try {
            pool.execute(()->{entered.countDown();try {release.await();}catch(InterruptedException e) {Thread.currentThread().interrupt();}});
            assertTrue(entered.await(1,TimeUnit.SECONDS));
            RunnerAsyncWork.executeChunk(pool,task);assertFalse(RunnerAsyncWork.trackedIdle());
            assertTrue(RunnerAsyncWork.removeChunk(pool,task));assertTrue(RunnerAsyncWork.trackedIdle());
        } finally {release.countDown();pool.shutdownNow();}
    }
    @Test public void droppedRunningChunkRemainsOwnedUntilItReturns() throws Exception {
        ThreadPoolExecutor pool=new ThreadPoolExecutor(1,1,0,TimeUnit.SECONDS,new LinkedBlockingQueue<>()) {
            protected void afterExecute(Runnable task,Throwable error) {RunnerAsyncWork.chunkFinished(task);}
        };
        CountDownLatch entered=new CountDownLatch(1),release=new CountDownLatch(1);
        Runnable task=()->{entered.countDown();try {release.await();}catch(InterruptedException e) {Thread.currentThread().interrupt();}};
        try {
            RunnerAsyncWork.executeChunk(pool,task);assertTrue(entered.await(1,TimeUnit.SECONDS));
            assertFalse(RunnerAsyncWork.removeChunk(pool,task));assertFalse(RunnerAsyncWork.trackedIdle());
            release.countDown();pool.submit(()->{}).get(1,TimeUnit.SECONDS);assertTrue(RunnerAsyncWork.trackedIdle());
        } finally {release.countDown();pool.shutdownNow();}
    }
    @Test public void submissionFailureCannotBeMistakenForQuiescence() {
        try {
            RunnerAsyncWork.submit(new AbstractFunction1<Object,Object>() {
                public Object apply(Object executor) {throw new IllegalStateException("failed after possible submission");}
            },null);fail();
        } catch(IllegalStateException expected) {assertFalse(RunnerAsyncWork.trackedIdle());}
        finally {resetTracking();}
    }
}
