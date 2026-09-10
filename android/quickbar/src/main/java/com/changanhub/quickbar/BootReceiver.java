package com.changanhub.quickbar;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

/**
 * Feiyu often skips BOOT_COMPLETED on ACC off→on (deep sleep / IPO, not a
 * cold boot). Catch every car-related wake, then start an invisible activity
 * so FLAG_STOPPED is cleared and OverlayService can run.
 *
 * Noisy intents (network, USB) only keep the process alive — they must not
 * expand a collapsed dock.
 */
public class BootReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context context, Intent intent) {
        Context app = context.getApplicationContext();
        String action = intent != null ? intent.getAction() : "";
        OverlayService.keepAlive(app);
        OverlayService.scheduleWatchdog(app);
        KeepAliveJob.schedule(app);
        if (isIgnitionWake(action)) {
            OverlayService.resumeAfterSleep(app);
            OverlayService.scheduleBootRetries(app);
            startTrampoline(app);
        }
    }

    static void startTrampoline(Context app) {
        try {
            Intent boot = new Intent(app, BootActivity.class);
            boot.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK
                    | Intent.FLAG_ACTIVITY_NO_ANIMATION
                    | Intent.FLAG_ACTIVITY_EXCLUDE_FROM_RECENTS
                    | Intent.FLAG_ACTIVITY_CLEAR_TOP);
            app.startActivity(boot);
        } catch (Exception ignored) {
        }
    }

    static boolean isIgnitionWake(String action) {
        if (action == null || action.length() == 0) {
            return false;
        }
        return Intent.ACTION_BOOT_COMPLETED.equals(action)
                || "android.intent.action.LOCKED_BOOT_COMPLETED".equals(action)
                || "android.intent.action.QUICKBOOT_POWERON".equals(action)
                || "com.htc.intent.action.QUICKBOOT_POWERON".equals(action)
                || Intent.ACTION_MY_PACKAGE_REPLACED.equals(action)
                || Intent.ACTION_POWER_CONNECTED.equals(action)
                || Intent.ACTION_USER_PRESENT.equals(action)
                || Intent.ACTION_USER_UNLOCKED.equals(action)
                || "android.intent.action.ACTION_BOOT_IPO".equals(action)
                || "android.intent.action.BOOT_IPO".equals(action)
                || "android.intent.action.ACTION_SHUTDOWN_IPO".equals(action)
                || "mtk.intent.action.BOOT_IPO".equals(action)
                || "com.mediatek.intent.action.BOOT_IPO".equals(action)
                || "android.intent.action.ACC_ON".equals(action)
                || "android.intent.action.ACTION_ACC_ON".equals(action)
                || "com.android.action.ACC_ON".equals(action)
                || "com.microntek.bootcheck".equals(action)
                || "autolink.intent.action.ACC_ON".equals(action)
                || "com.fyt.boot.ACCON".equals(action)
                || "com.syu.ms.ACCON".equals(action)
                || "com.incall.intent.action.ACC_ON".equals(action)
                || "com.incall.action.ACC_ON".equals(action)
                || "com.incall.intent.action.POWER_ON".equals(action);
    }
}
