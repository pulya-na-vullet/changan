package com.changanhub.quickbar;

import android.app.job.JobInfo;
import android.app.job.JobParameters;
import android.app.job.JobScheduler;
import android.app.job.JobService;
import android.content.ComponentName;
import android.content.Context;

/**
 * One-shot persisted job that reschedules itself. Periodic 15-minute jobs are
 * too slow after ACC: Feiyu drops BOOT_COMPLETED and the panel must come back
 * within seconds. setPersisted survives a real reboot; a 3s latency / 12s
 * deadline forces JobScheduler to run soon after the HU wakes.
 */
public class KeepAliveJob extends JobService {
    private static final int JOB_ID = 71;
    private static final long LATENCY_MS = 3_000L;
    private static final long DEADLINE_MS = 12_000L;

    public static void schedule(Context context) {
        JobScheduler scheduler = (JobScheduler) context.getSystemService(Context.JOB_SCHEDULER_SERVICE);
        if (scheduler == null) {
            return;
        }
        JobInfo job = new JobInfo.Builder(JOB_ID, new ComponentName(context, KeepAliveJob.class))
                .setPersisted(true)
                .setMinimumLatency(LATENCY_MS)
                .setOverrideDeadline(DEADLINE_MS)
                .setRequiredNetworkType(JobInfo.NETWORK_TYPE_NONE)
                .build();
        try {
            scheduler.schedule(job);
        } catch (Exception ignored) {
        }
    }

    @Override
    public boolean onStartJob(JobParameters params) {
        OverlayService.keepAlive(this);
        OverlayService.scheduleWatchdog(this);
        schedule(this);
        jobFinished(params, false);
        return false;
    }

    @Override
    public boolean onStopJob(JobParameters params) {
        return true;
    }
}
