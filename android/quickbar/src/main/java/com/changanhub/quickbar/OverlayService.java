package com.changanhub.quickbar;

import android.app.ActivityManager;
import android.app.AlarmManager;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.app.usage.UsageStats;
import android.app.usage.UsageStatsManager;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.SharedPreferences;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageManager;
import android.content.pm.ResolveInfo;
import android.graphics.Color;
import android.graphics.PixelFormat;
import android.graphics.Rect;
import android.graphics.Typeface;
import android.graphics.drawable.Drawable;
import android.graphics.drawable.GradientDrawable;
import android.os.Build;
import android.os.IBinder;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.util.DisplayMetrics;
import android.view.Display;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowManager;
import android.view.inputmethod.InputMethodManager;
import android.widget.EditText;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import java.io.File;
import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.HashSet;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;

/**
 * Persistent right-edge launcher dock for Changan portrait head units.
 * Stays above every activity via SYSTEM_ALERT_WINDOW.
 */
public class OverlayService extends Service {
    public static final String ACTION_SHOW = "com.changanhub.quickbar.SHOW";
    public static final String ACTION_HIDE = "com.changanhub.quickbar.HIDE";
    public static final String ACTION_TOGGLE = "com.changanhub.quickbar.TOGGLE";
    public static final String ACTION_REFRESH = "com.changanhub.quickbar.REFRESH";
    public static final String ACTION_KEEPALIVE = "com.changanhub.quickbar.KEEPALIVE";
    public static final String ACTION_PAUSE = "com.changanhub.quickbar.PAUSE";
    /** Recreate WindowManager views after ACC: process can survive while surfaces die. */
    public static final String ACTION_RESUME = "com.changanhub.quickbar.RESUME";
    /**
     * Previous applicationIds. Feiyu forbids deleting an auth package, so each
     * incompatible re-sign ships a new id and Hub disables the old ones.
     */
    public static final String[] LEGACY_PACKAGES = {
            "com.changanhub.quickbar",
            "com.changanhub.quickdock",
            "com.changanhub.quicklane",
    };
    public static final String LEGACY_PACKAGE = LEGACY_PACKAGES[0];

    /** Vertical UI is 3× the original dp so tap targets match a 13.2″ HU. */
    public static final int HEIGHT_SCALE = 3;
    private static final int ICON_DP = 48 * HEIGHT_SCALE;
    private static final int ROW_PAD_V_DP = 8 * HEIGHT_SCALE;
    /**
     * Top/bottom fifths stay clear. Collapsed mode uses two windows with at least
     * this much empty screen between them so Yandex Navigator keeps its right-side taps.
     */
    private static final float VERTICAL_MARGIN = 0.20f;

    private static final String CH = "quickbar";
    private static final String PREFS = "quickbar";
    private static final String KEY_FAV = "favorites";
    private static final String KEY_HIDDEN = "hidden";
    private static final String KEY_COLLAPSED = "collapsed";
    private static final String KEY_WIDE = "wide";
    private static final String KEY_RECENT = "recent";
    private static final int RECENT_MAX = 3;
    private static final int COLLAPSED_W_DP = 64;
    private static final int COLLAPSED_ICON_DP = 36;
    private static final int WATCHDOG_REQ = 7;
    private static final long WATCHDOG_MS = 20_000L;
    private static final int[] BOOT_RETRY_SEC = {3, 10, 30, 60, 120};

    private WindowManager windowManager;
    private View root;
    private View dockMenu;
    private View dockRecent;
    private View peekView;
    private WindowManager.LayoutParams params;
    private WindowManager.LayoutParams menuParams;
    private WindowManager.LayoutParams recentParams;
    private WindowManager.LayoutParams peekParams;
    private LinearLayout appList;
    private LinearLayout tools;
    private EditText search;
    private TextView titleView;
    private TextView usbStatus;
    private boolean collapsed;
    private boolean wide;
    private boolean usbMode;
    private boolean keyboardPeek;
    private boolean collapsedBeforePeek;
    /** After the user opens the bar while IME is up, do not peek again until IME hides. */
    private boolean ignoreImePeek;
    private long overlayPausedUntil;
    private long lastReattachElapsed;
    private View usbToggle;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private List<AppItem> apps = new ArrayList<>();
    private String query = "";
    /** Package waiting for hide/unhide confirm (checkmark / close). */
    private String pendingHidePkg;
    private BroadcastReceiver lifeReceiver;

    private final Runnable attachWatch = new Runnable() {
        @Override
        public void run() {
        if (SystemClock.elapsedRealtime() >= overlayPausedUntil && !hasOverlay()) {
            attachOverlay();
        }
        handler.postDelayed(this, 15_000);
        }
    };

    private final Runnable imeWatch = new Runnable() {
        @Override
        public void run() {
            syncKeyboardPeek();
            handler.postDelayed(this, 400);
        }
    };

    public static void start(Context context) {
        launch(context, ACTION_SHOW);
    }

    public static void keepAlive(Context context) {
        launch(context, ACTION_KEEPALIVE);
    }

    public static void resumeAfterSleep(Context context) {
        launch(context, ACTION_RESUME);
    }

    public static void pauseForDialog(Context context) {
        launch(context, ACTION_PAUSE);
    }

