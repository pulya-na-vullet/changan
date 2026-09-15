package com.changanhub.quickbar;

import android.content.Context;
import android.os.Environment;
import android.os.storage.StorageManager;
import android.os.storage.StorageVolume;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileReader;
import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;

/**
 * APK sources on a Feiyu head unit: the USB port and the HU's own storage.
 * Same roots as Lamore Player ({@code UsbMedia}).
 */
public final class UsbStorage {
    public static final String ID_USB = "usb";
    public static final String ID_MEMORY = "memory";

    private UsbStorage() {
    }

    public static final class Volume {
        public final String id;
        public final File root;
        public final boolean removable;
        public final String label;

        Volume(String id, File root, boolean removable, String label) {
            this.id = id;
            this.root = root;
            this.removable = removable;
            this.label = label;
        }
    }

    /** USB sticks in the HU port, excluding internal /sdcard. */
    public static List<File> usbRoots(Context context) {
        List<File> found = new ArrayList<>();
        addStorageVolumes(context, found, true);
        addAppVolumeRoots(context, found, true);
        addFromProcMounts(found);
        addWithChildren(found, new File("/mnt/media_rw"));
        addWithChildren(found, new File("/mnt/usb_storage"));
        addIfDir(found, new File("/mnt/usbhost"));
        addIfDir(found, new File("/mnt/udisk"));
        addIfDir(found, new File("/storage/usb0"));
        addIfDir(found, new File("/storage/usbotg"));
        addIfDir(found, new File("/storage/udisk"));
        addIfDir(found, new File("/storage/usbdisk"));
        addIfDir(found, new File("/mnt/usb"));
        addIfDir(found, new File("/storage/usb"));
        addIfDir(found, new File("/storage/sdcard1"));
        addIfDir(found, new File("/mnt/external_sd"));
        File storage = new File("/storage");
        File[] kids = kids(storage);
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
        return dropParents(uniqueExisting(found));
    }

