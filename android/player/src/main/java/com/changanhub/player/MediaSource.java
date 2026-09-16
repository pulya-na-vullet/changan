package com.changanhub.player;

import android.content.ContentUris;
import android.content.Context;
import android.database.Cursor;
import android.media.AudioAttributes;
import android.media.AudioManager;
import android.media.MediaPlayer;
import android.net.Uri;
import android.os.ParcelFileDescriptor;
import android.provider.MediaStore;
import android.system.Os;
import android.system.OsConstants;

import java.io.File;
import java.io.FileDescriptor;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.util.Locale;

/**
 * Feiyu FUSE {@code /storage/UUID} lists names. Java can often open the stub,
 * but MediaPlayer then fails with extra=-2147483648. Prefer {@code /mnt/media_rw},
 * skip zero-filled headers, copy real bytes into app cache, then play locally.
 */
public final class MediaSource {
    public static final long MAX_COPY = 512L * 1024L * 1024L;

    public interface Setup {
        void apply(MediaPlayer player);
    }

    public final MediaPlayer player;
    public final FileInputStream stream;
    public final ParcelFileDescriptor pfd;
    public final String path;

    private MediaSource(MediaPlayer player, FileInputStream stream, ParcelFileDescriptor pfd, String path) {
        this.player = player;
        this.stream = stream;
        this.pfd = pfd;
        this.path = path;
    }

    public static boolean isUsbFile(File file) {
        if (file == null) {
            return false;
        }
        String path = file.getAbsolutePath();
        if (path.contains("/cache/")) {
            return false;
        }
        if (UsbMedia.volumeName(path) != null) {
            return true;
        }
        return path.contains("/media_rw/")
                || path.contains("/usb_storage/")
                || path.contains("/usbhost/")
                || path.contains("/storage/usb")
                || path.contains("/mnt/usb")
                || path.contains("/mnt/udisk")
                || path.contains("/storage/udisk");
    }

    public static MediaSource open(File file, Setup setup) throws IOException {
        return open(null, file, setup);
    }

    public static MediaSource open(Context context, File file, Setup setup) throws IOException {
        if (file != null && !isUsbFile(file)) {
            return openLocal(file, setup);
        }
        File playable = UsbMedia.playableFile(file);
        IOException last = new IOException("файл не открылся: " + (file == null ? "" : file.getAbsolutePath()));
        File[] cands = UsbMedia.rankedPathCandidates(playable);
        for (int i = 0; i < cands.length; i++) {
            File cand = cands[i];
            if (cand == null || UsbMedia.looksLikeDirectory(cand) || !hasMediaHeader(cand)) {
                continue;
            }
            if (UsbMedia.fuseRank(cand) >= 9) {
                continue;
            }
            MediaSource viaFd = tryOpen(cand, setup, 1);
            if (viaFd != null) {
                return viaFd;
            }
            MediaSource viaPath = tryOpen(cand, setup, 0);
            if (viaPath != null) {
                return viaPath;
            }
            last = new IOException("не читается: " + cand.getAbsolutePath());
        }
        if (context != null) {
            Uri uri = findStoreUri(context, file != null ? file : playable);
            if (uri != null) {
                MediaSource viaUri = tryUri(context, uri, setup);
                if (viaUri != null) {
                    return viaUri;
                }
            }
        }
        throw last;
    }

    public static MediaSource openLocal(File file, Setup setup) throws IOException {
        MediaSource viaPath = tryOpen(file, setup, 0);
        if (viaPath != null) {
            return viaPath;
        }
        MediaSource viaFd = tryOpen(file, setup, 1);
        if (viaFd != null) {
            return viaFd;
        }
        throw new IOException("кэш не открылся: " + (file == null ? "" : file.getAbsolutePath()));
    }

    public static File materialize(Context context, File src) throws IOException {
        if (src == null) {
            throw new IOException("нет файла");
        }
        if (!isUsbFile(src)) {
            return src;
        }
        return copyToCache(context, src);
    }

    public static boolean looksEmpty(File file) {
        File[] cands = UsbMedia.rankedPathCandidates(UsbMedia.playableFile(file));
        boolean any = false;
        for (int i = 0; i < cands.length; i++) {
            File cand = cands[i];
            if (cand == null || UsbMedia.looksLikeDirectory(cand)) {
                continue;
            }
            any = true;
            if (hasMediaHeader(cand)) {
                return false;
            }
        }
        return any;
    }

