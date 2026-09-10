package com.changanhub.quickbar;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

/** AlarmManager callback: restart the overlay after Feiyu kills the process. */
public class WatchdogReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context context, Intent intent) {
        Context app = context.getApplicationContext();
        String action = intent != null ? intent.getAction() : OverlayService.ACTION_KEEPALIVE;
        if (OverlayService.ACTION_SHOW.equals(action)) {
            OverlayService.start(app);
        } else if (OverlayService.ACTION_RESUME.equals(action)) {
            OverlayService.resumeAfterSleep(app);
        } else {
            OverlayService.keepAlive(app);
        }
        OverlayService.scheduleWatchdog(app);
        KeepAliveJob.schedule(app);
    }
}
