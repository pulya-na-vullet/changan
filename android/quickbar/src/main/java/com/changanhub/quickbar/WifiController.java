package com.changanhub.quickbar;

import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.wifi.WifiManager;
import android.provider.Settings;

/**
 * Wi-Fi toggle for the Feiyu HU. Same idea as changan_wifi, without a second
 * floating overlay: {@link WifiManager#setWifiEnabled} on Android 9, then
 * {@code su -c svc wifi} if the firmware blocks the API.
 */
final class WifiController {
    private static final String[] SETTINGS_ACTIONS = {
            "android.settings.panel.action.WIFI",
            Settings.ACTION_WIFI_SETTINGS,
            Settings.ACTION_WIRELESS_SETTINGS,
            Settings.ACTION_SETTINGS,
    };
    private static final String[] SETTINGS_COMPONENTS = {
            "com.android.settings/com.android.settings.wifi.WifiSettings",
            "com.android.settings/com.android.settings.WifiSettings",
            "com.android.settings/com.android.settings.wifi.WifiPickerActivity",
            "com.android.settings/com.android.settings.wifi.WifiEnablerActivity",
            "com.android.settings/com.android.settings.Settings$WifiSettingsActivity",
    };

    private WifiController() {
    }

    static boolean isOn(Context context) {
        WifiManager wm = wifi(context);
        return wm != null && wm.isWifiEnabled();
    }

    /**
     * Same order as changan_wifi: {@code WifiManager.setWifiEnabled} on
     * targetSdk 28, then {@code su -c svc wifi} if the radio did not move.
     *
     * @return true if the radio ended in the requested state.
     */
    @SuppressWarnings("deprecation")
    static boolean setEnabled(Context context, boolean on) {
        WifiManager wm = wifi(context);
        boolean accepted = false;
        if (wm != null) {
            try {
                accepted = wm.setWifiEnabled(on);
            } catch (Exception ignored) {
            }
        }
        if (waitFor(context, on, accepted ? 1600 : 400)) {
            return true;
        }
        if (rootWifi(on) && waitFor(context, on, 1600)) {
            return true;
        }
        return isOn(context) == on;
    }

    static boolean toggle(Context context) {
        return setEnabled(context, !isOn(context));
    }

    static Intent settingsIntent(Context context) {
        PackageManager pm = context.getPackageManager();
        for (int i = 0; i < SETTINGS_ACTIONS.length; i++) {
            Intent intent = new Intent(SETTINGS_ACTIONS[i]);
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            if (resolves(pm, intent)) {
                return intent;
            }
        }
        for (int i = 0; i < SETTINGS_COMPONENTS.length; i++) {
            String[] parts = SETTINGS_COMPONENTS[i].split("/", 2);
            Intent intent = new Intent();
            intent.setClassName(parts[0], parts[1]);
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            if (resolves(pm, intent)) {
                return intent;
            }
        }
        Intent fallback = new Intent(Settings.ACTION_WIFI_SETTINGS);
        fallback.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        return fallback;
    }

    private static boolean resolves(PackageManager pm, Intent intent) {
        try {
            return pm.resolveActivity(intent, 0) != null;
        } catch (Exception e) {
            return false;
        }
    }

    private static WifiManager wifi(Context context) {
        try {
            return (WifiManager) context.getApplicationContext().getSystemService(Context.WIFI_SERVICE);
        } catch (Exception e) {
            return null;
        }
    }

    private static boolean rootWifi(boolean on) {
        String cmd = on ? "svc wifi enable" : "svc wifi disable";
        return exec(new String[] {"su", "-c", cmd}) || exec(new String[] {"sh", "-c", cmd});
    }

    private static boolean exec(String[] argv) {
        Process process = null;
        try {
            process = Runtime.getRuntime().exec(argv);
            if (process.waitFor() == 0) {
                return true;
            }
        } catch (Exception ignored) {
        } finally {
            if (process != null) {
                process.destroy();
            }
        }
        return false;
    }

    private static boolean waitFor(Context context, boolean on, int timeoutMs) {
        long end = System.currentTimeMillis() + timeoutMs;
        while (System.currentTimeMillis() < end) {
            if (isOn(context) == on) {
                return true;
            }
            try {
                Thread.sleep(120);
            } catch (InterruptedException e) {
                return isOn(context) == on;
            }
        }
        return isOn(context) == on;
    }
}
