package com.changanhub.quickbar;

import android.accessibilityservice.AccessibilityService;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.view.accessibility.AccessibilityEvent;
import android.view.accessibility.AccessibilityNodeInfo;
import android.view.accessibility.AccessibilityWindowInfo;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

/**
 * Wakes the overlay after ACC, and force-stops apps the way KillAPK does:
 * open the system app-info screen and click Force Stop / Остановить / 强行停止.
 */
public class KeepAliveAccessibility extends AccessibilityService {
    private static KeepAliveAccessibility instance;
    private static String pendingPkg;
    private static CountDownLatch latch;
    private static boolean awaitingConfirm;
    private static boolean success;

    private final Handler handler = new Handler(Looper.getMainLooper());
    private final Runnable scanRun = new Runnable() {
        @Override
        public void run() {
            tryClick();
        }
    };

    static boolean isEnabled(Context context) {
        if (instance != null) {
            return true;
        }
        try {
            int on = Settings.Secure.getInt(
                    context.getContentResolver(),
                    Settings.Secure.ACCESSIBILITY_ENABLED,
                    0);
            if (on == 0) {
                return false;
            }
            String enabled = Settings.Secure.getString(
                    context.getContentResolver(),
                    Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES);
            if (enabled == null || enabled.length() == 0) {
                return false;
            }
            ComponentName cn = new ComponentName(context, KeepAliveAccessibility.class);
            return enabled.contains(cn.flattenToString())
                    || enabled.contains(cn.flattenToShortString());
        } catch (Exception e) {
            return false;
        }
    }

