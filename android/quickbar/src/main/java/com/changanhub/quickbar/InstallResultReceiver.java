package com.changanhub.quickbar;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageInstaller;

public class InstallResultReceiver extends BroadcastReceiver {
    public static final String ACTION = "com.changanhub.quickbar.INSTALL_RESULT";

    @Override
    public void onReceive(Context context, Intent intent) {
        int status = intent.getIntExtra(
                PackageInstaller.EXTRA_STATUS, PackageInstaller.STATUS_FAILURE);
        if (status == PackageInstaller.STATUS_PENDING_USER_ACTION) {
            OverlayService.pauseForDialog(context);
            Intent confirm = intent.getParcelableExtra(Intent.EXTRA_INTENT);
            if (confirm != null) {
                confirm.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                context.startActivity(confirm);
            }
            return;
        }
        String pkg = intent.getStringExtra("pkg");
        if (status != PackageInstaller.STATUS_SUCCESS && pkg != null && pkg.length() > 0) {
            PackageActions.disable(context, pkg);
        }
        OverlayService.keepAlive(context);
        Intent refresh = new Intent(context, OverlayService.class);
        refresh.setAction(OverlayService.ACTION_REFRESH);
        try {
            if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.O) {
                context.startForegroundService(refresh);
            } else {
                context.startService(refresh);
            }
        } catch (Exception ignored) {
            try {
                context.startService(refresh);
            } catch (Exception ignoredStart) {
            }
        }
    }
}
