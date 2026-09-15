package com.changanhub.player;

import android.content.Context;
import android.media.AudioAttributes;
import android.media.AudioManager;
import android.media.MediaPlayer;
import android.os.ParcelFileDescriptor;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.util.Locale;

/**
 * Feiyu FUSE {@code /storage/UUID} lists names that MediaPlayer cannot decode.
 * Open a sized FileDescriptor, then copy into app cache if the stick still
 * yields a zero-length stub.
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

    public static MediaSource open(File file, Setup setup) throws IOException {
        File playable = UsbMedia.playableFile(file);
        IOException last = new IOException("файл не открылся: " + (file == null ? "" : file.getAbsolutePath()));
        File[] cands = UsbMedia.pathCandidates(playable);
        for (int i = 0; i < cands.length; i++) {
            File cand = cands[i];
            if (cand == null) {
                continue;
            }
            MediaSource viaSized = tryOpen(cand, setup, 2);
            if (viaSized != null) {
                return viaSized;
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
        throw last;
    }

    public static boolean looksEmpty(File file) {
        File[] cands = UsbMedia.pathCandidates(UsbMedia.playableFile(file));
        boolean any = false;
        for (int i = 0; i < cands.length; i++) {
            File cand = cands[i];
            if (cand == null || UsbMedia.looksLikeDirectory(cand)) {
                continue;
            }
            any = true;
            long size = 0;
            try {
                size = cand.length();
            } catch (Exception ignored) {
            }
            if (size > 0) {
                return false;
            }
        }
        return any;
    }

    public static File copyToCache(Context context, File src) throws IOException {
        File playable = UsbMedia.playableFile(src);
        FileInputStream in = openStream(playable);
        if (in == null) {
            throw new IOException("флешка не отдаёт байты: " + (src == null ? "" : src.getAbsolutePath()));
        }
        String name = playable != null ? playable.getName() : "media.bin";
        int dot = name.lastIndexOf('.');
        String ext = dot >= 0 ? name.substring(dot).toLowerCase(Locale.US) : ".bin";
        File dest = new File(context.getCacheDir(), "play" + ext);
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
            return dest;
        } finally {
            try {
                in.close();
            } catch (Exception ignored) {
            }
            if (out != null) {
                try {
                    out.close();
                } catch (Exception ignored) {
                }
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
        if (what == -38 || extra == -38) {
            return "файл с флешки не читается";
        }
        if (extra == Integer.MIN_VALUE || extra == -2147483648) {
            return "нет доступа или кодек ГУ (часто HEVC)";
        }
        if (extra == MediaPlayer.MEDIA_ERROR_IO) {
            return "нет доступа к файлу на флешке";
        }
        if (extra == MediaPlayer.MEDIA_ERROR_UNSUPPORTED) {
            return "кодек ГУ не умеет этот файл";
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

    private static FileInputStream openStream(File file) {
        File[] cands = UsbMedia.pathCandidates(file);
        for (int i = 0; i < cands.length; i++) {
            File cand = cands[i];
            if (cand == null || UsbMedia.looksLikeDirectory(cand)) {
                continue;
            }
            try {
                return new FileInputStream(cand);
            } catch (Exception ignored) {
            }
        }
        return null;
    }

    /**
     * mode 2: ParcelFileDescriptor + offset/length, 1: raw FD, 0: path string.
     */
    private static MediaSource tryOpen(File file, Setup setup, int mode) {
        MediaPlayer player = new MediaPlayer();
        FileInputStream stream = null;
        ParcelFileDescriptor pfd = null;
        try {
            if (setup != null) {
                setup.apply(player);
            }
            if (mode == 2) {
                pfd = ParcelFileDescriptor.open(file, ParcelFileDescriptor.MODE_READ_ONLY);
                long size = pfd.getStatSize();
                if (size <= 0) {
                    throw new IOException("size 0");
                }
                player.setDataSource(pfd.getFileDescriptor(), 0, size);
            } else if (mode == 1) {
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
