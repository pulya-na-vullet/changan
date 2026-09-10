package com.changanhub.quickbar;

import android.content.Context;
import android.os.storage.StorageManager;
import android.os.storage.StorageVolume;

import java.io.File;
import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;

/** Removable USB/SD volumes on a Feiyu head unit. */
public final class UsbStorage {
    private UsbStorage() {
    }

    public static List<File> roots(Context context) {
        List<File> found = new ArrayList<>();
        addStorageVolumes(context, found);
        addAppVolumeRoots(context, found);
        addIfDir(found, new File("/mnt/media_rw"));
        addIfDir(found, new File("/mnt/usb_storage"));
        addIfDir(found, new File("/mnt/usbhost"));
        addIfDir(found, new File("/mnt/udisk"));
        addIfDir(found, new File("/storage/usb0"));
        addIfDir(found, new File("/storage/usbotg"));
        addIfDir(found, new File("/storage/udisk"));
        addIfDir(found, new File("/storage/usbdisk"));
        addIfDir(found, new File("/sdcard/Download"));
        addIfDir(found, new File("/storage/emulated/0/Download"));
        File storage = new File("/storage");
        File[] kids = storage.listFiles();
        if (kids != null) {
            for (int i = 0; i < kids.length; i++) {
                File child = kids[i];
                String name = child.getName();
                if ("emulated".equals(name) || "self".equals(name)
                        || "sdcard0".equals(name) || "enc_emulated".equals(name)) {
                    continue;
                }
                addIfDir(found, child);
            }
        }
        return uniqueExisting(found);
    }

    private static void addAppVolumeRoots(Context context, List<File> found) {
        try {
            File[] dirs = context.getExternalFilesDirs(null);
            if (dirs == null) {
                return;
            }
            for (int i = 0; i < dirs.length; i++) {
                File dir = dirs[i];
                if (dir == null) {
                    continue;
                }
                addIfDir(found, dir);
                File vol = dir;
                for (int up = 0; up < 4 && vol != null; up++) {
                    vol = vol.getParentFile();
                }
                if (vol != null) {
                    String path = vol.getAbsolutePath();
                    if (path.contains("/emulated/") || path.endsWith("/emulated")
                            || path.contains("sdcard0")) {
                        addIfDir(found, new File(vol, "Download"));
                    } else {
                        addIfDir(found, vol);
                    }
                }
            }
        } catch (Exception ignored) {
        }
    }

    public static List<File> apkFiles(Context context) {
        List<File> apks = new ArrayList<>();
        List<File> volumes = roots(context);
        for (int i = 0; i < volumes.size(); i++) {
            walk(volumes.get(i), apks, 0);
        }
        return apks;
    }

    private static void addStorageVolumes(Context context, List<File> found) {
        try {
            StorageManager sm = (StorageManager) context.getSystemService(Context.STORAGE_SERVICE);
            if (sm == null) {
                return;
            }
            List<StorageVolume> volumes = sm.getStorageVolumes();
            Method getPath = StorageVolume.class.getMethod("getPath");
            for (int i = 0; i < volumes.size(); i++) {
                StorageVolume volume = volumes.get(i);
                if (volume.isPrimary() && !volume.isRemovable()) {
                    continue;
                }
                try {
                    Object path = getPath.invoke(volume);
                    if (path instanceof String) {
                        addIfDir(found, new File((String) path));
                    }
                } catch (Exception ignored) {
                }
            }
        } catch (Exception ignored) {
        }
    }

    private static void walk(File dir, List<File> out, int depth) {
        if (dir == null || depth > 5) {
            return;
        }
        File[] files = dir.listFiles();
        if (files == null) {
            return;
        }
        for (int i = 0; i < files.length; i++) {
            File file = files[i];
            if (file.isDirectory()) {
                String name = file.getName();
                if (name.startsWith(".") || "Android".equals(name) || "LOST.DIR".equals(name)
                        || "System Volume Information".equalsIgnoreCase(name)) {
                    continue;
                }
                walk(file, out, depth + 1);
            } else if (file.getName().toLowerCase(Locale.US).endsWith(".apk") && file.length() > 0) {
                out.add(file);
            }
        }
    }

    private static void addIfDir(List<File> found, File dir) {
        if (dir != null && dir.isDirectory()) {
            found.add(dir);
        }
    }

    private static List<File> uniqueExisting(List<File> input) {
        Set<String> seen = new LinkedHashSet<>();
        List<File> out = new ArrayList<>();
        for (int i = 0; i < input.size(); i++) {
            File dir = input.get(i);
            String key;
            try {
                key = dir.getCanonicalPath();
            } catch (Exception e) {
                key = dir.getAbsolutePath();
            }
            if (seen.add(key)) {
                out.add(dir);
            }
        }
        return out;
    }
}
