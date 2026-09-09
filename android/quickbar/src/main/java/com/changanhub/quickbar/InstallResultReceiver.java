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
        Intent refresh = new Intent(context, OverlayService.class);
        refresh.setAction(OverlayService.ACTION_REFRESH);
        if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.O) {
            context.startForegroundService(refresh);
        } else {
            context.startService(refresh);
        }
    }
}
