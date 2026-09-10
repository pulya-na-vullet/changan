package com.changanhub.quickbar;

import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageInstaller;
import android.net.Uri;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;

/** Uninstall user apps and sideload APKs from a USB stick. */
public final class PackageActions {
    private PackageActions() {
    }

    public static void uninstall(Context context, String pkg) {
        Intent intent = new Intent(Intent.ACTION_DELETE);
        intent.setData(Uri.parse("package:" + pkg));
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        context.startActivity(intent);
    }

    /** PackageInstaller often cannot stream from /mnt/media_rw; copy first. */
    public static File copyToCache(Context context, File apk) throws Exception {
        File dir = new File(context.getCacheDir(), "apk");
        if (!dir.exists() && !dir.mkdirs()) {
            throw new Exception("нет кэша для APK");
        }
        File dest = new File(dir, apk.getName());
        FileInputStream in = new FileInputStream(apk);
        FileOutputStream out = new FileOutputStream(dest);
        try {
            byte[] buf = new byte[65536];
            int n;
            while ((n = in.read(buf)) >= 0) {
                if (n == 0) {
                    continue;
                }
                out.write(buf, 0, n);
            }
            out.flush();
        } finally {
            in.close();
            out.close();
        }
        if (dest.length() < 64) {
            throw new Exception("скопированный APK пустой");
        }
        return dest;
    }

    public static void install(Context context, File apk) throws Exception {
        PackageInstaller installer = context.getPackageManager().getPackageInstaller();
        PackageInstaller.SessionParams params = new PackageInstaller.SessionParams(
                PackageInstaller.SessionParams.MODE_FULL_INSTALL);
        int sessionId = installer.createSession(params);
        PackageInstaller.Session session = installer.openSession(sessionId);
        boolean committed = false;
        try {
            OutputStream out = session.openWrite("base.apk", 0, apk.length());
            InputStream in = new FileInputStream(apk);
            try {
                byte[] buf = new byte[65536];
                int n;
                while ((n = in.read(buf)) >= 0) {
                    if (n == 0) {
                        continue;
                    }
                    out.write(buf, 0, n);
                }
                session.fsync(out);
            } finally {
                in.close();
                out.close();
            }
            Intent callback = new Intent(context, InstallResultReceiver.class);
            callback.setAction(InstallResultReceiver.ACTION);
            PendingIntent pi = PendingIntent.getBroadcast(
                    context, sessionId, callback, PendingIntent.FLAG_UPDATE_CURRENT);
            session.commit(pi.getIntentSender());
            committed = true;
        } finally {
            if (!committed) {
                session.abandon();
            }
        }
    }
}