    static boolean forceStop(Context context, String pkg, long timeoutMs) {
        KeepAliveAccessibility svc = instance;
        for (int i = 0; i < 20 && svc == null; i++) {
            try {
                Thread.sleep(100);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                return false;
            }
            svc = instance;
        }
        if (svc == null || pkg == null || pkg.length() == 0) {
            return false;
        }
        final KeepAliveAccessibility bound = svc;
        CountDownLatch done = new CountDownLatch(1);
        synchronized (KeepAliveAccessibility.class) {
            pendingPkg = pkg;
            awaitingConfirm = false;
            success = false;
            latch = done;
        }
        Intent intent = new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS);
        intent.setData(Uri.parse("package:" + pkg));
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK
                | Intent.FLAG_ACTIVITY_CLEAR_TOP
                | Intent.FLAG_ACTIVITY_NO_ANIMATION
                | Intent.FLAG_ACTIVITY_EXCLUDE_FROM_RECENTS);
        try {
            context.startActivity(intent);
        } catch (Exception e) {
            clearPending();
            return false;
        }
        bound.handler.removeCallbacks(bound.scanRun);
        bound.handler.postDelayed(bound.scanRun, 250);
        try {
            done.await(timeoutMs, TimeUnit.MILLISECONDS);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
        boolean ok;
        synchronized (KeepAliveAccessibility.class) {
            ok = success;
        }
        clearPending();
        bound.handler.removeCallbacks(bound.scanRun);
        bound.handler.post(new Runnable() {
            @Override
            public void run() {
                bound.performGlobalAction(GLOBAL_ACTION_BACK);
            }
        });
        return ok;
    }

    private static void clearPending() {
        synchronized (KeepAliveAccessibility.class) {
            pendingPkg = null;
            latch = null;
            awaitingConfirm = false;
        }
    }

    @Override
    protected void onServiceConnected() {
        super.onServiceConnected();
        instance = this;
        OverlayService.resumeAfterSleep(this);
        OverlayService.scheduleWatchdog(this);
        OverlayService.scheduleBootRetries(this);
        KeepAliveJob.schedule(this);
        BootReceiver.startTrampoline(this);
    }

    @Override
    public void onDestroy() {
        if (instance == this) {
            instance = null;
        }
        super.onDestroy();
    }

    @Override
    public void onAccessibilityEvent(AccessibilityEvent event) {
        String pkg;
        synchronized (KeepAliveAccessibility.class) {
            pkg = pendingPkg;
        }
        if (pkg == null) {
            return;
        }
        handler.removeCallbacks(scanRun);
        handler.postDelayed(scanRun, 80);
    }

    @Override
    public void onInterrupt() {
    }

    private void tryClick() {
        String pkg;
        synchronized (KeepAliveAccessibility.class) {
            pkg = pendingPkg;
        }
        if (pkg == null) {
            return;
        }
        List<AccessibilityNodeInfo> roots = collectRoots();
        try {
            for (int i = 0; i < roots.size(); i++) {
                if (scan(roots.get(i))) {
                    return;
                }
            }
        } finally {
            for (int i = 0; i < roots.size(); i++) {
                try {
                    roots.get(i).recycle();
                } catch (Exception ignored) {
                }
            }
        }
    }

    private List<AccessibilityNodeInfo> collectRoots() {
        ArrayList<AccessibilityNodeInfo> roots = new ArrayList<AccessibilityNodeInfo>();
        List<AccessibilityWindowInfo> windows = getWindows();
        if (windows != null) {
            for (int i = 0; i < windows.size(); i++) {
                AccessibilityWindowInfo window = windows.get(i);
                if (window == null) {
                    continue;
                }
                AccessibilityNodeInfo root = window.getRoot();
                if (root == null) {
                    continue;
                }
                CharSequence wp = root.getPackageName();
                if (wp != null && getPackageName().equals(wp.toString())) {
                    root.recycle();
                    continue;
                }
                roots.add(root);
            }
        }
        if (roots.isEmpty()) {
            AccessibilityNodeInfo active = getRootInActiveWindow();
            if (active != null) {
                roots.add(active);
            }
        }
        return roots;
    }

    private boolean scan(AccessibilityNodeInfo root) {
        if (root == null) {
            return false;
        }
        boolean confirm;
        synchronized (KeepAliveAccessibility.class) {
            confirm = awaitingConfirm;
        }
        if (!confirm) {
            if (clickForceStop(root)) {
                return true;
            }
            if (forceStopDisabled(root)) {
                finishOk();
                return true;
            }
            return false;
        }
        return clickConfirm(root);
    }

    private boolean clickForceStop(AccessibilityNodeInfo root) {
        if (clickById(root, "com.android.settings:id/force_stop_button", false)
                || clickById(root, "com.android.settings:id/right_button", false)
                || clickById(root, "com.android.settings:id/left_button", false)) {
            markConfirm();
            return true;
        }
        if (isForceStopLabel(root.getText()) || isForceStopLabel(root.getContentDescription())) {
            if (!root.isEnabled()) {
                finishOk();
                return true;
            }
            if (click(root)) {
                markConfirm();
                return true;
            }
        }
        ArrayList<AccessibilityNodeInfo> nodes = new ArrayList<AccessibilityNodeInfo>();
        collect(root, nodes);
        for (int i = 0; i < nodes.size(); i++) {
            AccessibilityNodeInfo node = nodes.get(i);
            if (isForceStopLabel(node.getText()) || isForceStopLabel(node.getContentDescription())) {
                if (!node.isEnabled()) {
                    recycleAll(nodes);
                    finishOk();
                    return true;
                }
                if (click(node)) {
                    recycleAll(nodes);
                    markConfirm();
                    return true;
                }
            }
        }
        recycleAll(nodes);
        return false;
    }

    private boolean forceStopDisabled(AccessibilityNodeInfo root) {
        ArrayList<AccessibilityNodeInfo> nodes = new ArrayList<AccessibilityNodeInfo>();
        collect(root, nodes);
        try {
            for (int i = 0; i < nodes.size(); i++) {
                AccessibilityNodeInfo node = nodes.get(i);
                if ((isForceStopLabel(node.getText()) || isForceStopLabel(node.getContentDescription()))
                        && !node.isEnabled()) {
                    return true;
                }
            }
            return false;
        } finally {
            recycleAll(nodes);
        }
    }

    private boolean clickConfirm(AccessibilityNodeInfo root) {
        if (clickById(root, "android:id/button1", true)) {
            finishOk();
            return true;
        }
        ArrayList<AccessibilityNodeInfo> nodes = new ArrayList<AccessibilityNodeInfo>();
        collect(root, nodes);
        for (int i = 0; i < nodes.size(); i++) {
            AccessibilityNodeInfo node = nodes.get(i);
            if (isConfirmLabel(node.getText()) || isConfirmLabel(node.getContentDescription())) {
                if (click(node)) {
                    recycleAll(nodes);
                    finishOk();
                    return true;
                }
            }
        }
        recycleAll(nodes);
        return false;
    }

    private boolean clickById(AccessibilityNodeInfo root, String viewId, boolean confirmOnly) {
        List<AccessibilityNodeInfo> found;
        try {
            found = root.findAccessibilityNodeInfosByViewId(viewId);
        } catch (Exception e) {
            return false;
        }
        if (found == null) {
            return false;
        }
        boolean clicked = false;
        for (int i = 0; i < found.size(); i++) {
            AccessibilityNodeInfo node = found.get(i);
            if (node == null) {
                continue;
            }
            CharSequence label = node.getText();
            if (label == null) {
                label = node.getContentDescription();
            }
            if (isCancelLabel(label)) {
                continue;
            }
            if (confirmOnly && isUninstallLabel(label)) {
                continue;
            }
            if (!confirmOnly && isUninstallLabel(label) && !isForceStopLabel(label)) {
                continue;
            }
            if (node.isEnabled() && click(node)) {
                clicked = true;
            }
        }
        recycleAll(found);
        return clicked;
    }

    private static void markConfirm() {
        synchronized (KeepAliveAccessibility.class) {
            awaitingConfirm = true;
        }
    }

    private void finishOk() {
        CountDownLatch done;
        synchronized (KeepAliveAccessibility.class) {
            success = true;
            done = latch;
            pendingPkg = null;
            latch = null;
        }
        if (done != null) {
            done.countDown();
        }
    }

    private static boolean click(AccessibilityNodeInfo node) {
        AccessibilityNodeInfo cur = node;
        for (int depth = 0; depth < 6 && cur != null; depth++) {
            if (cur.isClickable() || cur.isEnabled()) {
                if (cur.performAction(AccessibilityNodeInfo.ACTION_CLICK)) {
                    return true;
                }
            }
            AccessibilityNodeInfo parent = cur.getParent();
            if (cur != node) {
                try {
                    cur.recycle();
                } catch (Exception ignored) {
                }
            }
            cur = parent;
        }
        if (cur != null && cur != node) {
            try {
                cur.recycle();
            } catch (Exception ignored) {
            }
        }
        return node.performAction(AccessibilityNodeInfo.ACTION_CLICK);
    }

    private static void collect(AccessibilityNodeInfo node, List<AccessibilityNodeInfo> out) {
        if (node == null) {
            return;
        }
        int n = node.getChildCount();
        for (int i = 0; i < n; i++) {
            AccessibilityNodeInfo child;
            try {
                child = node.getChild(i);
            } catch (Exception e) {
                continue;
            }
            if (child != null) {
                out.add(child);
                collect(child, out);
            }
        }
    }

    private static void recycleAll(List<AccessibilityNodeInfo> nodes) {
        for (int i = 0; i < nodes.size(); i++) {
            AccessibilityNodeInfo node = nodes.get(i);
            if (node == null) {
                continue;
            }
            try {
                node.recycle();
            } catch (Exception ignored) {
            }
        }
    }

    static boolean isForceStopLabel(CharSequence raw) {
        if (raw == null) {
            return false;
        }
        String t = raw.toString().trim().toLowerCase(Locale.ROOT);
        if (t.length() == 0 || isUninstallLabel(raw) || isCancelLabel(raw)) {
            return false;
        }
        if (t.contains("force stop")
                || t.contains("force-stop")
                || t.contains("forcibly stop")
                || t.contains("принудител")
                || t.contains("强行停止")
                || t.contains("强制停止")
                || t.contains("强制关闭")) {
            return true;
        }
        return t.equals("остановить") || t.equals("stop");
    }

    static boolean isConfirmLabel(CharSequence raw) {
        if (raw == null) {
            return false;
        }
        String t = raw.toString().trim().toLowerCase(Locale.ROOT);
        if (t.length() == 0 || isCancelLabel(raw) || isUninstallLabel(raw)) {
            return false;
        }
        if (isForceStopLabel(raw)) {
            return true;
        }
        return t.equals("ok")
                || t.equals("ок")
                || t.equals("okay")
                || t.equals("да")
                || t.equals("yes")
                || t.equals("确定")
                || t.equals("好");
    }

    static boolean isCancelLabel(CharSequence raw) {
        if (raw == null) {
            return false;
        }
        String t = raw.toString().trim().toLowerCase(Locale.ROOT);
        return t.contains("cancel")
                || t.contains("отмен")
                || t.contains("取消")
                || t.equals("нет")
                || t.equals("no");
    }

    static boolean isUninstallLabel(CharSequence raw) {
        if (raw == null) {
            return false;
        }
        String t = raw.toString().trim().toLowerCase(Locale.ROOT);
        return t.contains("uninstall")
                || t.contains("удал")
                || t.contains("卸载")
                || t.contains("disable")
                || t.contains("отключ");
    }
}
