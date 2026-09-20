package com.changanhub.quickbar;

import android.app.ActivityManager;
import android.app.AppOpsManager;
import android.app.usage.UsageStats;
import android.app.usage.UsageStatsManager;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Process;
import android.provider.Settings;

import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * KillAPK-style closer: list running apps, then force-stop through the
 * accessibility service (system App Info → Force Stop). No {@code su}:
 * Feiyu's su binary flashes a 提示 / password toast and does not stop the app.
 */
final class AppKiller {
    private static final long RECENT_MS = 20L * 60L * 1000L;

    private AppKiller() {
    }

    static boolean isProtected(String pkg, String self) {
        if (pkg == null || pkg.length() == 0) {
            return true;
        }
        if (self != null && pkg.equals(self)) {
            return true;
        }
        if (pkg.equals("android") || pkg.equals("system") || pkg.equals("com.android.shell")) {
            return true;
        }
        if (pkg.startsWith("com.android.systemui")
                || pkg.startsWith("com.android.phone")
                || pkg.startsWith("com.android.bluetooth")
                || pkg.startsWith("com.android.nfc")
                || pkg.startsWith("com.android.providers")
                || pkg.contains("inputmethod")
                || pkg.contains("keyboard")) {
            return true;
        }
        if (pkg.contains("autofly.launcher")
                || pkg.equals("com.android.launcher")
                || pkg.equals("com.android.launcher3")) {
            return true;
        }
        if (pkg.startsWith("com.changanhub.qb")
                || pkg.equals("com.changanhub.quickbar")
                || pkg.equals("com.changanhub.quickdock")
                || pkg.equals("com.changanhub.quicklane")
                || pkg.equals("com.changanhub.quickkeep")
                || pkg.equals("com.changanhub.quickrise")
                || pkg.equals("com.changanhub.quickstash")
                || pkg.equals("com.changanhub.quickload")) {
            return true;
        }
        if (pkg.equals("com.syu.ms")
                || pkg.startsWith("com.fyt.ivoka")
                || pkg.equals("com.incall.apps.launcher")) {
            return true;
        }
        return false;
    }

    static boolean hasUsageAccess(Context context) {
        try {
            AppOpsManager appOps = (AppOpsManager) context.getSystemService(Context.APP_OPS_SERVICE);
            if (appOps == null) {
                return false;
            }
            int mode = appOps.checkOpNoThrow(
                    AppOpsManager.OPSTR_GET_USAGE_STATS,
                    Process.myUid(),
                    context.getPackageName());
            return mode == AppOpsManager.MODE_ALLOWED;
        } catch (Exception e) {
            return false;
        }
    }

    static boolean needsKillPermission(Context context) {
        return !KeepAliveAccessibility.isEnabled(context);
    }

