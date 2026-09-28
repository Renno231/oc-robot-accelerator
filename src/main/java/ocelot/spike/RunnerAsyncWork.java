package ocelot.spike;

import java.lang.reflect.Field;
import java.util.*;
import java.util.concurrent.*;
import net.minecraft.world.storage.ThreadedFileIOBase;
import scala.Function1;

/** Pinned OC save submissions and Forge chunk reads, from admission through completion.
 * Shares the temporal owner's lock so an async admission cannot race an idle jump.
 * Tracking starts at class loading, including work submitted before the runner binds.
 */
public final class RunnerAsyncWork {
    private static final Set<Future<?>> futures=Collections.newSetFromMap(new IdentityHashMap<>());
    private static final Set<Runnable> chunks=Collections.newSetFromMap(new IdentityHashMap<>());
    private static int submitting;
    private static boolean uncertain;
    private static final int LIMIT=4096;
    private RunnerAsyncWork() {}

    /** Replaces only Function1.apply inside the pinned SafeThreadPool.withPool. */
    public static Object submit(Function1<Object,Object> function,Object executor) {
        synchronized(RunnerScheduler.LOCK) {prune();capacity();submitting++;}
        Object result=null;boolean completed=false;
        try {result=function.apply(executor);completed=true;return result;}
        finally {
            synchronized(RunnerScheduler.LOCK) {
                submitting--;
                // A throwing callback may already have submitted work without returning its Future.
                if(!completed) uncertain=true;
                else if(result instanceof Future<?>) futures.add((Future<?>)result);
                else if(result!=null) uncertain=true;
                RunnerScheduler.LOCK.notifyAll();
            }
        }
    }
    public static void executeChunk(ThreadPoolExecutor executor,Runnable task) {
        synchronized(RunnerScheduler.LOCK) {prune();capacity();if(!chunks.add(task)) throw new IllegalStateException("duplicate_chunk_submission");}
        try {executor.execute(task);}
        catch(RuntimeException | Error error) {chunkFinished(task);throw error;}
    }
    public static boolean removeChunk(ThreadPoolExecutor executor,Runnable task) {
        // Native remove success proves it did not begin executing. On failure a
        // dropped callback does NOT imply that its asynchronous read has stopped.
        boolean removed=executor.remove(task);
        if(removed) chunkFinished(task);
        return removed;
    }
    /** Called at the native executor's afterExecute boundary, including exceptions. */
    public static void chunkFinished(Runnable task) {
        synchronized(RunnerScheduler.LOCK) {chunks.remove(task);RunnerScheduler.LOCK.notifyAll();}
    }
    private static void capacity() {
        if(futures.size()+chunks.size()+submitting>=LIMIT) throw new IllegalStateException("async_tracking_limit");
    }
    private static void prune() {
        for(Iterator<Future<?>> iterator=futures.iterator();iterator.hasNext();) {
            Future<?> future=iterator.next();
            // Future.cancel marks done before the task necessarily exits. Never
            // infer idleness from cancellation (native shutdown is the usual caller).
            if(future.isCancelled()) uncertain=true;
            if(future.isDone()) iterator.remove();
        }
    }
    static boolean trackedIdle() {
        synchronized(RunnerScheduler.LOCK) {prune();return !uncertain && submitting==0 && futures.isEmpty() && chunks.isEmpty();}
    }
    static boolean nativeIdle() {
        synchronized(RunnerScheduler.LOCK) {
            if(!trackedIdle()) return false;
            // Queue producers are the world thread, owned OC worker or tracked
            // asynchronous work. At this boundary they cannot enqueue behind us.
            // Completion can only turn a conservative no-jump into idle.
            try {return NativeIO.queued.getLong(NativeIO.owner)==NativeIO.saved.getLong(NativeIO.owner);}
            catch(IllegalAccessException error) {throw new IllegalStateException("native_io_clock_coverage",error);}
        }
    }
    private static final class NativeIO {
        static final Object owner=ThreadedFileIOBase.getThreadedIOInstance();
        static final Field queued=counter("writeQueuedCounter","field_75740_c");
        static final Field saved=counter("savedIOCounter","field_75737_d");
        private static Field counter(String... names) {
            for(String name:names) try {
                Field field=owner.getClass().getDeclaredField(name);
                if(field.getType()!=long.class || !java.lang.reflect.Modifier.isVolatile(field.getModifiers()))
                    throw new IllegalStateException("native_io_counter_shape:"+name);
                field.setAccessible(true);return field;
            } catch(NoSuchFieldException absent) { /* development MCP or production SRG */ }
            throw new IllegalStateException("native_io_counter_missing");
        }
    }
}
