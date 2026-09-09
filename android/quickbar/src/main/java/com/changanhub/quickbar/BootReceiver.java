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
        String action = intent != null ? intent.getAction() : "";
        if (Intent.ACTION_USER_PRESENT.equals(action)
                || Intent.ACTION_USER_UNLOCKED.equals(action)) {
            OverlayService.keepAlive(app);
        } else {
            OverlayService.start(app);
        }
        OverlayService.scheduleWatchdog(app);
        OverlayService.scheduleBootRetries(app);
    }
}