    public static File copyToCache(Context context, File src) throws IOException {
        File playable = UsbMedia.playableFile(src);
        InputStream in = context != null ? UsbBridge.open(context, src) : null;
        if (in == null && context != null) {
            in = UsbBridge.scanAndOpen(context, src);
        }
        if (in == null) {
            in = openReadableStream(playable != null ? playable : src);
        }
        if (in == null) {
            File named = UsbMedia.findNamed(src);
            if (named != null) {
                in = openReadableStream(named);
            }
        }
        if (in == null && context != null && playable != null && playable != src) {
            in = UsbBridge.open(context, playable);
        }
        if (in == null) {
            throw new IOException("флешка без байтов. Нажмите «Разрешить флешку» и Allow. "
                    + (src == null ? "" : src.getAbsolutePath()));
        }
        try {
            return writeCache(context, in, playable != null ? playable.getName() : "media.bin",
                    playable != null ? playable.getAbsolutePath() : "usb");
        } finally {
            try {
                in.close();
            } catch (Exception ignored) {
            }
        }
    }

    public void close() {
        if (stream != null) {
            try {
                stream.close();
            } catch (Exception ignored) {
            }
        }
        if (pfd != null) {
            try {
                pfd.close();
            } catch (Exception ignored) {
            }
        }
    }

    public static void applyAudio(MediaPlayer player, boolean video) {
        player.setAudioAttributes(new AudioAttributes.Builder()
                .setUsage(AudioAttributes.USAGE_MEDIA)
                .setContentType(video
                        ? AudioAttributes.CONTENT_TYPE_MOVIE
                        : AudioAttributes.CONTENT_TYPE_MUSIC)
                .setLegacyStreamType(AudioManager.STREAM_MUSIC)
                .build());
    }

    public static String explainError(int what, int extra) {
        return explainError(what, extra, "");
    }

    public static String explainError(int what, int extra, String name) {
        String lower = name == null ? "" : name.toLowerCase(Locale.US);
        boolean audio = ends(lower, ".mp3", ".flac", ".wav", ".ogg", ".m4a", ".aac", ".opus", ".wma", ".mp2");
        boolean video = ends(lower, ".mp4", ".mkv", ".webm", ".mov", ".ts", ".m2ts", ".avi", ".3gp");
        if (what == -38 || extra == -38) {
            return audio ? "флешка не отдала музыку" : "файл с флешки не читается";
        }
        if (extra == Integer.MIN_VALUE || extra == -2147483648 || extra == MediaPlayer.MEDIA_ERROR_IO) {
            if (audio) {
                return "флешка не отдала музыку (FUSE). Нужен /mnt/media_rw";
            }
            if (video) {
                return "нет доступа или кодек ГУ (часто HEVC, нужен H.264)";
            }
            return "нет доступа к файлу на флешке";
        }
        if (extra == MediaPlayer.MEDIA_ERROR_UNSUPPORTED) {
            return video ? "кодек ГУ не умеет этот файл (часто HEVC)" : "кодек ГУ не умеет этот файл";
        }
        if (extra == MediaPlayer.MEDIA_ERROR_MALFORMED) {
            return "битый файл";
        }
        if (extra == MediaPlayer.MEDIA_ERROR_TIMED_OUT) {
            return "таймаут декодера";
        }
        if (what == MediaPlayer.MEDIA_ERROR_SERVER_DIED) {
            return "декодер ГУ упал";
        }
        return "ошибка " + what + "/" + extra;
    }

    static boolean looksLikeMedia(byte[] head, int n) {
        if (head == null || n < 8) {
            return false;
        }
        int nz = 0;
        for (int i = 0; i < n; i++) {
            if (head[i] != 0) {
                nz++;
            }
        }
        if (nz < 4) {
            return false;
        }
        if (head[0] == 'I' && head[1] == 'D' && head[2] == '3') {
            return true;
        }
        if ((head[0] & 0xFF) == 0xFF && (head[1] & 0xE0) == 0xE0) {
            return true;
        }
        if (head[0] == 'f' && head[1] == 'L' && head[2] == 'a' && head[3] == 'C') {
            return true;
        }
        if (head[0] == 'O' && head[1] == 'g' && head[2] == 'g' && head[3] == 'S') {
            return true;
        }
        if (head[0] == 'R' && head[1] == 'I' && head[2] == 'F' && head[3] == 'F') {
            return true;
        }
        if (n >= 8 && head[4] == 'f' && head[5] == 't' && head[6] == 'y' && head[7] == 'p') {
            return true;
        }
        if ((head[0] & 0xFF) == 0x1A && (head[1] & 0xFF) == 0x45
                && (head[2] & 0xFF) == 0xDF && (head[3] & 0xFF) == 0xA3) {
            return true;
        }
        if (head[0] == 0x47) {
            return true;
        }
        return nz > n / 4;
    }

