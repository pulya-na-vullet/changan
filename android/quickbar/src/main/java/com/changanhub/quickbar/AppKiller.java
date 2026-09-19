package com.changanhub.quickbar;

import android.app.ActivityManager;
import android.app.usage.UsageStats;
import android.app.usage.UsageStatsManager;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.lang.reflect.Method;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * KillAPK-style closer for the Feiyu HU: list what is running, then force-stop
 * one package at a time. Normal apps cannot call {@code forceStopPackage};
 * Android 9 still allows {@link ActivityManager#killBackgroundProcesses}, then
 * {@code su -c am force-stop} / {@code sh -c am force-stop} like Wi-Fi.
 */
final class AppKiller {
    private static final Pattern PKG = Pattern.compile(
            "(?:cmp=|pkg=|processName=|ProcessRecord\\{[^ }]+ )([a-zA-Z][a-zA-Z0-9_]*+(?:\\.[a-zA-Z][a-zA-Z0-9_]*+)+)");
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

    static Set<String> runningPackages(Context context, String self) {
        LinkedHashSet<String> out = new LinkedHashSet<String>();
        addProcesses(context, out);
        addTasks(context, out);
        addRecentTasks(context, out);
        addUsage(context, out);
        addDump(out);
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
        boolean ok = false;
        ActivityManager am = (ActivityManager) context.getSystemService(Context.ACTIVITY_SERVICE);
        if (am != null) {
            try {
                am.killBackgroundProcesses(pkg);
                ok = true;
            } catch (Exception ignored) {
            }
            try {
                Method method = ActivityManager.class.getMethod("forceStopPackage", String.class);
                method.invoke(am, pkg);
                ok = true;
            } catch (Exception ignored) {
            }
        }
        String cmd = "am force-stop " + pkg;
        if (exec(new String[] {"su", "-c", cmd}) || exec(new String[] {"sh", "-c", cmd})) {
            return true;
        }
        String cmd2 = "cmd activity force-stop " + pkg;
        if (exec(new String[] {"su", "-c", cmd2}) || exec(new String[] {"sh", "-c", cmd2})) {
            return true;
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

    private static void addDump(Set<String> out) {
        parseDump(out, execOut("dumpsys activity recents"));
        parseDump(out, execOut("dumpsys activity activities"));
    }

    private static void parseDump(Set<String> out, String dump) {
        if (dump == null || dump.length() == 0) {
            return;
        }
        Matcher matcher = PKG.matcher(dump);
        while (matcher.find()) {
            addPkg(out, matcher.group(1));
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

    private static boolean exec(String[] argv) {
        Process process = null;
        try {
            process = Runtime.getRuntime().exec(argv);
            return process.waitFor() == 0;
        } catch (Exception ignored) {
            return false;
        } finally {
            if (process != null) {
                process.destroy();
            }
        }
    }

    private static String execOut(String cmd) {
        String viaSu = read(new String[] {"su", "-c", cmd});
        if (viaSu != null && viaSu.length() > 0) {
            return viaSu;
        }
        return read(new String[] {"sh", "-c", cmd});
    }

    private static String read(String[] argv) {
        Process process = null;
        try {
            process = Runtime.getRuntime().exec(argv);
            ByteArrayOutputStream buf = new ByteArrayOutputStream();
            InputStream in = process.getInputStream();
            byte[] chunk = new byte[4096];
            int n;
            int total = 0;
            while ((n = in.read(chunk)) > 0 && total < 200000) {
                buf.write(chunk, 0, n);
                total += n;
            }
            process.waitFor();
            return buf.toString("UTF-8");
        } catch (Exception e) {
            return "";
        } finally {
            if (process != null) {
                process.destroy();
            }
        }
    }
}