    /** Internal HU storage (not the USB port). */
    public static List<File> memoryRoots() {
        List<File> found = new ArrayList<>();
        try {
            addIfDir(found, Environment.getExternalStorageDirectory());
        } catch (Exception ignored) {
        }
        try {
            addIfDir(found, Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS));
        } catch (Exception ignored) {
        }
        addIfDir(found, new File("/storage/emulated/0"));
        addIfDir(found, new File("/storage/emulated/0/Download"));
        addIfDir(found, new File("/sdcard"));
        addIfDir(found, new File("/sdcard/Download"));
        addIfDir(found, new File("/storage/sdcard0"));
        addIfDir(found, new File("/mnt/sdcard"));
        return uniqueExisting(found);
    }

    /** Sources the user can pick: each USB volume, plus one «Память ГУ». */
    public static List<Volume> volumes(Context context) {
        List<Volume> out = new ArrayList<>();
        List<File> sticks = usbRoots(context);
        if (sticks.isEmpty()) {
            out.add(new Volume(ID_USB, null, true, "USB"));
        } else if (sticks.size() == 1) {
            out.add(new Volume(ID_USB + ":" + canon(sticks.get(0)), sticks.get(0), true, "USB"));
        } else {
            for (int i = 0; i < sticks.size(); i++) {
                File root = sticks.get(i);
                out.add(new Volume(ID_USB + ":" + canon(root), root, true, "USB · " + root.getName()));
            }
        }
        List<File> memory = memoryRoots();
        File memRoot = memory.isEmpty() ? null : memory.get(0);
        out.add(new Volume(ID_MEMORY, memRoot, false, "Память ГУ"));
        return out;
    }

    public static Volume volumeById(Context context, String id) {
        List<Volume> vols = volumes(context);
        if (id != null) {
            for (int i = 0; i < vols.size(); i++) {
                if (id.equals(vols.get(i).id)) {
                    return vols.get(i);
                }
            }
            if (id.startsWith(ID_USB)) {
                for (int i = 0; i < vols.size(); i++) {
                    if (vols.get(i).removable) {
                        return vols.get(i);
                    }
                }
            }
        }
        for (int i = 0; i < vols.size(); i++) {
            Volume v = vols.get(i);
            if (v.removable && v.root != null) {
                return v;
            }
        }
        return vols.get(vols.size() - 1);
    }

    public static List<File> apkFiles(Context context) {
        return apkFiles(context, volumeById(context, null));
    }

    public static List<File> apkFiles(Context context, Volume volume) {
        List<File> apks = new ArrayList<>();
        List<File> roots;
        if (volume == null || !volume.removable) {
            roots = memoryRoots();
        } else if (volume.root == null) {
            roots = new ArrayList<>();
        } else {
            roots = new ArrayList<>();
            roots.add(volume.root);
        }
        for (int i = 0; i < roots.size(); i++) {
            walk(roots.get(i), apks, 0);
        }
        return uniqueFiles(apks);
    }

    /** @deprecated use {@link #usbRoots} / {@link #memoryRoots} */
    public static List<File> roots(Context context) {
        List<File> found = new ArrayList<>();
        found.addAll(usbRoots(context));
        found.addAll(memoryRoots());
        return uniqueExisting(found);
    }

    private static void addAppVolumeRoots(Context context, List<File> found, boolean usbOnly) {
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
                File vol = dir;
                for (int up = 0; up < 4 && vol != null; up++) {
                    vol = vol.getParentFile();
                }
                if (vol == null) {
                    continue;
                }
                boolean memory = isMemoryPath(vol.getAbsolutePath());
                if (usbOnly && memory) {
                    continue;
                }
                if (!usbOnly && !memory) {
                    continue;
                }
                addIfDir(found, vol);
            }
        } catch (Exception ignored) {
        }
    }

    private static void addStorageVolumes(Context context, List<File> found, boolean usbOnly) {
        try {
            StorageManager sm = (StorageManager) context.getSystemService(Context.STORAGE_SERVICE);
            if (sm == null) {
                return;
            }
            List<StorageVolume> volumes = sm.getStorageVolumes();
            Method getPath = optionalMethod("getPath");
            Method getPathFile = optionalMethod("getPathFile");
            Method getDirectory = optionalMethod("getDirectory");
            for (int i = 0; i < volumes.size(); i++) {
                File path = volumePath(volumes.get(i), getPath, getPathFile, getDirectory);
                if (path == null) {
                    continue;
                }
                boolean memory = isMemoryPath(path.getAbsolutePath());
                if (usbOnly && memory) {
                    continue;
                }
                if (!usbOnly && !memory) {
                    continue;
                }
                addIfDir(found, path);
            }
        } catch (Exception ignored) {
        }
    }

    private static Method optionalMethod(String name) {
        try {
            return StorageVolume.class.getMethod(name);
        } catch (Exception e) {
            return null;
        }
    }

    private static File volumePath(
            StorageVolume volume, Method getPath, Method getPathFile, Method getDirectory) {
        if (getDirectory != null) {
            try {
                Object dir = getDirectory.invoke(volume);
                if (dir instanceof File) {
                    return (File) dir;
                }
            } catch (Exception ignored) {
            }
        }
        if (getPathFile != null) {
            try {
                Object dir = getPathFile.invoke(volume);
                if (dir instanceof File) {
                    return (File) dir;
                }
            } catch (Exception ignored) {
            }
        }
        if (getPath != null) {
            try {
                Object path = getPath.invoke(volume);
                if (path instanceof String && ((String) path).length() > 0) {
                    return new File((String) path);
                }
            } catch (Exception ignored) {
            }
        }
        return null;
    }

    private static void addFromProcMounts(List<File> found) {
        BufferedReader reader = null;
        try {
            reader = new BufferedReader(new FileReader("/proc/mounts"));
            String line;
            while ((line = reader.readLine()) != null) {
                String[] parts = line.split(" ");
                if (parts.length < 3) {
                    continue;
                }
                String mount = parts[1];
                String fs = parts[2];
                if (isMemoryPath(mount) || mount.startsWith("/mnt/runtime")
                        || mount.startsWith("/mnt/pass_through") || mount.contains("/Android/")) {
                    continue;
                }
                boolean usbFs = "vfat".equals(fs) || "exfat".equals(fs) || "texfat".equals(fs)
                        || "fuseblk".equals(fs) || "ntfs".equals(fs) || "sdcardfs".equals(fs)
                        || "fuse".equals(fs) || "sdfat".equals(fs);
                boolean usbPath = mount.contains("media_rw") || mount.contains("usb")
                        || mount.contains("udisk") || mount.contains("otg")
                        || mount.matches(".*/storage/[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}.*");
                if (usbFs && usbPath) {
                    addIfDir(found, new File(mount));
                }
            }
        } catch (Exception ignored) {
        } finally {
            if (reader != null) {
                try {
                    reader.close();
                } catch (Exception ignored) {
                }
            }
        }
    }

    private static void addWithChildren(List<File> found, File dir) {
        addIfDir(found, dir);
        File[] kids = kids(dir);
        if (kids == null) {
            return;
        }
        for (int i = 0; i < kids.length; i++) {
            File child = kids[i];
            if (child.isDirectory() && !child.getName().startsWith(".")) {
                addIfDir(found, child);
            }
        }
    }

    private static File[] kids(File dir) {
        if (dir == null) {
            return null;
        }
        File[] files = dir.listFiles();
        if (files != null) {
            return files;
        }
        String[] names = dir.list();
        if (names == null) {
            return null;
        }
        File[] out = new File[names.length];
        for (int i = 0; i < names.length; i++) {
            out[i] = new File(dir, names[i]);
        }
        return out;
    }

    private static void walk(File dir, List<File> out, int depth) {
        if (dir == null || depth > 6) {
            return;
        }
        File[] files = kids(dir);
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

    static boolean isMemoryPath(String path) {
        if (path == null) {
            return false;
        }
        String lower = path.toLowerCase(Locale.ROOT);
        return lower.contains("/emulated/") || lower.endsWith("/emulated")
                || lower.equals("/sdcard") || lower.endsWith("/sdcard")
                || lower.contains("/sdcard0");
    }

    private static void addIfDir(List<File> found, File dir) {
        if (dir != null && dir.isDirectory()) {
            found.add(dir);
        }
    }

    private static String canon(File dir) {
        try {
            return dir.getCanonicalPath();
        } catch (Exception e) {
            return dir.getAbsolutePath();
        }
    }

    private static List<File> uniqueExisting(List<File> input) {
        Set<String> seen = new LinkedHashSet<>();
        List<File> out = new ArrayList<>();
        for (int i = 0; i < input.size(); i++) {
            File dir = input.get(i);
            if (seen.add(canon(dir))) {
                out.add(dir);
            }
        }
        return out;
    }

    private static List<File> uniqueFiles(List<File> input) {
        Set<String> seen = new LinkedHashSet<>();
        List<File> out = new ArrayList<>();
        for (int i = 0; i < input.size(); i++) {
            File file = input.get(i);
            if (seen.add(canon(file))) {
                out.add(file);
            }
        }
        return out;
    }

    /** Prefer /mnt/media_rw/ABCD over the parent /mnt/media_rw. */
    private static List<File> dropParents(List<File> dirs) {
        List<File> out = new ArrayList<>();
        for (int i = 0; i < dirs.size(); i++) {
            String a = canon(dirs.get(i));
            boolean parent = false;
            for (int j = 0; j < dirs.size(); j++) {
                if (i == j) {
                    continue;
                }
                String b = canon(dirs.get(j));
                if (b.startsWith(a + "/")) {
                    parent = true;
                    break;
                }
            }
            if (!parent) {
                out.add(dirs.get(i));
            }
        }
        return out;
    }
}