    static void openKillPermissionSettings(Context context) {
        Intent intent;
        if (!KeepAliveAccessibility.isEnabled(context)) {
            intent = new Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS);
        } else {
            intent = new Intent(Settings.ACTION_USAGE_ACCESS_SETTINGS);
            intent.setData(Uri.parse("package:" + context.getPackageName()));
        }
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK
                | Intent.FLAG_ACTIVITY_NO_ANIMATION
                | Intent.FLAG_ACTIVITY_EXCLUDE_FROM_RECENTS);
        try {
            context.startActivity(intent);
        } catch (Exception e) {
            Intent fallback = new Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS);
            fallback.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            try {
                context.startActivity(fallback);
            } catch (Exception ignored) {
            }
        }
    }

    static Set<String> runningPackages(Context context, String self) {
        LinkedHashSet<String> out = new LinkedHashSet<String>();
        addProcesses(context, out);
        addTasks(context, out);
        addRecentTasks(context, out);
        addUsage(context, out);
        LinkedHashSet<String> filtered = new LinkedHashSet<String>();
        PackageManager pm = context.getPackageManager();
        for (String pkg : out) {
            if (isProtected(pkg, self)) {
                continue;
            }
            if (!launchable(pm, pkg)) {
                continue;
            }
            filtered.add(pkg);
        }
        return filtered;
    }

    static boolean forceStop(Context context, String pkg) {
        if (isProtected(pkg, context.getPackageName())) {
            return false;
        }
        boolean ok = KeepAliveAccessibility.forceStop(context, pkg, 12_000L);
        ActivityManager am = (ActivityManager) context.getSystemService(Context.ACTIVITY_SERVICE);
        if (am != null) {
            try {
                am.killBackgroundProcesses(pkg);
            } catch (Exception ignored) {
            }
        }
        return ok;
    }

    private static boolean launchable(PackageManager pm, String pkg) {
        try {
            Intent launch = pm.getLaunchIntentForPackage(pkg);
            return launch != null;
        } catch (Exception e) {
            return false;
        }
    }

    private static void addProcesses(Context context, Set<String> out) {
        try {
            ActivityManager am = (ActivityManager) context.getSystemService(Context.ACTIVITY_SERVICE);
            if (am == null) {
                return;
            }
            List<ActivityManager.RunningAppProcessInfo> list = am.getRunningAppProcesses();
            if (list == null) {
                return;
            }
            for (int i = 0; i < list.size(); i++) {
                ActivityManager.RunningAppProcessInfo info = list.get(i);
                if (info.pkgList == null) {
                    continue;
                }
                for (int j = 0; j < info.pkgList.length; j++) {
                    addPkg(out, info.pkgList[j]);
                }
            }
        } catch (Exception ignored) {
        }
    }

    @SuppressWarnings("deprecation")
    private static void addTasks(Context context, Set<String> out) {
        try {
            ActivityManager am = (ActivityManager) context.getSystemService(Context.ACTIVITY_SERVICE);
            if (am == null) {
                return;
            }
            List<ActivityManager.RunningTaskInfo> tasks = am.getRunningTasks(32);
            if (tasks == null) {
                return;
            }
            for (int i = 0; i < tasks.size(); i++) {
                addTask(out, tasks.get(i).baseActivity, tasks.get(i).topActivity);
            }
        } catch (Exception ignored) {
        }
    }

    @SuppressWarnings("deprecation")
    private static void addRecentTasks(Context context, Set<String> out) {
        try {
            ActivityManager am = (ActivityManager) context.getSystemService(Context.ACTIVITY_SERVICE);
            if (am == null) {
                return;
            }
            List<ActivityManager.RecentTaskInfo> tasks = am.getRecentTasks(32, 0);
            if (tasks == null) {
                return;
            }
            for (int i = 0; i < tasks.size(); i++) {
                ActivityManager.RecentTaskInfo info = tasks.get(i);
                if (info.baseIntent != null && info.baseIntent.getComponent() != null) {
                    addPkg(out, info.baseIntent.getComponent().getPackageName());
                }
                addTask(out, info.origActivity, info.topActivity);
            }
        } catch (Exception ignored) {
        }
    }

    private static void addUsage(Context context, Set<String> out) {
        try {
            UsageStatsManager usm = (UsageStatsManager) context.getSystemService(Context.USAGE_STATS_SERVICE);
            if (usm == null) {
                return;
            }
            long now = System.currentTimeMillis();
            Map<String, UsageStats> map = usm.queryAndAggregateUsageStats(now - RECENT_MS, now);
            if (map == null) {
                return;
            }
            for (UsageStats stats : map.values()) {
                if (stats.getLastTimeUsed() >= now - RECENT_MS) {
                    addPkg(out, stats.getPackageName());
                }
            }
        } catch (Exception ignored) {
        }
    }

    private static void addTask(Set<String> out, ComponentName a, ComponentName b) {
        if (a != null) {
            addPkg(out, a.getPackageName());
        }
        if (b != null) {
            addPkg(out, b.getPackageName());
        }
    }

    private static void addPkg(Set<String> out, String pkg) {
        if (pkg == null || pkg.indexOf('.') < 0) {
            return;
        }
        out.add(pkg);
    }
}