    private static void launch(Context context, String action) {
        Intent intent = new Intent(context, OverlayService.class);
        intent.setAction(action);
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(intent);
            } else {
                context.startService(intent);
            }
        } catch (Exception foregroundDenied) {
            try {
                context.startService(intent);
            } catch (Exception ignored) {
            }
        }
    }

    public static void scheduleWatchdog(Context context) {
        Context app = context.getApplicationContext();
        AlarmManager am = (AlarmManager) app.getSystemService(Context.ALARM_SERVICE);
        if (am == null) {
            return;
        }
        Intent intent = new Intent(app, WatchdogReceiver.class);
        intent.setAction(ACTION_KEEPALIVE);
        PendingIntent pi = pending(app, WATCHDOG_REQ, intent);
        long elapsedAt = SystemClock.elapsedRealtime() + WATCHDOG_MS;
        long rtcAt = System.currentTimeMillis() + WATCHDOG_MS;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            am.setExactAndAllowWhileIdle(AlarmManager.ELAPSED_REALTIME_WAKEUP, elapsedAt, pi);
            PendingIntent rtc = pending(app, WATCHDOG_REQ + 1, intent);
            am.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, rtcAt, rtc);
        } else {
            am.set(AlarmManager.ELAPSED_REALTIME_WAKEUP, elapsedAt, pi);
        }
    }

    public static void scheduleBootRetries(Context context) {
        Context app = context.getApplicationContext();
        AlarmManager am = (AlarmManager) app.getSystemService(Context.ALARM_SERVICE);
        if (am == null) {
            return;
        }
        for (int i = 0; i < BOOT_RETRY_SEC.length; i++) {
            Intent intent = new Intent(app, WatchdogReceiver.class);
            intent.setAction(ACTION_KEEPALIVE);
            PendingIntent elapsedPi = pending(app, 100 + i, intent);
            PendingIntent rtcPi = pending(app, 200 + i, intent);
            long elapsedAt = SystemClock.elapsedRealtime() + BOOT_RETRY_SEC[i] * 1000L;
            long rtcAt = System.currentTimeMillis() + BOOT_RETRY_SEC[i] * 1000L;
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                am.setExactAndAllowWhileIdle(AlarmManager.ELAPSED_REALTIME_WAKEUP, elapsedAt, elapsedPi);
                am.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, rtcAt, rtcPi);
            } else {
                am.set(AlarmManager.ELAPSED_REALTIME_WAKEUP, elapsedAt, elapsedPi);
                am.set(AlarmManager.RTC_WAKEUP, rtcAt, rtcPi);
            }
        }
    }

    private static PendingIntent pending(Context context, int requestCode, Intent intent) {
        int flags = PendingIntent.FLAG_UPDATE_CURRENT;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            flags |= PendingIntent.FLAG_IMMUTABLE;
        }
        return PendingIntent.getBroadcast(context, requestCode, intent, flags);
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    @Override
    public void onCreate() {
        super.onCreate();
        SharedPreferences p = getSharedPreferences(PREFS, MODE_PRIVATE);
        collapsed = p.getBoolean(KEY_COLLAPSED, false);
        wide = true;
        startInForeground();
        registerLifeReceiver();
        scheduleWatchdog(this);
        KeepAliveJob.schedule(this);
        suppressLegacy();
        attachOverlay();
        handler.postDelayed(attachWatch, 15_000);
        handler.postDelayed(imeWatch, 400);
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        startInForeground();
        scheduleWatchdog(this);
        KeepAliveJob.schedule(this);
        String action = intent != null ? intent.getAction() : ACTION_SHOW;
        if (ACTION_HIDE.equals(action)) {
            detachOverlay();
            return START_STICKY;
        }
        if (ACTION_RESUME.equals(action)) {
            reattachOverlay();
            suppressLegacy();
            return START_STICKY;
        }
        if (!hasOverlay()) {
            attachOverlay();
        }
        suppressLegacy();
        if (ACTION_PAUSE.equals(action)) {
            overlayPausedUntil = SystemClock.elapsedRealtime() + 90_000L;
            setCollapsed(true);
            return START_STICKY;
        }
        if (ACTION_KEEPALIVE.equals(action)
                || (ACTION_SHOW.equals(action)
                        && SystemClock.elapsedRealtime() < overlayPausedUntil)) {
            return START_STICKY;
        }
        if (ACTION_TOGGLE.equals(action)) {
            setCollapsed(!collapsed);
        } else if (ACTION_REFRESH.equals(action)) {
            reloadApps();
        } else {
            if (collapsed) {
                setCollapsed(false);
            }
            reloadApps();
        }
        return START_STICKY;
    }

    @Override
    public void onDestroy() {
        handler.removeCallbacks(attachWatch);
        handler.removeCallbacks(imeWatch);
        unregisterLifeReceiver();
        detachOverlay();
        super.onDestroy();
        scheduleWatchdog(getApplicationContext());
        handler.postDelayed(new Runnable() {
            @Override
            public void run() {
                keepAlive(getApplicationContext());
            }
        }, 800);
    }

    private void registerLifeReceiver() {
        if (lifeReceiver != null) {
            return;
        }
        lifeReceiver = new BroadcastReceiver() {
            @Override
            public void onReceive(Context context, Intent intent) {
                reattachOverlay();
            }
        };
        IntentFilter filter = new IntentFilter();
        filter.addAction(Intent.ACTION_SCREEN_ON);
        filter.addAction(Intent.ACTION_USER_PRESENT);
        filter.addAction(Intent.ACTION_POWER_CONNECTED);
        filter.addAction(Intent.ACTION_USER_UNLOCKED);
        filter.addAction(Intent.ACTION_BOOT_COMPLETED);
        filter.addAction("com.fyt.boot.ACCON");
        filter.addAction("com.incall.intent.action.ACC_ON");
        filter.addAction("android.intent.action.ACC_ON");
        registerReceiver(lifeReceiver, filter);
    }

    private void unregisterLifeReceiver() {
        if (lifeReceiver == null) {
            return;
        }
        try {
            unregisterReceiver(lifeReceiver);
        } catch (Exception ignored) {
        }
        lifeReceiver = null;
    }

    private void startInForeground() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel channel = new NotificationChannel(
                    CH, "QuickBar", NotificationManager.IMPORTANCE_MIN);
            channel.setShowBadge(false);
            channel.enableLights(false);
            channel.enableVibration(false);
            NotificationManager nm = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
            if (nm != null) {
                nm.createNotificationChannel(channel);
            }
        }
        Intent launch = new Intent(this, OverlayService.class);
        launch.setAction(ACTION_KEEPALIVE);
        int piFlags = PendingIntent.FLAG_UPDATE_CURRENT;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            piFlags |= PendingIntent.FLAG_IMMUTABLE;
        }
        PendingIntent pi = PendingIntent.getService(this, 0, launch, piFlags);
        Notification.Builder b;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            b = new Notification.Builder(this, CH);
        } else {
            b = new Notification.Builder(this);
        }
        Notification n = b
                .setContentTitle("QuickBar")
                .setContentText(getString(R.string.overlay_notification))
                .setSmallIcon(android.R.drawable.ic_media_play)
                .setContentIntent(pi)
                .setOngoing(true)
                .setPriority(Notification.PRIORITY_MIN)
                .build();
        startForeground(7, n);
    }

    private void attachOverlay() {
        windowManager = (WindowManager) getSystemService(WINDOW_SERVICE);
        relayout();
        reloadApps();
    }

    private void reattachOverlay() {
        long now = SystemClock.elapsedRealtime();
        if (now - lastReattachElapsed < 2500L) {
            return;
        }
        lastReattachElapsed = now;
        detachOverlay();
        attachOverlay();
    }

    private boolean hasOverlay() {
        return root != null || dockMenu != null || dockRecent != null || peekView != null;
    }

    private void relayout() {
        if (windowManager == null) {
            windowManager = (WindowManager) getSystemService(WINDOW_SERVICE);
        }
        if (keyboardPeek) {
            removeView(root);
            root = null;
            removeView(dockMenu);
            dockMenu = null;
            removeView(dockRecent);
            dockRecent = null;
            if (peekView == null) {
                peekView = buildPeekButton();
                peekParams = addOverlay(peekView, dp(COLLAPSED_W_DP), dp(56), overlayTop());
            } else {
                applyChip(peekView, peekParams, dp(COLLAPSED_W_DP), dp(56), overlayTop());
            }
            return;
        }
        removeView(peekView);
        peekView = null;
        if (collapsed) {
            removeView(root);
            root = null;
            int menuH = collapsedMenuHeight();
            int recentH = collapsedRecentHeight();
            int topY = collapsedMenuY();
            int bottomY = collapsedRecentY(recentH);
            if (dockMenu == null) {
                dockMenu = wrapChip(collapseZone(R.drawable.ic_menu, new View.OnClickListener() {
                    @Override
                    public void onClick(View v) {
                        expandToFull();
                    }
                }));
                menuParams = addOverlay(dockMenu, dp(COLLAPSED_W_DP), menuH, topY);
            } else {
                applyChip(dockMenu, menuParams, dp(COLLAPSED_W_DP), menuH, topY);
            }
            if (dockRecent == null) {
                dockRecent = wrapChip(recentZone());
                recentParams = addOverlay(dockRecent, dp(COLLAPSED_W_DP), recentH, bottomY);
            } else {
                applyChip(dockRecent, recentParams, dp(COLLAPSED_W_DP), recentH, bottomY);
            }
            return;
        }
        removeView(dockMenu);
        dockMenu = null;
        removeView(dockRecent);
        dockRecent = null;
        if (root == null) {
            root = buildView();
            params = addOverlay(root, dp(380), overlayHeight(), overlayTop());
        }
        applySize();
        refreshChrome();
    }

    private View wrapChip(View inner) {
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setGravity(Gravity.CENTER);
        box.setBackground(panelBackground(true));
        box.setPadding(dp(2), dp(4), dp(2), dp(4));
        box.addView(inner, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        return box;
    }

    private View buildPeekButton() {
        LinearLayout box = new LinearLayout(this);
        box.setGravity(Gravity.CENTER);
        box.setBackground(panelBackground(true));
        ImageView image = new ImageView(this);
        image.setImageResource(R.drawable.ic_logo);
        image.setColorFilter(Color.parseColor("#CC3DDC97"));
        box.addView(image, new LinearLayout.LayoutParams(dp(COLLAPSED_ICON_DP), dp(COLLAPSED_ICON_DP)));
        box.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                ignoreImePeek = true;
                keyboardPeek = false;
                expandToFull();
            }
        });
        return box;
    }

    private WindowManager.LayoutParams addOverlay(View view, int width, int height, int y) {
        int[] types = overlayTypes();
        Exception last = null;
        for (int i = 0; i < types.length; i++) {
            WindowManager.LayoutParams lp = chipParams(types[i], width, height, y);
            try {
                windowManager.addView(view, lp);
                return lp;
            } catch (Exception e) {
                last = e;
                removeView(view);
            }
        }
        if (last != null) {
            last.printStackTrace();
        }
        return chipParams(types[0], width, height, y);
    }

    private WindowManager.LayoutParams chipParams(int type, int width, int height, int y) {
        WindowManager.LayoutParams lp = new WindowManager.LayoutParams(
                width,
                height,
                type,
                WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE
                        | WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN
                        | WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL
                        | WindowManager.LayoutParams.FLAG_HARDWARE_ACCELERATED,
                PixelFormat.TRANSLUCENT);
        lp.gravity = Gravity.END | Gravity.TOP;
        lp.x = 0;
        lp.y = y;
        return lp;
    }

    private void applyChip(View view, WindowManager.LayoutParams lp, int width, int height, int y) {
        if (view == null || lp == null || windowManager == null) {
            return;
        }
        lp.width = width;
        lp.height = height;
        lp.y = y;
        try {
            windowManager.updateViewLayout(view, lp);
        } catch (Exception ignored) {
        }
    }

    private void removeView(View view) {
        if (view == null || windowManager == null) {
            return;
        }
        try {
            windowManager.removeView(view);
        } catch (Exception ignored) {
        }
    }

    private int[] overlayTypes() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            return new int[] {
                    WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
                    WindowManager.LayoutParams.TYPE_PHONE,
                    WindowManager.LayoutParams.TYPE_SYSTEM_ALERT,
                    WindowManager.LayoutParams.TYPE_TOAST
            };
        }
        return new int[] {
                WindowManager.LayoutParams.TYPE_PHONE,
                WindowManager.LayoutParams.TYPE_SYSTEM_ALERT,
                WindowManager.LayoutParams.TYPE_SYSTEM_OVERLAY,
                WindowManager.LayoutParams.TYPE_TOAST
        };
    }

    private void detachOverlay() {
        removeView(root);
        root = null;
        removeView(dockMenu);
        dockMenu = null;
        removeView(dockRecent);
        dockRecent = null;
        removeView(peekView);
        peekView = null;
    }

    private void applySize() {
        if (keyboardPeek || collapsed) {
            relayout();
            return;
        }
        if (params == null || windowManager == null || root == null) {
            relayout();
            return;
        }
        params.width = dp(380);
        params.height = overlayHeight();
        params.y = overlayTop();
        params.gravity = Gravity.END | Gravity.TOP;
        try {
            windowManager.updateViewLayout(root, params);
        } catch (Exception ignored) {
        }
        refreshChrome();
    }

    /** Middle 60% of the screen — do not cover the top/bottom 20%. */
    private int overlayHeight() {
        int screen = displayHeight();
        int height = Math.round(screen * (1f - 2f * VERTICAL_MARGIN));
        return Math.max(dp(280), height);
    }

    private int overlayTop() {
        return Math.round(displayHeight() * VERTICAL_MARGIN);
    }

    private int collapsedMenuHeight() {
        return dp(56);
    }

    private int collapsedRecentHeight() {
        return dp(COLLAPSED_ICON_DP) * RECENT_MAX + dp(28);
    }

    private int collapsedMenuY() {
        return overlayTop();
    }

    /**
     * Recents chip sits above the bottom 20%. The hole between the two chips is a
     * real gap with no WindowManager view, so navigator buttons receive taps.
     */
    private int collapsedRecentY(int recentH) {
        int screen = displayHeight();
        int gap = overlayTop();
        int y = screen - gap - recentH;
        int minY = collapsedMenuY() + collapsedMenuHeight() + gap;
        return Math.max(y, minY);
    }

    private void syncKeyboardPeek() {
        if (SystemClock.elapsedRealtime() < overlayPausedUntil) {
            return;
        }
        boolean typingHere = search != null && search.hasFocus();
        boolean open = !typingHere && imeHeight() > dp(80);
        if (!open) {
            ignoreImePeek = false;
        }
        if (open && ignoreImePeek) {
            return;
        }
        if (open == keyboardPeek) {
            return;
        }
        if (open) {
            collapsedBeforePeek = collapsed;
            keyboardPeek = true;
        } else {
            keyboardPeek = false;
            collapsed = collapsedBeforePeek;
        }
        relayout();
        if (!keyboardPeek && !collapsed) {
            reloadApps();
        }
    }

    private int imeHeight() {
        try {
            InputMethodManager imm = (InputMethodManager) getSystemService(INPUT_METHOD_SERVICE);
            Method method = InputMethodManager.class.getMethod("getInputMethodWindowVisibleHeight");
            Object value = method.invoke(imm);
            if (value instanceof Integer) {
                int height = ((Integer) value).intValue();
                if (height > dp(80)) {
                    return height;
                }
            }
        } catch (Exception ignored) {
        }
        try {
            Rect visible = new Rect();
            View sample = peekView != null ? peekView : (root != null ? root : dockMenu);
            if (sample != null) {
                sample.getWindowVisibleDisplayFrame(visible);
                int screen = displayHeight();
                int covered = screen - visible.bottom;
                // Ignore the nav bar; a real IME covers a chunk of the screen.
                if (visible.bottom > 0 && covered > Math.round(screen * 0.12f)) {
                    return covered;
                }
            }
        } catch (Exception ignored) {
        }
        return 0;
    }

    private int displayHeight() {
        DisplayMetrics metrics = new DisplayMetrics();
        WindowManager wm = windowManager;
        if (wm == null) {
            wm = (WindowManager) getSystemService(WINDOW_SERVICE);
        }
        if (wm != null) {
            Display display = wm.getDefaultDisplay();
            if (display != null) {
                display.getRealMetrics(metrics);
                if (metrics.heightPixels > 0) {
                    return metrics.heightPixels;
                }
            }
        }
        return getResources().getDisplayMetrics().heightPixels;
    }

    private View buildView() {
        LinearLayout panel = new LinearLayout(this);
        panel.setOrientation(LinearLayout.VERTICAL);
        panel.setBackground(panelBackground(false));
        panel.setPadding(dp(6), dp(8), dp(6), dp(8));

        titleView = new TextView(this);
        titleView.setText(R.string.app_name);
        titleView.setTextColor(Color.parseColor("#3DDC97"));
        titleView.setTextSize(18);
        titleView.setTypeface(Typeface.DEFAULT_BOLD);
        titleView.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams titleLp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        titleLp.bottomMargin = dp(8);
        panel.addView(titleView, titleLp);

        tools = new LinearLayout(this);
        tools.setOrientation(LinearLayout.HORIZONTAL);
        tools.setGravity(Gravity.CENTER);
        tools.addView(toolIcon(R.drawable.ic_collapse, new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                setCollapsed(true);
            }
        }));
        tools.addView(toolIcon(R.drawable.ic_refresh, new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                if (usbMode) {
                    renderApps();
                } else {
                    reloadApps();
                }
            }
        }));
        usbToggle = toolIcon(R.drawable.ic_usb, new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                usbMode = !usbMode;
                if (usbMode) {
                    wide = true;
                    persist();
                    applySize();
                }
                refreshChrome();
                renderApps();
            }
        });
        tools.addView(usbToggle);
        panel.addView(tools);

        usbStatus = new TextView(this);
        usbStatus.setTextColor(Color.parseColor("#3DDC97"));
        usbStatus.setTextSize(12);
        usbStatus.setVisibility(View.GONE);
        usbStatus.setPadding(dp(4), dp(4), dp(4), dp(4));
        panel.addView(usbStatus);

        search = new EditText(this);
        search.setHint("поиск");
        search.setHintTextColor(Color.parseColor("#9AA7B8"));
        search.setTextColor(Color.WHITE);
        search.setTextSize(13);
        search.setSingleLine(true);
        search.setBackgroundColor(Color.parseColor("#3328E07A"));
        search.setPadding(dp(8), dp(8 * HEIGHT_SCALE), dp(8), dp(8 * HEIGHT_SCALE));
        search.setOnFocusChangeListener(new View.OnFocusChangeListener() {
            @Override
            public void onFocusChange(View v, boolean hasFocus) {
                if (params == null) {
                    return;
                }
                if (hasFocus) {
                    params.flags &= ~WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE;
                } else {
                    params.flags |= WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE;
                }
                try {
                    windowManager.updateViewLayout(root, params);
                } catch (Exception ignored) {
                }
            }
        });
        search.addTextChangedListener(new SimpleTextWatcher() {
            @Override
            public void onTextChanged(CharSequence s, int start, int before, int count) {
                query = s == null ? "" : s.toString();
                renderApps();
            }
        });
        panel.addView(search, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        ((LinearLayout.LayoutParams) search.getLayoutParams()).topMargin = dp(8);
        ((LinearLayout.LayoutParams) search.getLayoutParams()).bottomMargin = dp(8);

        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        appList = new LinearLayout(this);
        appList.setOrientation(LinearLayout.VERTICAL);
        scroll.addView(appList, new ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        LinearLayout.LayoutParams sp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f);
        panel.addView(scroll, sp);

        panel.setOnTouchListener(new View.OnTouchListener() {
            float startX;
            @Override
            public boolean onTouch(View v, MotionEvent event) {
                if (event.getAction() == MotionEvent.ACTION_DOWN) {
                    startX = event.getRawX();
                } else if (event.getAction() == MotionEvent.ACTION_UP) {
                    float dx = event.getRawX() - startX;
                    if (collapsed && dx < -dp(20)) {
                        expandToFull();
                        return true;
                    }
                    if (!collapsed && dx > dp(28)) {
                        setCollapsed(true);
                        return true;
                    }
                }
                return false;
            }
        });
        return panel;
    }

    private void refreshChrome() {
        if (root == null) {
            return;
        }
        int chrome = collapsed ? View.GONE : View.VISIBLE;
        if (titleView != null) {
            titleView.setVisibility(chrome);
        }
        if (tools != null) {
            tools.setVisibility(chrome);
        }
        if (search != null) {
            search.setVisibility(collapsed ? View.GONE : View.VISIBLE);
            search.setHint(usbMode ? "apk" : "поиск");
        }
        if (usbToggle instanceof ImageView) {
            ((ImageView) usbToggle).setImageResource(usbMode ? R.drawable.ic_apps : R.drawable.ic_usb);
            usbToggle.setVisibility(chrome);
        }
        if (collapsed) {
            root.setPadding(dp(2), dp(4), dp(2), dp(4));
        } else {
            root.setPadding(dp(6), dp(8), dp(6), dp(8));
        }
        root.setBackground(panelBackground(false));
    }

    private ImageView toolIcon(int drawable, View.OnClickListener click) {
        ImageView image = new ImageView(this);
        image.setImageResource(drawable);
        image.setColorFilter(Color.WHITE);
        int pad = dp(8);
        image.setPadding(pad, pad, pad, pad);
        image.setOnClickListener(click);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(dp(48), dp(48));
        image.setLayoutParams(lp);
        return image;
    }

    private View actionIcon(int drawable, int color, View.OnClickListener click) {
        ImageView image = new ImageView(this);
        image.setImageResource(drawable);
        int pad = dp(8);
        image.setPadding(pad, pad, pad, pad);
        GradientDrawable bg = new GradientDrawable();
        bg.setColor(color);
        bg.setCornerRadius(dp(12));
        image.setBackground(bg);
        image.setOnClickListener(click);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(dp(48), dp(48));
        lp.setMargins(dp(6), 0, 0, 0);
        image.setLayoutParams(lp);
        return image;
    }

    private GradientDrawable panelBackground(boolean chip) {
        GradientDrawable d = new GradientDrawable();
        if (chip) {
            d.setColor(Color.parseColor("#990B1220"));
            d.setCornerRadii(new float[]{dp(10), dp(10), 0, 0, 0, 0, dp(10), dp(10)});
            d.setStroke(Math.max(1, dp(1) / 2), Color.parseColor("#333DDC97"));
        } else {
            d.setColor(Color.parseColor("#E60B1220"));
            d.setCornerRadii(new float[]{dp(18), dp(18), 0, 0, 0, 0, dp(18), dp(18)});
            d.setStroke(dp(1), Color.parseColor("#663DDC97"));
        }
        return d;
    }

    private void setCollapsed(boolean value) {
        keyboardPeek = false;
        collapsed = value;
        persist();
        relayout();
        if (!collapsed) {
            renderApps();
        }
    }

    private void expandToFull() {
        usbMode = false;
        wide = true;
        collapsed = false;
        keyboardPeek = false;
        persist();
        relayout();
        renderApps();
    }

    private void persist() {
        getSharedPreferences(PREFS, MODE_PRIVATE)
                .edit()
                .putBoolean(KEY_COLLAPSED, collapsed)
                .putBoolean(KEY_WIDE, wide)
                .apply();
    }

    private Set<String> favorites() {
        return new HashSet<String>(getSharedPreferences(PREFS, MODE_PRIVATE)
                .getStringSet(KEY_FAV, new HashSet<String>()));
    }

    private void toggleFavorite(String pkg) {
        Set<String> fav = favorites();
        if (fav.contains(pkg)) {
            fav.remove(pkg);
        } else {
            fav.add(pkg);
        }
        getSharedPreferences(PREFS, MODE_PRIVATE).edit().putStringSet(KEY_FAV, fav).apply();
        renderApps();
    }

    private Set<String> hidden() {
        return new HashSet<String>(getSharedPreferences(PREFS, MODE_PRIVATE)
                .getStringSet(KEY_HIDDEN, new HashSet<String>()));
    }

    private void setHidden(String pkg, boolean hide) {
        if (pkg == null || pkg.equals(getPackageName()) || isLegacyPackage(pkg)) {
            return;
        }
        Set<String> hideSet = hidden();
        if (hide) {
            hideSet.add(pkg);
        } else {
            hideSet.remove(pkg);
        }
        getSharedPreferences(PREFS, MODE_PRIVATE).edit().putStringSet(KEY_HIDDEN, hideSet).apply();
    }

    private void reloadApps() {
        PackageManager pm = getPackageManager();
        Intent intent = new Intent(Intent.ACTION_MAIN, null);
        intent.addCategory(Intent.CATEGORY_LAUNCHER);
        List<ResolveInfo> resolved = pm.queryIntentActivities(intent, 0);
        List<AppItem> items = new ArrayList<>();
        Set<String> seen = new HashSet<>();
        for (ResolveInfo ri : resolved) {
            if (ri.activityInfo == null) {
                continue;
            }
            String pkg = ri.activityInfo.packageName;
            if (getPackageName().equals(pkg)
                    || isLegacyPackage(pkg)
                    || seen.contains(pkg)) {
                continue;
            }
            seen.add(pkg);
            AppItem item = new AppItem();
            item.pkg = pkg;
            item.label = String.valueOf(ri.loadLabel(pm));
            try {
                item.icon = ri.loadIcon(pm);
            } catch (Exception e) {
                item.icon = getDrawable(android.R.drawable.sym_def_app_icon);
            }
            try {
                ApplicationInfo ai = pm.getApplicationInfo(pkg, 0);
                item.system = (ai.flags & ApplicationInfo.FLAG_SYSTEM) != 0
                        || (ai.flags & ApplicationInfo.FLAG_UPDATED_SYSTEM_APP) != 0;
            } catch (Exception ignored) {
            }
            items.add(item);
        }
        final Set<String> fav = favorites();
        Collections.sort(items, new Comparator<AppItem>() {
            @Override
            public int compare(AppItem a, AppItem b) {
                if (a.system != b.system) {
                    return a.system ? 1 : -1;
                }
                boolean fa = fav.contains(a.pkg);
                boolean fb = fav.contains(b.pkg);
                if (fa != fb) {
                    return fa ? -1 : 1;
                }
                return a.label.compareToIgnoreCase(b.label);
            }
        });
        apps = items;
        if (collapsed && !keyboardPeek) {
            if (dockRecent != null) {
                removeView(dockRecent);
                dockRecent = null;
            }
            relayout();
        } else {
            renderApps();
        }
    }

    private void renderApps() {
        if (appList == null) {
            return;
        }
        if (collapsed || keyboardPeek) {
            return;
        }
        appList.removeAllViews();
        if (usbMode) {
            renderUsb();
            return;
        }
        String q = query == null ? "" : query.toLowerCase(Locale.ROOT).trim();
        Set<String> fav = favorites();
        Set<String> hideSet = hidden();
        int shown = 0;
        boolean userHeader = false;
        boolean systemHeader = false;
        List<AppItem> hiddenItems = new ArrayList<>();
        for (final AppItem item : apps) {
            if (q.length() > 0 && !item.label.toLowerCase(Locale.ROOT).contains(q)
                    && !item.pkg.toLowerCase(Locale.ROOT).contains(q)) {
                continue;
            }
            if (hideSet.contains(item.pkg)) {
                hiddenItems.add(item);
                continue;
            }
            if (!item.system && !userHeader) {
                appList.addView(sectionHeader("Сторонние"));
                userHeader = true;
            }
            if (item.system && !systemHeader) {
                appList.addView(sectionHeader("Системные"));
                systemHeader = true;
            }
            appList.addView(row(item, fav.contains(item.pkg), false));
            shown++;
        }
        if (hiddenItems.size() > 0) {
            appList.addView(sectionHeader("Скрытые"));
            for (int i = 0; i < hiddenItems.size(); i++) {
                AppItem item = hiddenItems.get(i);
                appList.addView(row(item, fav.contains(item.pkg), true));
                shown++;
            }
        }
        if (shown == 0) {
            TextView empty = new TextView(this);
            empty.setText("нет приложений");
            empty.setTextColor(Color.parseColor("#9AA7B8"));
            empty.setGravity(Gravity.CENTER);
            empty.setPadding(0, dp(12 * HEIGHT_SCALE), 0, dp(12 * HEIGHT_SCALE));
            appList.addView(empty);
        }
    }

    private View collapseZone(int icon, View.OnClickListener click) {
        LinearLayout zone = new LinearLayout(this);
        zone.setOrientation(LinearLayout.VERTICAL);
        zone.setGravity(Gravity.CENTER);
        zone.setOnClickListener(click);
        ImageView image = new ImageView(this);
        image.setImageResource(icon);
        image.setColorFilter(Color.parseColor("#CC3DDC97"));
        zone.addView(image, new LinearLayout.LayoutParams(dp(COLLAPSED_ICON_DP), dp(COLLAPSED_ICON_DP)));
        return zone;
    }

    private View recentZone() {
        LinearLayout zone = new LinearLayout(this);
        zone.setOrientation(LinearLayout.VERTICAL);
        zone.setGravity(Gravity.CENTER_HORIZONTAL);
        List<String> recent = recentPackages();
        // Equal gap to the edges and between icons (space-evenly).
        zone.addView(evenSpacer());
        for (int i = 0; i < RECENT_MAX; i++) {
            ImageView image = new ImageView(this);
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                    dp(COLLAPSED_ICON_DP), dp(COLLAPSED_ICON_DP));
            lp.gravity = Gravity.CENTER_HORIZONTAL;
            if (i < recent.size()) {
                final String pkg = recent.get(i);
                image.setImageDrawable(iconFor(pkg));
                image.setOnClickListener(new View.OnClickListener() {
                    @Override
                    public void onClick(View v) {
                        launch(pkg);
                    }
                });
            } else {
                image.setImageResource(R.drawable.ic_apps);
                image.setColorFilter(Color.parseColor("#9AA7B8"));
                image.setAlpha(0.4f);
            }
            zone.addView(image, lp);
            zone.addView(evenSpacer());
        }
        return zone;
    }

    private View evenSpacer() {
        View spacer = new View(this);
        spacer.setLayoutParams(new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f));
        return spacer;
    }

    private void renderUsb() {
        TextView hint = new TextView(this);
        hint.setText("APK с флешки в USB ГУ. Тап по строке или зелёной кнопке — установка.");
        hint.setTextColor(Color.parseColor("#9AA7B8"));
        hint.setTextSize(11);
        hint.setPadding(dp(4), 0, dp(4), dp(8));
        appList.addView(hint);
        if (usbStatus != null && usbStatus.getVisibility() == View.VISIBLE) {
            TextView copy = new TextView(this);
            copy.setText(usbStatus.getText());
            copy.setTextColor(Color.parseColor("#3DDC97"));
            copy.setPadding(dp(4), 0, dp(4), dp(8));
            appList.addView(copy);
        }
        List<File> apks = UsbStorage.apkFiles(this);
        String q = query == null ? "" : query.toLowerCase(Locale.ROOT).trim();
        int shown = 0;
        for (int i = 0; i < apks.size(); i++) {
            final File apk = apks.get(i);
            String name = apk.getName();
            if (q.length() > 0 && !name.toLowerCase(Locale.ROOT).contains(q)
                    && !apk.getAbsolutePath().toLowerCase(Locale.ROOT).contains(q)) {
                continue;
            }
            appList.addView(apkRow(apk));
            shown++;
        }
        if (shown == 0) {
            TextView empty = new TextView(this);
            List<File> roots = UsbStorage.roots(this);
            StringBuilder paths = new StringBuilder();
            for (int i = 0; i < roots.size() && i < 6; i++) {
                if (paths.length() > 0) {
                    paths.append("\n");
                }
                paths.append(roots.get(i).getAbsolutePath());
            }
            empty.setText(apks.isEmpty()
                    ? "APK не найдены.\nВставьте USB в разъём ГУ.\n" + paths
                    : "нет APK по поиску");
            empty.setTextColor(Color.parseColor("#9AA7B8"));
            empty.setGravity(Gravity.CENTER);
            empty.setPadding(0, dp(12), 0, dp(12));
            appList.addView(empty);
        }
    }

    private View sectionHeader(String text) {
        TextView header = new TextView(this);
        header.setText(text);
        header.setTextColor(Color.parseColor("#3DDC97"));
        header.setTextSize(13);
        header.setTypeface(Typeface.DEFAULT_BOLD);
        header.setPadding(dp(4), dp(14), dp(4), dp(6));
        return header;
    }

    private View apkRow(final File apk) {
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setGravity(Gravity.CENTER_VERTICAL);
        row.setPadding(dp(4), dp(10), dp(4), dp(10));
        GradientDrawable bg = new GradientDrawable();
        bg.setColor(Color.parseColor("#2228E07A"));
        bg.setCornerRadius(dp(10));
        row.setBackground(bg);

        LinearLayout text = new LinearLayout(this);
        text.setOrientation(LinearLayout.VERTICAL);
        LinearLayout.LayoutParams textLp = new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f);
        TextView name = new TextView(this);
        name.setText(apk.getName());
        name.setTextColor(Color.WHITE);
        name.setTextSize(14);
        name.setMaxLines(2);
        TextView meta = new TextView(this);
        meta.setText(apk.getParent() + " · " + (apk.length() / 1024) + " КБ");
        meta.setTextColor(Color.parseColor("#9AA7B8"));
        meta.setTextSize(10);
        meta.setMaxLines(2);
        text.addView(name);
        text.addView(meta);
        row.addView(text, textLp);
        View installBtn = actionIcon(R.drawable.ic_install, Color.parseColor("#3DDC97"), new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                installFromUsb(apk);
            }
        });
        row.addView(installBtn);
        row.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                installFromUsb(apk);
            }
        });
        return row;
    }

    private void showUsbStatus(String message) {
        if (usbStatus != null) {
            usbStatus.setText(message);
            usbStatus.setVisibility(View.VISIBLE);
        }
        if (usbMode && !collapsed && appList != null) {
            renderApps();
        }
    }

    private void installFromUsb(File apk) {
        showUsbStatus("ставлю " + apk.getName() + "…");
        try {
            File local = PackageActions.copyToCache(this, apk);
            PackageActions.install(this, local);
            showUsbStatus("отправлено в установщик: " + apk.getName());
        } catch (Exception e) {
            String msg = e.getMessage() == null ? e.getClass().getSimpleName() : e.getMessage();
            showUsbStatus("ошибка: " + msg);
            usbMode = true;
            setCollapsed(false);
        }
    }

    private View row(final AppItem item, boolean favorite, final boolean hidden) {
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setGravity(Gravity.CENTER_VERTICAL);
        row.setPadding(dp(4), dp(ROW_PAD_V_DP), dp(4), dp(ROW_PAD_V_DP));
        row.setMinimumHeight(dp(ICON_DP + ROW_PAD_V_DP));
        GradientDrawable bg = new GradientDrawable();
        bg.setColor(hidden
                ? Color.parseColor("#22FF6B6B")
                : (favorite ? Color.parseColor("#3328E07A") : Color.TRANSPARENT));
        bg.setCornerRadius(dp(12));
        row.setBackground(bg);

        ImageView icon = new ImageView(this);
        icon.setImageDrawable(item.icon);
        icon.setAlpha(hidden ? 0.45f : 1f);
        int iconW = dp(ICON_DP);
        LinearLayout.LayoutParams ip = new LinearLayout.LayoutParams(iconW, dp(ICON_DP));
        row.addView(icon, ip);

        boolean pending = item.pkg.equals(pendingHidePkg);
        if (wide) {
            LinearLayout textCol = new LinearLayout(this);
            textCol.setOrientation(LinearLayout.VERTICAL);
            textCol.setPadding(dp(10), 0, 0, 0);
            TextView name = new TextView(this);
            name.setText(item.label);
            name.setTextColor(Color.WHITE);
            name.setTextSize(14);
            name.setMaxLines(2);
            TextView mark = new TextView(this);
            if (pending) {
                mark.setText(hidden ? "галочка — вернуть, крестик — оставить" : "галочка — скрыть, крестик — отмена");
            } else if (hidden) {
                mark.setText("скрыто в панели");
            } else {
                mark.setText(favorite ? "★ избранное" : "удерживайте ★");
            }
            mark.setTextColor(Color.parseColor("#9AA7B8"));
            mark.setTextSize(10);
            textCol.addView(name);
            textCol.addView(mark);
            row.addView(textCol, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
        }

        row.addView(hideAction(item, hidden, pending));

        row.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                if (hidden) {
                    return;
                }
                launch(item.pkg);
            }
        });
        row.setOnLongClickListener(new View.OnLongClickListener() {
            @Override
            public boolean onLongClick(View v) {
                toggleFavorite(item.pkg);
                return true;
            }
        });
        return row;
    }

    private View hideAction(final AppItem item, final boolean hidden, boolean pending) {
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.HORIZONTAL);
        box.setGravity(Gravity.CENTER_VERTICAL);
        box.setClickable(true);
        if (pending) {
            box.addView(actionIcon(R.drawable.ic_check, Color.parseColor("#3DDC97"), new View.OnClickListener() {
                @Override
                public void onClick(View v) {
                    setHidden(item.pkg, !hidden);
                    pendingHidePkg = null;
                    renderApps();
                }
            }));
            box.addView(actionIcon(R.drawable.ic_close, Color.parseColor("#FF6B6B"), new View.OnClickListener() {
                @Override
                public void onClick(View v) {
                    pendingHidePkg = null;
                    renderApps();
                }
            }));
        } else {
            box.addView(actionIcon(R.drawable.ic_eye_off, Color.parseColor("#5A6A80"), new View.OnClickListener() {
                @Override
                public void onClick(View v) {
                    pendingHidePkg = item.pkg;
                    renderApps();
                }
            }));
        }
        return box;
    }

    private void launch(String pkg) {
        try {
            Intent intent = getPackageManager().getLaunchIntentForPackage(pkg);
            if (intent == null) {
                return;
            }
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            startActivity(intent);
            rememberLaunch(pkg);
        } catch (Exception ignored) {
        }
    }

    private void rememberLaunch(String pkg) {
        if (pkg == null || pkg.equals(getPackageName())) {
            return;
        }
        List<String> rec = storedRecents();
        rec.remove(pkg);
        rec.add(0, pkg);
        while (rec.size() > RECENT_MAX) {
            rec.remove(rec.size() - 1);
        }
        StringBuilder joined = new StringBuilder();
        for (int i = 0; i < rec.size(); i++) {
            if (i > 0) {
                joined.append(',');
            }
            joined.append(rec.get(i));
        }
        getSharedPreferences(PREFS, MODE_PRIVATE).edit().putString(KEY_RECENT, joined.toString()).apply();
    }

    private List<String> storedRecents() {
        List<String> out = new ArrayList<>();
        String raw = getSharedPreferences(PREFS, MODE_PRIVATE).getString(KEY_RECENT, "");
        if (raw == null || raw.length() == 0) {
            return out;
        }
        String[] parts = raw.split(",");
        for (int i = 0; i < parts.length; i++) {
            if (parts[i].length() > 0) {
                out.add(parts[i]);
            }
        }
        return out;
    }

    private List<String> recentPackages() {
        LinkedHashSet<String> out = new LinkedHashSet<>();
        addUsageRecents(out);
        addTaskRecents(out);
        List<String> stored = storedRecents();
        for (int i = 0; i < stored.size(); i++) {
            addRecent(out, stored.get(i));
        }
        List<String> list = new ArrayList<String>();
        for (String pkg : out) {
            list.add(pkg);
            if (list.size() >= RECENT_MAX) {
                break;
            }
        }
        return list;
    }

    private void addUsageRecents(LinkedHashSet<String> out) {
        try {
            UsageStatsManager usm = (UsageStatsManager) getSystemService(USAGE_STATS_SERVICE);
            if (usm == null) {
                return;
            }
            long now = System.currentTimeMillis();
            Map<String, UsageStats> map = usm.queryAndAggregateUsageStats(now - 7L * 24 * 3600 * 1000, now);
            if (map == null || map.isEmpty()) {
                return;
            }
            List<UsageStats> stats = new ArrayList<UsageStats>(map.values());
            Collections.sort(stats, new Comparator<UsageStats>() {
                @Override
                public int compare(UsageStats a, UsageStats b) {
                    long d = b.getLastTimeUsed() - a.getLastTimeUsed();
                    return d < 0 ? -1 : (d > 0 ? 1 : 0);
                }
            });
            for (int i = 0; i < stats.size(); i++) {
                addRecent(out, stats.get(i).getPackageName());
                if (out.size() >= RECENT_MAX) {
                    return;
                }
            }
        } catch (Exception ignored) {
        }
    }

    private void addTaskRecents(LinkedHashSet<String> out) {
        try {
            ActivityManager am = (ActivityManager) getSystemService(ACTIVITY_SERVICE);
            if (am == null) {
                return;
            }
            List<ActivityManager.RunningTaskInfo> tasks = am.getRunningTasks(12);
            if (tasks == null) {
                return;
            }
            for (int i = 0; i < tasks.size(); i++) {
                ActivityManager.RunningTaskInfo task = tasks.get(i);
                if (task.baseActivity != null) {
                    addRecent(out, task.baseActivity.getPackageName());
                }
                if (out.size() >= RECENT_MAX) {
                    return;
                }
            }
        } catch (Exception ignored) {
        }
    }

    private void addRecent(LinkedHashSet<String> out, String pkg) {
        if (pkg == null || pkg.equals(getPackageName())) {
            return;
        }
        if (hidden().contains(pkg)) {
            return;
        }
        if (getPackageManager().getLaunchIntentForPackage(pkg) == null) {
            return;
        }
        out.add(pkg);
    }

    private Drawable iconFor(String pkg) {
        try {
            return getPackageManager().getApplicationIcon(pkg);
        } catch (Exception e) {
            return getDrawable(android.R.drawable.sym_def_app_icon);
        }
    }

    private int dp(int value) {
        DisplayMetrics m = getResources().getDisplayMetrics();
        return Math.round(value * m.density);
    }

    /** Old overlay ids cannot be uninstalled on Feiyu (auth, not allow delete). */
    private void suppressLegacy() {
        for (String pkg : LEGACY_PACKAGES) {
            if (pkg.equals(getPackageName())) {
                continue;
            }
            try {
                Intent hide = new Intent(ACTION_HIDE);
                hide.setClassName(pkg, OverlayService.class.getName());
                startService(hide);
            } catch (Exception ignored) {
            }
            try {
                ActivityManager am = (ActivityManager) getSystemService(ACTIVITY_SERVICE);
                if (am != null) {
                    am.killBackgroundProcesses(pkg);
                }
            } catch (Exception ignored) {
            }
        }
    }

    static boolean isLegacyPackage(String pkg) {
        if (pkg == null) {
            return false;
        }
        for (String legacy : LEGACY_PACKAGES) {
            if (legacy.equals(pkg)) {
                return true;
            }
        }
        return false;
    }

    private static class AppItem {
        String pkg;
        String label;
        Drawable icon;
        boolean system;
    }

    private abstract static class SimpleTextWatcher implements android.text.TextWatcher {
        @Override
        public void beforeTextChanged(CharSequence s, int start, int count, int after) {
        }

        @Override
        public abstract void onTextChanged(CharSequence s, int start, int before, int count);

        @Override
        public void afterTextChanged(android.text.Editable s) {
        }
    }
}
