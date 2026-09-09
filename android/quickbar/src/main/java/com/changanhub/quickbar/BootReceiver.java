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
        if (shouldExpand(action)) {
            OverlayService.start(app);
        } else {
            OverlayService.keepAlive(app);
        }
        OverlayService.scheduleWatchdog(app);
        if (shouldExpand(action)) {
            OverlayService.scheduleBootRetries(app);
        }
    }

    private static boolean shouldExpand(String action) {
        if (action == null || action.length() == 0) {
            return true;
        }
        return Intent.ACTION_BOOT_COMPLETED.equals(action)
                || "android.intent.action.LOCKED_BOOT_COMPLETED".equals(action)
                || "android.intent.action.QUICKBOOT_POWERON".equals(action)
                || "com.htc.intent.action.QUICKBOOT_POWERON".equals(action)
                || Intent.ACTION_MY_PACKAGE_REPLACED.equals(action)
                || Intent.ACTION_POWER_CONNECTED.equals(action)
                || "android.intent.action.ACC_ON".equals(action)
                || "android.intent.action.ACTION_ACC_ON".equals(action)
                || "com.android.action.ACC_ON".equals(action)
                || "com.microntek.bootcheck".equals(action)
                || "autolink.intent.action.ACC_ON".equals(action);
    }
}