    private static boolean hasMediaHeader(File file) {
        Peek peek = peekFile(file);
        return peek != null && usableHead(file, peek.head, peek.n);
    }

    private static InputStream openReadableStream(File file) {
        InputStream in = openFromCandidates(UsbMedia.expandKernelCandidates(file));
        if (in != null) {
            return in;
        }
        File named = UsbMedia.findNamed(file);
        if (named == null) {
            return null;
        }
        return openFromCandidates(new File[] { named });
    }

    private static InputStream openFromCandidates(File[] cands) {
        if (cands == null) {
            return null;
        }
        for (int i = 0; i < cands.length; i++) {
            File cand = cands[i];
            if (cand == null || UsbMedia.looksLikeDirectory(cand)) {
                continue;
            }
            Peek peek = peekFile(cand);
            if (peek == null || !usableHead(cand, peek.head, peek.n)) {
                continue;
            }
            InputStream in = openAny(cand);
            if (in != null) {
                return in;
            }
        }
        return null;
    }

    private static String triedHint(File src, File playable) {
        File probe = playable != null ? playable : src;
        File[] cands = UsbMedia.expandKernelCandidates(probe);
        StringBuilder sb = new StringBuilder();
        int shown = 0;
        for (int i = 0; i < cands.length && shown < 2; i++) {
            File cand = cands[i];
            if (cand == null || UsbMedia.looksLikeDirectory(cand)) {
                continue;
            }
            if (UsbMedia.fuseRank(cand) > 4) {
                continue;
            }
            sb.append(shown == 0 ? " · нет " : " / ");
            sb.append(cand.getAbsolutePath());
            shown++;
        }
        return sb.toString();
    }

    private static final class Peek {
        final byte[] head;
        final int n;

        Peek(byte[] head, int n) {
            this.head = head;
            this.n = n;
        }
    }

    private static Peek peekFile(File file) {
        InputStream in = openAny(file);
        if (in == null) {
            return null;
        }
        try {
            byte[] head = new byte[64];
            int n = in.read(head);
            return new Peek(head, n);
        } catch (Exception e) {
            return null;
        } finally {
            try {
                in.close();
            } catch (Exception ignored) {
            }
        }
    }

    private static boolean usableHead(File cand, byte[] head, int n) {
        if (looksLikeMedia(head, n)) {
            return true;
        }
        if (head == null || n < 1) {
            return false;
        }
        int nz = 0;
        for (int i = 0; i < n; i++) {
            if (head[i] != 0) {
                nz++;
            }
        }
        if (nz == 0) {
            return false;
        }
        return UsbMedia.fuseRank(cand) <= 4 && nz >= 1;
    }

    private static InputStream openAny(File file) {
        if (file == null) {
            return null;
        }
        InputStream os = openOs(file);
        if (os != null) {
            return os;
        }
        try {
            return new FileInputStream(file);
        } catch (Exception ignored) {
        }
        try {
            ParcelFileDescriptor pfd = ParcelFileDescriptor.open(
                    file, ParcelFileDescriptor.MODE_READ_ONLY);
            return new ParcelFileDescriptor.AutoCloseInputStream(pfd);
        } catch (Exception ignored) {
        }
        return null;
    }

    private static InputStream openOs(File file) {
        FileDescriptor fd = null;
        try {
            fd = Os.open(file.getAbsolutePath(), OsConstants.O_RDONLY, 0);
            ParcelFileDescriptor pfd = ParcelFileDescriptor.dup(fd);
            Os.close(fd);
            fd = null;
            return new ParcelFileDescriptor.AutoCloseInputStream(pfd);
        } catch (Exception e) {
            if (fd != null) {
                try {
                    Os.close(fd);
                } catch (Exception ignored) {
                }
            }
            return null;
        }
    }

    private static File copyUriToCache(Context context, Uri uri, String name) throws IOException {
        InputStream in = context.getContentResolver().openInputStream(uri);
        if (in == null) {
            throw new IOException("MediaStore не открыл " + uri);
        }
        try {
            return writeCache(context, in, name, uri.toString());
        } finally {
            try {
                in.close();
            } catch (Exception ignored) {
            }
        }
    }

