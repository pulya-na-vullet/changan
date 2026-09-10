package com.changanhub.quickbar;

import android.accessibilityservice.AccessibilityService;
import android.view.accessibility.AccessibilityEvent;

/**
 * Feiyu starts enabled accessibility services after ACC even when it dropped
 * BOOT_COMPLETED and force-stopped the package. This service only wakes the
 * overlay — it does not read window content.
 */
public class KeepAliveAccessibility extends AccessibilityService {
    @Override
    protected void onServiceConnected() {
        super.onServiceConnected();
        OverlayService.resumeAfterSleep(this);
        OverlayService.scheduleWatchdog(this);
        OverlayService.scheduleBootRetries(this);
        KeepAliveJob.schedule(this);
        BootReceiver.startTrampoline(this);
    }

    @Override
    public void onAccessibilityEvent(AccessibilityEvent event) {
    }

    @Override
    public void onInterrupt() {
    }
}
