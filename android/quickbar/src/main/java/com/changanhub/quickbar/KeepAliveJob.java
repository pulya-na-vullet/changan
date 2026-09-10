package com.changanhub.quickbar;

import android.app.job.JobInfo;
import android.app.job.JobParameters;
import android.app.job.JobScheduler;
import android.app.job.JobService;
import android.content.ComponentName;
import android.content.Context;

/**
 * Persisted periodic job so Feiyu can restart QuickBar after ACC even when
 * BOOT_COMPLETED is dropped and AlarmManager was cleared.
 */
public class KeepAliveJob extends JobService {
    private static final int JOB_ID = 71;
    private static final long PERIOD_MS = 15 * 60 * 1000L;

    public static void schedule(Context context) {
        JobScheduler scheduler = (JobScheduler) context.getSystemService(Context.JOB_SCHEDULER_SERVICE);
        if (scheduler == null) {
            return;
        }
        JobInfo job = new JobInfo.Builder(JOB_ID, new ComponentName(context, KeepAliveJob.class))
                .setPersisted(true)
                .setPeriodic(PERIOD_MS)
                .setRequiredNetworkType(JobInfo.NETWORK_TYPE_NONE)
                .build();
        try {
            scheduler.schedule(job);
        } catch (Exception ignored) {
        }
    }

    @Override
    public boolean onStartJob(JobParameters params) {
        OverlayService.start(this);
        OverlayService.scheduleWatchdog(this);
        jobFinished(params, false);
        return false;
    }

    @Override
    public boolean onStopJob(JobParameters params) {
        return true;
    }
}
