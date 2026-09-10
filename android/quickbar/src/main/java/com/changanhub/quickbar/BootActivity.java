package com.changanhub.quickbar;

import android.app.Activity;
import android.os.Bundle;

/**
 * Invisible trampoline. Feiyu force-stops third-party apps on ACC off, which
 * puts the package in FLAG_STOPPED so BOOT_COMPLETED never arrives. Starting
 * an activity from a wake receiver clears stopped state and lets OverlayService
 * run. Theme.NoDisplay + finish() in onCreate: no window on the map.
 */
public class BootActivity extends Activity {
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        OverlayService.resumeAfterSleep(getApplicationContext());
        OverlayService.scheduleWatchdog(getApplicationContext());
        OverlayService.scheduleBootRetries(getApplicationContext());
        KeepAliveJob.schedule(getApplicationContext());
        finish();
    }
}
