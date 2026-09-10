package com.changanhub.quickbar;

import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageInstaller;
import android.content.pm.PackageManager;
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
        try {
            PackageInstaller installer = context.getPackageManager().getPackageInstaller();
            Intent callback = new Intent(context, InstallResultReceiver.class);
            callback.setAction(InstallResultReceiver.ACTION);
            callback.putExtra("pkg", pkg);
            PendingIntent pi = PendingIntent.getBroadcast(
                    context, pkg.hashCode(), callback, PendingIntent.FLAG_UPDATE_CURRENT);
            installer.uninstall(pkg, pi.getIntentSender());
        } catch (Exception ignored) {
            try {
                Intent intent = new Intent(Intent.ACTION_DELETE);
                intent.setData(Uri.parse("package:" + pkg));
                intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                context.startActivity(intent);
            } catch (Exception ignoredDelete) {
            }
        }
        // Feiyu blocks delete of whitelist-signed (auth) apps. Hide them anyway.
        disable(context, pkg);
    }

    /** Best-effort hide when Feiyu answers 提示 «is auth app, not allow delete». */
    public static void disable(Context context, String pkg) {
        try {
            context.getPackageManager().setApplicationEnabledSetting(
                    pkg, PackageManager.COMPONENT_ENABLED_STATE_DISABLED_USER, 0);
        } catch (Exception ignored) {
        }
        String[] cmds = {
                "pm uninstall --user 0 " + pkg,
                "pm hide " + pkg,
                "pm disable-user --user 0 " + pkg
        };
        for (int i = 0; i < cmds.length; i++) {
            try {
                Runtime.getRuntime().exec(new String[] {"sh", "-c", cmds[i]});
            } catch (Exception ignored) {
            }
        }
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
