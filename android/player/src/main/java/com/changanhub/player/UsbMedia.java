package com.changanhub.player;

import android.content.Context;
import android.os.storage.StorageManager;
import android.os.storage.StorageVolume;

import java.io.File;
import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;

/** Removable USB/SD volumes on a Feiyu head unit, same roots as QuickBar. */
public final class UsbMedia {
    private UsbMedia() {
    }

    public static class Entry {
        public File file;
        public boolean directory;
        public boolean audio;
        public boolean video;
        public String label;
        public String meta;
    }

    public static List<File> roots(Context context) {
        List<File> found = new ArrayList<>();
        addStorageVolumes(context, found);
        addIfDir(found, new File("/mnt/media_rw"));
        addIfDir(found, new File("/mnt/usb_storage"));
        addIfDir(found, new File("/mnt/usbhost"));
        addIfDir(found, new File("/mnt/udisk"));
        addIfDir(found, new File("/storage/usb0"));
        addIfDir(found, new File("/storage/usbotg"));
        addIfDir(found, new File("/storage/udisk"));
        addIfDir(found, new File("/storage/usbdisk"));
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
        try {
            File[] dirs = context.getExternalFilesDirs(null);
            if (dirs != null) {
                for (int i = 0; i < dirs.length; i++) {
                    File dir = dirs[i];
                    if (dir == null) {
                        continue;
                    }
                    File vol = dir;
                    for (int up = 0; up < 4 && vol != null; up++) {
                        vol = vol.getParentFile();
                    }
                    if (vol != null) {
                        String path = vol.getAbsolutePath();
                        if (!path.contains("/emulated/") && !path.endsWith("/emulated")) {
                            addIfDir(found, vol);
                        }
                    }
                }
            }
        } catch (Exception ignored) {
        }
        return uniqueExisting(found);
    }

    public static List<Entry> list(File dir) {
        List<Entry> out = new ArrayList<>();
        if (dir == null || !dir.isDirectory()) {
            return out;
        }
        File[] files = dir.listFiles();
        if (files == null) {
            return out;
        }
        for (int i = 0; i < files.length; i++) {
            File file = files[i];
            String name = file.getName();
            if (name.startsWith(".") || "Android".equals(name) || "LOST.DIR".equals(name)
                    || "System Volume Information".equalsIgnoreCase(name)) {
                continue;
            }
            if (file.isDirectory()) {
                Entry e = new Entry();
                e.file = file;
                e.directory = true;
                e.label = name;
                e.meta = "папка";
                out.add(e);
            } else if (MediaTypes.isMedia(name) && file.length() > 0) {
                Entry e = new Entry();
                e.file = file;
                e.audio = MediaTypes.isAudio(name);
                e.video = MediaTypes.isVideo(name);
                e.label = name;
                e.meta = (e.video ? "видео · " : "аудио · ") + (file.length() / 1024) + " КБ";
                out.add(e);
            }
        }
        Collections.sort(out, new Comparator<Entry>() {
            @Override
            public int compare(Entry a, Entry b) {
                if (a.directory != b.directory) {
                    return a.directory ? -1 : 1;
                }
                return a.label.toLowerCase(Locale.ROOT).compareTo(b.label.toLowerCase(Locale.ROOT));
            }
        });
        return out;
    }

    public static List<File> scan(File root, boolean video) {
        List<File> out = new ArrayList<>();
        walk(root, out, 0, video);
        return out;
    }

    private static void walk(File dir, List<File> out, int depth, boolean video) {
        if (dir == null || depth > 6) {
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
                if (name.startsWith(".") || "Android".equals(name) || "LOST.DIR".equals(name)) {
                    continue;
                }
                walk(file, out, depth + 1, video);
            } else if (file.length() > 0) {
                if (video && MediaTypes.isVideo(file.getName())) {
                    out.add(file);
                } else if (!video && MediaTypes.isAudio(file.getName())) {
                    out.add(file);
                }
            }
        }
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
