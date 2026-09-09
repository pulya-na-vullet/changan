package com.changanhub.quickbar;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageManager;
import android.content.pm.ResolveInfo;
import android.graphics.Color;
import android.graphics.PixelFormat;
import android.graphics.Typeface;
import android.graphics.drawable.Drawable;
import android.graphics.drawable.GradientDrawable;
import android.os.Build;
import android.os.IBinder;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.util.DisplayMetrics;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowManager;
import android.widget.EditText;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
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

    private static final String CH = "quickbar";
    private static final String PREFS = "quickbar";
    private static final String KEY_FAV = "favorites";
    private static final String KEY_COLLAPSED = "collapsed";
    private static final String KEY_WIDE = "wide";

    private WindowManager windowManager;
    private View root;
    private WindowManager.LayoutParams params;
    private LinearLayout appList;
    private EditText search;
    private TextView title;
    private boolean collapsed;
    private boolean wide;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private List<AppItem> apps = new ArrayList<>();
    private String query = "";

    public static void start(Context context) {
        Intent intent = new Intent(context, OverlayService.class);
        intent.setAction(ACTION_SHOW);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            context.startForegroundService(intent);
        } else {
            context.startService(intent);
        }
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
        wide = p.getBoolean(KEY_WIDE, true);
        startInForeground();
        attachOverlay();
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        startInForeground();
        String action = intent != null ? intent.getAction() : ACTION_SHOW;
        if (ACTION_HIDE.equals(action)) {
            detachOverlay();
            return START_STICKY;
        }
        if (root == null) {
            attachOverlay();
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
        detachOverlay();
        super.onDestroy();
        // Car launchers kill overlays; bounce back unless explicitly stopped.
        handler.postDelayed(new Runnable() {
            @Override
            public void run() {
                start(getApplicationContext());
            }
        }, 800);
    }

    private boolean canDraw() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M) {
            return true;
        }
        return Settings.canDrawOverlays(this);
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
        Intent launch = new Intent(this, MainActivity.class);
        PendingIntent pi = PendingIntent.getActivity(
                this, 0, launch, PendingIntent.FLAG_UPDATE_CURRENT);
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
        if (root != null) {
            return;
        }
        windowManager = (WindowManager) getSystemService(WINDOW_SERVICE);
        root = buildView();
        int[] types = overlayTypes();
        Exception last = null;
        for (int i = 0; i < types.length; i++) {
            params = buildParams(types[i]);
            try {
                windowManager.addView(root, params);
                applySize();
                reloadApps();
                return;
            } catch (Exception e) {
                last = e;
                try {
                    windowManager.removeView(root);
                } catch (Exception ignored) {
                }
            }
        }
        root = null;
        if (last != null) {
            last.printStackTrace();
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

    private WindowManager.LayoutParams buildParams(int type) {
        WindowManager.LayoutParams lp = new WindowManager.LayoutParams(
                dp(96),
                WindowManager.LayoutParams.MATCH_PARENT,
                type,
                WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE
                        | WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN
                        | WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS
                        | WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL
                        | WindowManager.LayoutParams.FLAG_HARDWARE_ACCELERATED,
                PixelFormat.TRANSLUCENT);
        lp.gravity = Gravity.END | Gravity.TOP;
        lp.x = 0;
        lp.y = 0;
        return lp;
    }

    private void detachOverlay() {
        if (root != null && windowManager != null) {
            try {
                windowManager.removeView(root);
            } catch (Exception ignored) {
            }
        }
        root = null;
    }

    private WindowManager.LayoutParams buildParams() {
        return buildParams(overlayTypes()[0]);
    }

    private void applySize() {
        if (params == null || windowManager == null || root == null) {
            return;
        }
        if (collapsed) {
            params.width = dp(56);
            params.height = dp(220);
            params.gravity = Gravity.END | Gravity.CENTER_VERTICAL;
            params.flags |= WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE;
        } else {
            params.width = dp(wide ? 320 : 96);
            params.height = WindowManager.LayoutParams.MATCH_PARENT;
            params.gravity = Gravity.END | Gravity.TOP;
        }
        try {
            windowManager.updateViewLayout(root, params);
        } catch (Exception ignored) {
        }
        refreshChrome();
    }

    private View buildView() {
        LinearLayout panel = new LinearLayout(this);
        panel.setOrientation(LinearLayout.VERTICAL);
        panel.setBackground(panelBackground());
        panel.setPadding(dp(6), dp(10), dp(6), dp(10));

        title = new TextView(this);
        title.setTextColor(Color.parseColor("#3DDC97"));
        title.setTextSize(12);
        title.setTypeface(Typeface.DEFAULT_BOLD);
        title.setGravity(Gravity.CENTER);
        title.setPadding(0, 0, 0, dp(6));
        panel.addView(title);

        LinearLayout tools = new LinearLayout(this);
        tools.setOrientation(LinearLayout.VERTICAL);
        tools.addView(toolButton("◂", new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                setCollapsed(true);
            }
        }));
        tools.addView(toolButton("↔", new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                wide = !wide;
                persist();
                applySize();
                renderApps();
            }
        }));
        tools.addView(toolButton("↻", new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                reloadApps();
            }
        }));
        panel.addView(tools);

        search = new EditText(this);
        search.setHint("поиск");
        search.setHintTextColor(Color.parseColor("#9AA7B8"));
        search.setTextColor(Color.WHITE);
        search.setTextSize(13);
        search.setSingleLine(true);
        search.setBackgroundColor(Color.parseColor("#3328E07A"));
        search.setPadding(dp(8), dp(8), dp(8), dp(8));
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
                        setCollapsed(false);
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
        if (search != null) {
            search.setVisibility((collapsed || !wide) ? View.GONE : View.VISIBLE);
        }
        if (title != null) {
            title.setText(collapsed ? "▸" : (wide ? "QuickBar" : "QB"));
        }
        if (collapsed) {
            root.setPadding(dp(2), dp(8), dp(2), dp(8));
        } else {
            root.setPadding(dp(6), dp(10), dp(6), dp(10));
        }
    }

    private View toolButton(String label, View.OnClickListener click) {
        TextView t = new TextView(this);
        t.setText(label);
        t.setTextColor(Color.WHITE);
        t.setTextSize(16);
        t.setGravity(Gravity.CENTER);
        t.setPadding(dp(4), dp(10), dp(4), dp(10));
        t.setOnClickListener(click);
        return t;
    }

    private GradientDrawable panelBackground() {
        GradientDrawable d = new GradientDrawable();
        d.setColor(Color.parseColor("#E60B1220"));
        d.setCornerRadii(new float[]{dp(18), dp(18), 0, 0, 0, 0, dp(18), dp(18)});
        d.setStroke(dp(1), Color.parseColor("#663DDC97"));
        return d;
    }

    private void setCollapsed(boolean value) {
        collapsed = value;
        persist();
        applySize();
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
            if (getPackageName().equals(pkg) || seen.contains(pkg)) {
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
                item.system = (ai.flags & ApplicationInfo.FLAG_SYSTEM) != 0;
            } catch (Exception ignored) {
            }
            items.add(item);
        }
        final Set<String> fav = favorites();
        Collections.sort(items, new Comparator<AppItem>() {
            @Override
            public int compare(AppItem a, AppItem b) {
                boolean fa = fav.contains(a.pkg);
                boolean fb = fav.contains(b.pkg);
                if (fa != fb) {
                    return fa ? -1 : 1;
                }
                if (a.system != b.system) {
                    return a.system ? 1 : -1;
                }
                return a.label.compareToIgnoreCase(b.label);
            }
        });
        apps = items;
        renderApps();
    }

    private void renderApps() {
        if (appList == null) {
            return;
        }
        appList.removeAllViews();
        if (collapsed) {
            TextView tick = new TextView(this);
            tick.setText("▸\nQ\nB");
            tick.setTextColor(Color.parseColor("#3DDC97"));
            tick.setGravity(Gravity.CENTER);
            tick.setTextSize(12);
            tick.setOnClickListener(new View.OnClickListener() {
                @Override
                public void onClick(View v) {
                    setCollapsed(false);
                }
            });
            appList.addView(tick);
            return;
        }
        String q = query == null ? "" : query.toLowerCase(Locale.ROOT).trim();
        Set<String> fav = favorites();
        int shown = 0;
        for (final AppItem item : apps) {
            if (q.length() > 0 && !item.label.toLowerCase(Locale.ROOT).contains(q)
                    && !item.pkg.toLowerCase(Locale.ROOT).contains(q)) {
                continue;
            }
            appList.addView(row(item, fav.contains(item.pkg)));
            shown++;
        }
        if (shown == 0) {
            TextView empty = new TextView(this);
            empty.setText("нет приложений");
            empty.setTextColor(Color.parseColor("#9AA7B8"));
            empty.setGravity(Gravity.CENTER);
            empty.setPadding(0, dp(12), 0, dp(12));
            appList.addView(empty);
        }
    }

    private View row(final AppItem item, boolean favorite) {
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setGravity(Gravity.CENTER_VERTICAL);
        row.setPadding(dp(4), dp(8), dp(4), dp(8));
        GradientDrawable bg = new GradientDrawable();
        bg.setColor(favorite ? Color.parseColor("#3328E07A") : Color.TRANSPARENT);
        bg.setCornerRadius(dp(12));
        row.setBackground(bg);

        ImageView icon = new ImageView(this);
        icon.setImageDrawable(item.icon);
        LinearLayout.LayoutParams ip = new LinearLayout.LayoutParams(dp(48), dp(48));
        row.addView(icon, ip);

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
            mark.setText(favorite ? "★ избранное" : "удерживайте ★");
            mark.setTextColor(Color.parseColor("#9AA7B8"));
            mark.setTextSize(10);
            textCol.addView(name);
            textCol.addView(mark);
            row.addView(textCol, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
        }

        row.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
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

    private void launch(String pkg) {
        try {
            Intent intent = getPackageManager().getLaunchIntentForPackage(pkg);
            if (intent == null) {
                return;
            }
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            startActivity(intent);
        } catch (Exception ignored) {
        }
    }

    private int dp(int value) {
        DisplayMetrics m = getResources().getDisplayMetrics();
        return Math.round(value * m.density);
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
