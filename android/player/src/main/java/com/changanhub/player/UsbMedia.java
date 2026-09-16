package com.changanhub.player;

import android.content.Context;
import android.os.Environment;
import android.os.storage.StorageManager;
import android.os.storage.StorageVolume;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileReader;
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
        public boolean volume;
        public boolean removable;
        public String label;
        public String meta;
        public String artist = "";
        public String album = "";
        public int durationMs;
    }

    public static List<File> roots(Context context) {
        List<File> found = new ArrayList<>();
        addStorageVolumes(context, found);
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
        return collapseSameName(dropParents(uniqueExisting(found)));
    }

    public static List<File> memoryRoots() {
        List<File> found = new ArrayList<>();
        try {
            addIfDir(found, Environment.getExternalStorageDirectory());
        } catch (Exception ignored) {
        }
        addIfDir(found, new File("/storage/emulated/0"));
        addIfDir(found, new File("/sdcard"));
        addIfDir(found, new File("/storage/sdcard0"));
        addIfDir(found, new File("/mnt/sdcard"));
        return uniqueExisting(found);
    }

    public static List<Entry> volumes(Context context) {
        List<Entry> out = new ArrayList<>();
        Set<String> seen = new LinkedHashSet<>();
        List<File> sticks = roots(context);
        for (int i = 0; i < sticks.size(); i++) {
            File root = sticks.get(i);
            String key = canon(root);
            if (!seen.add(key) || isMemoryPath(key)) {
                continue;
            }
            out.add(volumeEntry(root, true));
        }
        List<File> memory = memoryRoots();
        for (int i = 0; i < memory.size(); i++) {
            File root = memory.get(i);
            String key = canon(root);
            if (!seen.add(key)) {
                continue;
            }
            out.add(volumeEntry(root, false));
        }
        return out;
    }

    public static void fillTags(Entry e) {
        if (e == null || e.file == null || e.directory) {
            return;
        }
        Tags tags = Tags.read(e.file);
        if (tags.title.length() > 0) {
            e.label = tags.title;
        }
        e.artist = tags.artist;
        e.album = tags.album;
        e.durationMs = tags.durationMs;
        String kind = e.video ? "видео" : "аудио";
        String who = e.artist.length() > 0 ? e.artist : (e.file.getParent() == null ? "" : e.file.getParent());
        String clock = e.durationMs > 0 ? " · " + Tags.clock(e.durationMs) : "";
        String res = "";
        if (e.video && tags.width > 0 && tags.height > 0) {
            res = " · " + tags.width + "×" + tags.height;
        }
        e.meta = kind + " · " + who + clock + res;
    }

    public static void sortEntries(List<Entry> rows, int mode) {
        Collections.sort(rows, new Comparator<Entry>() {
            @Override
            public int compare(Entry a, Entry b) {
                if (a.directory != b.directory) {
                    return a.directory ? -1 : 1;
                }
                String left;
                String right;
                if (mode == 1) {
                    left = a.artist;
                    right = b.artist;
                } else if (mode == 2) {
                    left = a.album;
                    right = b.album;
                } else if (mode == 3) {
                    left = a.label;
                    right = b.label;
                } else {
                    String pa = a.file != null && a.file.getParent() != null ? a.file.getParent() : "";
                    String pb = b.file != null && b.file.getParent() != null ? b.file.getParent() : "";
                    int dirs = pa.compareToIgnoreCase(pb);
                    if (dirs != 0) {
                        return dirs;
                    }
                    left = a.label;
                    right = b.label;
                }
                if (left == null) {
                    left = "";
                }
                if (right == null) {
                    right = "";
                }
                int cmp = left.compareToIgnoreCase(right);
                if (cmp != 0) {
                    return cmp;
                }
                return a.label.compareToIgnoreCase(b.label);
            }
        });
    }

    public static List<Entry> list(File dir) {
        return list(dir, true, true);
    }

    public static List<Entry> list(File dir, boolean wantAudio, boolean wantVideo) {
        List<Entry> out = new ArrayList<>();
        File readable = bestReadable(dir);
        if (readable == null) {
            return out;
        }
        File[] files = kids(readable);
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
            if (looksLikeDirectory(file)) {
                Entry e = new Entry();
                e.file = file;
                e.directory = true;
                e.label = name;
                e.meta = "папка";
                out.add(e);
            } else if (MediaTypes.isMedia(name)) {
                boolean audio = MediaTypes.isAudio(name);
                boolean video = MediaTypes.isVideo(name);
                if ((audio && !wantAudio) || (video && !wantVideo)) {
                    continue;
                }
                if (!audio && !video) {
                    continue;
                }
                Entry e = new Entry();
                e.file = file;
                e.audio = audio;
                e.video = video;
                e.label = name;
                fillTags(e);
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

    public static List<Entry> scanEntries(File root, boolean video) {
        List<File> files = scan(root, video);
        List<Entry> out = new ArrayList<>();
        for (int i = 0; i < files.size(); i++) {
            File file = files.get(i);
            Entry e = new Entry();
            e.file = file;
            e.audio = !video;
            e.video = video;
            e.label = file.getName();
            fillTags(e);
            out.add(e);
        }
        return out;
    }

    public static List<Entry> scanAll(Context context, boolean video) {
        List<Entry> out = new ArrayList<>();
        Set<String> seen = new LinkedHashSet<>();
        List<File> volumes = roots(context);
        List<File> memory = memoryRoots();
        for (int i = 0; i < memory.size(); i++) {
            volumes.add(memory.get(i));
        }
        volumes = uniqueExisting(volumes);
        for (int i = 0; i < volumes.size(); i++) {
            List<Entry> chunk = scanEntries(volumes.get(i), video);
            for (int j = 0; j < chunk.size(); j++) {
                Entry e = chunk.get(j);
                String key = e.file == null ? "" : e.file.getAbsolutePath();
                if (seen.add(key)) {
                    out.add(e);
                }
            }
        }
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
        File readable = depth == 0 ? bestReadable(dir) : dir;
        if (readable == null) {
            return;
        }
        File[] files = kids(readable);
        if (files == null) {
            return;
        }
        for (int i = 0; i < files.length; i++) {
            File file = files[i];
            String name = file.getName();
            if (name.startsWith(".")) {
                continue;
            }
            if (looksLikeDirectory(file)) {
                if ("Android".equals(name) || "LOST.DIR".equals(name)
                        || "System Volume Information".equalsIgnoreCase(name)) {
                    continue;
                }
                walk(file, out, depth + 1, video);
            } else if (video && MediaTypes.isVideo(name)) {
                out.add(file);
            } else if (!video && MediaTypes.isAudio(name)) {
                out.add(file);
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
            Method getPath = optionalMethod("getPath");
            Method getPathFile = optionalMethod("getPathFile");
            Method getDirectory = optionalMethod("getDirectory");
            for (int i = 0; i < volumes.size(); i++) {
                File path = volumePath(volumes.get(i), getPath, getPathFile, getDirectory);
                if (path == null || isMemoryPath(path.getAbsolutePath())) {
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
        String[] names = dir.list();
        if (names == null) {
            return dir.listFiles();
        }
        File[] out = new File[names.length];
        for (int i = 0; i < names.length; i++) {
            out[i] = new File(dir, names[i]);
        }
        return out;
    }

    static boolean looksLikeDirectory(File file) {
        if (file == null) {
            return false;
        }
        if (file.isDirectory()) {
            return true;
        }
        if (file.isFile()) {
            return false;
        }
        return file.list() != null;
    }

    /**
     * Kernel USB folder names on Feiyu often are {@code usb0}/{@code UDISK},
     * not the FUSE UUID {@code A678-ED41}. Guess those names when {@code list()}
     * on {@code /mnt/media_rw} is empty or denied.
     */
    private static final String[] KERNEL_VOL_GUESSES = {
            "usb0", "usb1", "usb2", "usb3",
            "udisk", "UDISK", "UDISK0", "UDISK1", "udisk0", "udisk1",
            "USB_DISK0", "USB_DISK1", "USB_DISK2",
            "usbdisk", "usbdisk1", "usbotg", "otg",
            "usbhost0", "usbhost1", "sda", "sda1", "sdb1"
    };

    static File bestReadable(File dir) {
        if (dir == null) {
            return null;
        }
        String name = dir.getName();
        File[] kernelNamed = {
                new File("/mnt/media_rw", name),
                new File("/mnt/usb_storage", name),
                new File("/mnt/usbhost", name),
                new File("/mnt/udisk", name),
                new File("/storage/usb0", name),
                new File("/storage/usbotg", name),
                new File("/storage/udisk", name),
        };
        File listed = firstListed(kernelNamed);
        if (listed != null) {
            return listed;
        }
        File overlap = kernelVolumeSharingNames(dir);
        if (overlap != null) {
            return overlap;
        }
        if (looksLikeDirectory(dir)) {
            String[] names = dir.list();
            if (names != null && names.length > 0) {
                return dir;
            }
        }
        File emptyOk = firstDir(kernelNamed);
        File anyDir = looksLikeDirectory(dir) ? dir : emptyOk;
        return emptyOk != null ? emptyOk : anyDir;
    }

    private static File firstListed(File[] candidates) {
        for (int i = 0; i < candidates.length; i++) {
            File c = candidates[i];
            if (c == null || !looksLikeDirectory(c)) {
                continue;
            }
            String[] names = c.list();
            if (names != null && names.length > 0) {
                return c;
            }
        }
        return null;
    }

    private static File firstDir(File[] candidates) {
        for (int i = 0; i < candidates.length; i++) {
            File c = candidates[i];
            if (c != null && looksLikeDirectory(c)) {
                return c;
            }
        }
        return null;
    }

    /**
     * FUSE {@code /storage/UUID} and kernel {@code /mnt/media_rw/usb0} list the
     * same song names. Prefer the kernel folder so copy/open does not remap UUID.
     */
    static File kernelVolumeSharingNames(File dir) {
        if (dir == null) {
            return null;
        }
        String[] want = dir.list();
        if (want == null || want.length == 0) {
            return null;
        }
        Set<String> names = new LinkedHashSet<>();
        int cap = Math.min(want.length, 24);
        for (int i = 0; i < cap; i++) {
            String n = want[i];
            if (n == null || n.length() == 0 || n.startsWith(".")) {
                continue;
            }
            if ("Android".equals(n) || "LOST.DIR".equals(n)
                    || "System Volume Information".equalsIgnoreCase(n)) {
                continue;
            }
            names.add(n);
        }
        if (names.isEmpty()) {
            return null;
        }
        String self = canon(dir);
        File[] roots = kernelVolumeRoots();
        File best = null;
        int bestHits = 0;
        for (int i = 0; i < roots.length; i++) {
            File root = roots[i];
            if (root == null) {
                continue;
            }
            if (self.equals(canon(root))) {
                continue;
            }
            String[] have = root.list();
            if (have == null || have.length == 0) {
                continue;
            }
            int hits = 0;
            int check = Math.min(have.length, 40);
            for (int j = 0; j < check; j++) {
                if (names.contains(have[j])) {
                    hits++;
                }
            }
            if (hits > bestHits) {
                bestHits = hits;
                best = root;
            }
        }
        return bestHits > 0 ? best : null;
    }

    static File[] kernelVolumeRoots() {
        List<File> found = new ArrayList<>();
        addWithChildren(found, new File("/mnt/media_rw"));
        addWithChildren(found, new File("/mnt/usb_storage"));
        addIfDir(found, new File("/mnt/usbhost"));
        addIfDir(found, new File("/mnt/udisk"));
        addIfDir(found, new File("/mnt/usb"));
        addIfDir(found, new File("/storage/usb0"));
        addIfDir(found, new File("/storage/usbotg"));
        addIfDir(found, new File("/storage/udisk"));
        addIfDir(found, new File("/storage/usbdisk"));
        String[] bases = {"/mnt/media_rw", "/mnt/usb_storage", "/mnt/usbhost"};
        for (int b = 0; b < bases.length; b++) {
            for (int g = 0; g < KERNEL_VOL_GUESSES.length; g++) {
                addIfDir(found, new File(bases[b], KERNEL_VOL_GUESSES[g]));
            }
        }
        addFromProcMounts(found);
        List<File> unique = uniqueExisting(found);
        List<File> out = new ArrayList<>();
        for (int i = 0; i < unique.size(); i++) {
            File dir = unique.get(i);
            if (isFuseUuidPath(dir.getAbsolutePath())) {
                continue;
            }
            out.add(dir);
        }
        return out.toArray(new File[0]);
    }

    static boolean isFuseUuidPath(String path) {
        if (path == null || path.contains("/mnt/")) {
            return false;
        }
        return path.contains("/storage/") && volumeName(path) != null;
    }

    static String volumeRelative(File file) {
        if (file == null) {
            return "";
        }
        String path = file.getAbsolutePath().replace('\\', '/');
        String uuid = volumeName(path);
        if (uuid != null) {
            String needle = "/" + uuid;
            int idx = path.indexOf(needle);
            if (idx >= 0) {
                String rest = path.substring(idx + needle.length());
                if (rest.startsWith("/")) {
                    rest = rest.substring(1);
                }
                return rest;
            }
        }
        String[] prefixes = {
                "/mnt/media_rw/", "/mnt/usb_storage/", "/mnt/usbhost/", "/mnt/udisk/",
                "/mnt/usb/", "/storage/usb0/", "/storage/usbotg/", "/storage/udisk/",
                "/storage/usbdisk/", "/storage/usb/", "/storage/"
        };
        for (int i = 0; i < prefixes.length; i++) {
            if (!path.startsWith(prefixes[i])) {
                continue;
            }
            String rest = path.substring(prefixes[i].length());
            int slash = rest.indexOf('/');
            if (slash >= 0) {
                return rest.substring(slash + 1);
            }
            return rest;
        }
        return file.getName() == null ? "" : file.getName();
    }

    private static File pickRicher(File a, File b) {
        int na = listCount(a);
        int nb = listCount(b);
        if (nb > na) {
            return b;
        }
        if (na > nb) {
            return a;
        }
        String pb = b.getAbsolutePath();
        if (pb.contains("/media_rw/") || pb.contains("/usb_storage/")) {
            return b;
        }
        return a;
    }

    private static int listCount(File dir) {
        if (dir == null) {
            return -1;
        }
        String[] names = dir.list();
        return names == null ? -1 : names.length;
    }

    private static List<File> collapseSameName(List<File> dirs) {
        java.util.LinkedHashMap<String, File> byName = new java.util.LinkedHashMap<>();
        for (int i = 0; i < dirs.size(); i++) {
            File best = bestReadable(dirs.get(i));
            if (best == null) {
                continue;
            }
            String name = best.getName();
            File prev = byName.get(name);
            byName.put(name, prev == null ? best : pickRicher(prev, best));
        }
        return new ArrayList<>(byName.values());
    }

    public static File playableFile(File file) {
        if (file == null) {
            return null;
        }
        File[] cands = rankedPathCandidates(file);
        File readable = null;
        File withBytes = null;
        for (int i = 0; i < cands.length; i++) {
            File cand = cands[i];
            if (cand == null || looksLikeDirectory(cand)) {
                continue;
            }
            if (readable == null) {
                readable = cand;
            }
            long size = 0;
            try {
                size = cand.length();
            } catch (Exception ignored) {
            }
            boolean opens = canOpen(cand);
            if (size <= 0 && !opens) {
                continue;
            }
            if (withBytes == null) {
                withBytes = cand;
            }
            String path = cand.getAbsolutePath();
            if (path.contains("/media_rw/") || path.contains("/usb_storage/")) {
                return cand;
            }
        }
        return withBytes != null ? withBytes : (readable != null ? readable : file);
    }

    static File[] pathCandidates(File file) {
        java.util.LinkedHashSet<String> seen = new LinkedHashSet<>();
        java.util.ArrayList<File> out = new ArrayList<>();
        addCandidate(out, seen, file);
        if (file == null) {
            return out.toArray(new File[0]);
        }
        try {
            addCandidate(out, seen, file.getCanonicalFile());
        } catch (Exception ignored) {
        }
        File parent = file.getParentFile();
        if (parent != null) {
            File bestParent = bestReadable(parent);
            if (bestParent != null) {
                addCandidate(out, seen, new File(bestParent, file.getName()));
            }
        }
        String path = file.getAbsolutePath();
        String uuid = volumeName(path);
        String rel = volumeRelative(file);
        if (uuid != null) {
            String needle = "/" + uuid;
            int idx = path.indexOf(needle);
            if (idx >= 0) {
                String rest = path.substring(idx + needle.length());
                addCandidate(out, seen, new File("/mnt/media_rw/" + uuid + rest));
                addCandidate(out, seen, new File("/storage/" + uuid + rest));
                addCandidate(out, seen, new File("/mnt/usb_storage/" + uuid + rest));
                addCandidate(out, seen, new File("/mnt/usbhost/" + uuid + rest));
            }
        }
        File[] kernels = kernelVolumeRoots();
        for (int i = 0; i < kernels.length; i++) {
            if (rel != null && rel.length() > 0) {
                addCandidate(out, seen, new File(kernels[i], rel));
            }
            addCandidate(out, seen, new File(kernels[i], file.getName()));
        }
        return out.toArray(new File[0]);
    }

    /**
     * Slow path for copy: guess kernel folder names and search by filename.
     * Not used while building the playlist.
     */
    static File[] expandKernelCandidates(File file) {
        java.util.LinkedHashSet<String> seen = new LinkedHashSet<>();
        java.util.ArrayList<File> out = new ArrayList<>();
        File[] cheap = rankedPathCandidates(file);
        for (int i = 0; i < cheap.length; i++) {
            addCandidate(out, seen, cheap[i]);
        }
        if (file == null) {
            return out.toArray(new File[0]);
        }
        String rel = volumeRelative(file);
        String name = file.getName();
        String uuid = volumeName(file.getAbsolutePath());
        String[] bases = {
                "/mnt/media_rw", "/mnt/usb_storage", "/mnt/usbhost", "/mnt/udisk"
        };
        for (int b = 0; b < bases.length; b++) {
            if (rel.length() > 0) {
                addCandidate(out, seen, new File(bases[b], rel));
            }
            addCandidate(out, seen, new File(bases[b], name));
            if (uuid != null) {
                addCandidate(out, seen, new File(bases[b] + "/" + uuid, rel));
                addCandidate(out, seen, new File(bases[b] + "/" + uuid, name));
            }
            for (int g = 0; g < KERNEL_VOL_GUESSES.length; g++) {
                File vol = new File(bases[b], KERNEL_VOL_GUESSES[g]);
                if (rel.length() > 0) {
                    addCandidate(out, seen, new File(vol, rel));
                }
                addCandidate(out, seen, new File(vol, name));
            }
        }
        File[] raw = out.toArray(new File[0]);
        java.util.Arrays.sort(raw, new Comparator<File>() {
            @Override
            public int compare(File a, File b) {
                return Integer.compare(fuseRank(a), fuseRank(b));
            }
        });
        return raw;
    }

    static File findNamed(File file) {
        if (file == null || looksLikeDirectory(file)) {
            return null;
        }
        String name = file.getName();
        if (name == null || name.length() == 0) {
            return null;
        }
        String rel = volumeRelative(file);
        File[] roots = kernelVolumeRoots();
        for (int i = 0; i < roots.length; i++) {
            if (rel.length() > 0) {
                File withRel = new File(roots[i], rel);
                if (hasNonZeroBytes(withRel)) {
                    return withRel;
                }
            }
            File direct = new File(roots[i], name);
            if (hasNonZeroBytes(direct)) {
                return direct;
            }
        }
        for (int i = 0; i < roots.length; i++) {
            File found = walkFind(roots[i], name, 0);
            if (found != null) {
                return found;
            }
        }
        return null;
    }

    private static File walkFind(File dir, String name, int depth) {
        if (dir == null || depth > 4) {
            return null;
        }
        File[] files = kids(dir);
        if (files == null) {
            return null;
        }
        for (int i = 0; i < files.length; i++) {
            File child = files[i];
            String childName = child.getName();
            if (childName.startsWith(".")) {
                continue;
            }
            if (looksLikeDirectory(child)) {
                if ("Android".equals(childName) || "LOST.DIR".equals(childName)
                        || "System Volume Information".equalsIgnoreCase(childName)) {
                    continue;
                }
                File found = walkFind(child, name, depth + 1);
                if (found != null) {
                    return found;
                }
            } else if (name.equals(childName) && hasNonZeroBytes(child)) {
                return child;
            }
        }
        return null;
    }

    static boolean hasNonZeroBytes(File file) {
        if (file == null || looksLikeDirectory(file)) {
            return false;
        }
        FileInputStream in = null;
        try {
            in = new FileInputStream(file);
            byte[] buf = new byte[64];
            int n = in.read(buf);
            if (n < 1) {
                return false;
            }
            for (int i = 0; i < n; i++) {
                if (buf[i] != 0) {
                    return true;
                }
            }
            return false;
        } catch (Exception e) {
            return false;
        } finally {
            if (in != null) {
                try {
                    in.close();
                } catch (Exception ignored) {
                }
            }
        }
    }

    /**
     * Kernel USB nodes first. Feiyu FUSE {@code /storage/UUID} lists names but
     * often yields a zero-filled stub that MediaPlayer reports as -2147483648.
     */
    static File[] rankedPathCandidates(File file) {
        File[] raw = pathCandidates(file);
        java.util.Arrays.sort(raw, new Comparator<File>() {
            @Override
            public int compare(File a, File b) {
                return Integer.compare(fuseRank(a), fuseRank(b));
            }
        });
        return raw;
    }

    static int fuseRank(File file) {
        if (file == null) {
            return 99;
        }
        String path = file.getAbsolutePath();
        if (path.contains("/mnt/media_rw/")) {
            return 0;
        }
        if (path.contains("/mnt/usb_storage/")) {
            return 1;
        }
        if (path.contains("/mnt/usbhost/")) {
            return 2;
        }
        if (path.contains("/mnt/udisk") || path.contains("/mnt/usb")) {
            return 3;
        }
        if (path.contains("/storage/usb")) {
            return 4;
        }
        if (volumeName(path) != null && path.contains("/storage/")) {
            return 9;
        }
        return 5;
    }

    private static void addCandidate(java.util.List<File> out, Set<String> seen, File file) {
        if (file == null) {
            return;
        }
        String key = file.getAbsolutePath();
        if (key.length() == 0 || !seen.add(key)) {
            return;
        }
        out.add(file);
    }

    static String volumeName(String path) {
        if (path == null) {
            return null;
        }
        String[] parts = path.split("/");
        for (int i = 0; i < parts.length; i++) {
            String part = parts[i];
            if (part.length() == 9 && part.charAt(4) == '-' && part.matches("[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}")) {
                return part;
            }
        }
        return null;
    }

    static boolean canOpen(File file) {
        if (file == null) {
            return false;
        }
        FileInputStream in = null;
        try {
            in = new FileInputStream(file);
            return true;
        } catch (Exception e) {
            return false;
        } finally {
            if (in != null) {
                try {
                    in.close();
                } catch (Exception ignored) {
                }
            }
        }
    }

    public static String describe(File dir) {
        File best = bestReadable(dir);
        if (best == null) {
            return "том не найден";
        }
        String[] names = best.list();
        if (names == null) {
            return best.getAbsolutePath() + " — нет доступа к файлам";
        }
        if (names.length == 0) {
            return best.getAbsolutePath() + " — папка пустая";
        }
        StringBuilder sb = new StringBuilder(best.getAbsolutePath());
        sb.append(" — ").append(names.length).append(" имён, например: ");
        int n = Math.min(4, names.length);
        for (int i = 0; i < n; i++) {
            if (i > 0) {
                sb.append(", ");
            }
            sb.append(names[i]);
        }
        return sb.toString();
    }

    private static void addIfDir(List<File> found, File dir) {
        if (dir != null && dir.isDirectory()) {
            found.add(dir);
        }
    }

    private static Entry volumeEntry(File root, boolean removable) {
        Entry e = new Entry();
        e.file = root;
        e.directory = true;
        e.volume = true;
        e.removable = removable;
        e.label = removable ? ("Флешка · " + root.getName()) : ("Память ГУ · " + root.getName());
        e.meta = root.getAbsolutePath();
        return e;
    }

    private static boolean isMemoryPath(String path) {
        String lower = path.toLowerCase(Locale.ROOT);
        return lower.contains("/emulated/") || lower.endsWith("/emulated")
                || lower.equals("/sdcard") || lower.endsWith("/sdcard")
                || lower.contains("/sdcard0");
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
