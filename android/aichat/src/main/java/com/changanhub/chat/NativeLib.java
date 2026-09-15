package com.changanhub.chat;

import android.content.Context;
import android.os.Build;

import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.util.zip.ZipEntry;
import java.util.zip.ZipFile;

/**
 * Feiyu often skips extracting native .so from the APK. Copy RHVoice out of
 * {@code lib/<abi>/} and {@code System.load} the real path.
 */
public final class NativeLib {
    private NativeLib() {
    }

    public static File extract(Context context, String name) throws Exception {
        String fileName = "lib" + name + ".so";
        File dest = new File(context.getDir("nativelib", Context.MODE_PRIVATE), fileName);
        File packed = new File(context.getApplicationInfo().nativeLibraryDir, fileName);
        if (packed.isFile() && packed.length() > 1000) {
            return packed;
        }
        String[] abis = Build.SUPPORTED_ABIS;
        ZipFile zip = new ZipFile(context.getPackageCodePath());
        try {
            ZipEntry entry = null;
            for (int i = 0; i < abis.length; i++) {
                ZipEntry cand = zip.getEntry("lib/" + abis[i] + "/" + fileName);
                if (cand != null) {
                    entry = cand;
                    break;
                }
            }
            if (entry == null) {
                entry = zip.getEntry("lib/arm64-v8a/" + fileName);
            }
            if (entry == null) {
                entry = zip.getEntry("lib/armeabi-v7a/" + fileName);
            }
            if (entry == null) {
                throw new Exception("в APK нет " + fileName);
            }
            InputStream in = zip.getInputStream(entry);
            try {
                FileOutputStream out = new FileOutputStream(dest);
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
        } finally {
            zip.close();
        }
        if (!dest.isFile() || dest.length() < 1000) {
            throw new Exception("не скопировалась " + fileName);
        }
        return dest;
    }
}