    private static File writeCache(Context context, InputStream in, String name, String key) throws IOException {
        int dot = name.lastIndexOf('.');
        String ext = dot >= 0 ? name.substring(dot).toLowerCase(Locale.US) : ".bin";
        File dest = new File(context.getCacheDir(), "p" + Integer.toHexString(key.hashCode()) + ext);
        FileOutputStream out = null;
        try {
            out = new FileOutputStream(dest);
            byte[] buf = new byte[256 * 1024];
            long total = 0;
            int n;
            while ((n = in.read(buf)) > 0) {
                out.write(buf, 0, n);
                total += n;
                if (total > MAX_COPY) {
                    throw new IOException("файл больше 512 МБ, копирование остановлено");
                }
            }
            out.flush();
            if (total <= 0) {
                dest.delete();
                throw new IOException("пустой файл на флешке");
            }
            if (!hasMediaHeader(dest)) {
                dest.delete();
                throw new IOException("скопировалась пустышка FUSE, не медиа");
            }
            return dest;
        } finally {
            if (out != null) {
                try {
                    out.close();
                } catch (Exception ignored) {
                }
            }
        }
    }

    private static Uri findStoreUri(Context context, File file) {
        if (context == null || file == null) {
            return null;
        }
        String name = file.getName();
        File[] cands = UsbMedia.rankedPathCandidates(file);
        Uri[] tables = new Uri[] {
                MediaStore.Audio.Media.EXTERNAL_CONTENT_URI,
                MediaStore.Video.Media.EXTERNAL_CONTENT_URI,
                MediaStore.Files.getContentUri("external")
        };
        for (int t = 0; t < tables.length; t++) {
            Uri found = queryStore(context, tables[t], MediaStore.MediaColumns.DISPLAY_NAME, name);
            if (found != null) {
                return found;
            }
            for (int i = 0; i < cands.length; i++) {
                if (cands[i] == null) {
                    continue;
                }
                found = queryStore(context, tables[t], MediaStore.MediaColumns.DATA, cands[i].getAbsolutePath());
                if (found != null) {
                    return found;
                }
            }
        }
        return null;
    }

    private static Uri queryStore(Context context, Uri table, String column, String value) {
        Cursor cursor = null;
        try {
            cursor = context.getContentResolver().query(
                    table,
                    new String[] { MediaStore.MediaColumns._ID },
                    column + "=?",
                    new String[] { value },
                    null);
            if (cursor != null && cursor.moveToFirst()) {
                long id = cursor.getLong(0);
                return ContentUris.withAppendedId(table, id);
            }
        } catch (Exception ignored) {
        } finally {
            if (cursor != null) {
                try {
                    cursor.close();
                } catch (Exception ignored) {
                }
            }
        }
        return null;
    }

    private static MediaSource tryUri(Context context, Uri uri, Setup setup) {
        MediaPlayer player = new MediaPlayer();
        try {
            if (setup != null) {
                setup.apply(player);
            }
            player.setDataSource(context, uri);
            return new MediaSource(player, null, null, uri.toString());
        } catch (Exception e) {
            try {
                player.reset();
                player.release();
            } catch (Exception ignored) {
            }
            return null;
        }
    }

    private static boolean ends(String name, String... ext) {
        for (int i = 0; i < ext.length; i++) {
            if (name.endsWith(ext[i])) {
                return true;
            }
        }
        return false;
    }

    /**
     * mode 1: raw FD, 0: path string.
     */
    private static MediaSource tryOpen(File file, Setup setup, int mode) {
        MediaPlayer player = new MediaPlayer();
        FileInputStream stream = null;
        ParcelFileDescriptor pfd = null;
        try {
            if (setup != null) {
                setup.apply(player);
            }
            if (mode == 1) {
                stream = new FileInputStream(file);
                player.setDataSource(stream.getFD());
            } else {
                player.setDataSource(file.getAbsolutePath());
            }
            return new MediaSource(player, stream, pfd, file.getAbsolutePath());
        } catch (Exception e) {
            if (stream != null) {
                try {
                    stream.close();
                } catch (Exception ignored) {
                }
            }
            if (pfd != null) {
                try {
                    pfd.close();
                } catch (Exception ignored) {
                }
            }
            try {
                player.reset();
                player.release();
            } catch (Exception ignored) {
            }
            return null;
        }
    }
}
