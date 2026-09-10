package com.changanhub.quickbar;

import android.app.Activity;
import android.content.Intent;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.PowerManager;
import android.provider.Settings;
import android.view.View;
import android.widget.Button;
import android.widget.TextView;

public class MainActivity extends Activity {
    private TextView status;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);
        status = findViewById(R.id.status);
        Button start = findViewById(R.id.btn_start);
        start.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                if (!canDraw()) {
                    requestOverlay();
                    return;
                }
                startPanel();
                status.setText("Панель запущена справа");
                finish();
            }
        });
        refresh();
        if (canDraw()) {
            startPanel();
        }
    }

    @Override
    protected void onResume() {
        super.onResume();
        refresh();
        if (canDraw()) {
            startPanel();
        }
    }

    private void startPanel() {
        requestIgnoreBattery();
        OverlayService.start(this);
        OverlayService.scheduleWatchdog(this);
        KeepAliveJob.schedule(this);
    }

    private void refresh() {
        status.setText(canDraw()
                ? "Разрешение выдано. Панель можно держать всегда поверх приложений."
                : getString(R.string.need_overlay));
    }

    private boolean canDraw() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M) {
            return true;
        }
        return Settings.canDrawOverlays(this);
    }

    private void requestOverlay() {
        try {
            Intent intent = new Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                    Uri.parse("package:" + getPackageName()));
            startActivity(intent);
        } catch (Exception ignored) {
            status.setText(getString(R.string.need_overlay));
        }
    }

    private void requestIgnoreBattery() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M) {
            return;
        }
        try {
            PowerManager pm = (PowerManager) getSystemService(POWER_SERVICE);
            if (pm != null && pm.isIgnoringBatteryOptimizations(getPackageName())) {
                return;
            }
            Intent intent = new Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS);
            intent.setData(Uri.parse("package:" + getPackageName()));
            startActivity(intent);
        } catch (Exception ignored) {
        }
    }
}
