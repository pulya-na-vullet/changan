package com.changanhub.quickbar;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

/**
 * Feiyu often skips BOOT_COMPLETED on ACC off→on. Catch every car-related
 * wake we can, then let AlarmManager retries finish the job.
 */
public class BootReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context context, Intent intent) {
        Context app = context.getApplicationContext();
        OverlayService.start(app);
        OverlayService.keepAlive(app);
        OverlayService.scheduleWatchdog(app);
        OverlayService.scheduleBootRetries(app);
        KeepAliveJob.schedule(app);
    }
}
