package com.changanhub.chat;

import android.content.Context;
import android.content.res.AssetManager;

import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;

/** Copies bundled RHVoice language/voice data out of assets to a real path. */
public final class RhVoiceData {
    public static final String VERSION = "elena-4.3";

    private RhVoiceData() {
    }

    public static File root(Context context) {
        return new File(context.getFilesDir(), "rhvoice");
    }

    public static File configDir(Context context) {
        File dir = new File(context.getFilesDir(), "rhvoice-config");
        dir.mkdirs();
        return dir;
    }

    public static synchronized File ensure(Context context) throws Exception {
        File root = root(context);
        File stamp = new File(root, ".pack");
        if (stamp.isFile() && VERSION.equals(read(stamp)) && new File(root, "voices/elena/voice.info").isFile()
                && new File(root, "languages/Russian/language.info").isFile()) {
            return root;
        }
        deleteTree(root);
        copyAssetDir(context.getAssets(), "rhvoice", root);
        write(stamp, VERSION);
        return root;
    }

    private static void copyAssetDir(AssetManager am, String assetPath, File dest) throws Exception {
        String[] kids = am.list(assetPath);
        if (kids == null || kids.length == 0) {
            dest.getParentFile().mkdirs();
            InputStream in = am.open(assetPath);
            try {
                OutputStream out = new FileOutputStream(dest);
                try {
                    byte[] buf = new byte[16384];
                    int n;
                    while ((n = in.read(buf)) > 0) {
                        out.write(buf, 0, n);
                    }
                } finally {
                    out.close();
                }
            } finally {
                in.close();
            }
            return;
        }
        dest.mkdirs();
        for (int i = 0; i < kids.length; i++) {
            copyAssetDir(am, assetPath + "/" + kids[i], new File(dest, kids[i]));
        }
    }

    private static String read(File file) {
        try {
            InputStream in = new java.io.FileInputStream(file);
            try {
                byte[] buf = new byte[(int) Math.min(file.length(), 64)];
                int n = in.read(buf);
                return n > 0 ? new String(buf, 0, n, "UTF-8").trim() : "";
            } finally {
                in.close();
            }
        } catch (Exception e) {
            return "";
        }
    }

    private static void write(File file, String text) throws Exception {
        OutputStream out = new FileOutputStream(file);
        try {
            out.write(text.getBytes("UTF-8"));
        } finally {
            out.close();
        }
    }

    private static void deleteTree(File file) {
        if (file == null || !file.exists()) {
            return;
        }
        File[] kids = file.listFiles();
        if (kids != null) {
            for (int i = 0; i < kids.length; i++) {
                deleteTree(kids[i]);
            }
        }
        file.delete();
    }
}
