package com.changanhub.player;

import android.media.AudioAttributes;
import android.media.AudioManager;
import android.media.MediaPlayer;

import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;

/**
 * Feiyu FUSE {@code /storage/UUID} often lists names that MediaPlayer cannot
 * open by path. Prefer a real FileDescriptor, usually from {@code /mnt/media_rw}.
 */
public final class MediaSource {
    public interface Setup {
        void apply(MediaPlayer player);
    }

    public final MediaPlayer player;
    public final FileInputStream stream;
    public final String path;

    private MediaSource(MediaPlayer player, FileInputStream stream, String path) {
        this.player = player;
        this.stream = stream;
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
            MediaSource viaFd = tryOpen(cand, setup, true);
            if (viaFd != null) {
                return viaFd;
            }
            MediaSource viaPath = tryOpen(cand, setup, false);
            if (viaPath != null) {
                return viaPath;
            }
            last = new IOException("не читается: " + cand.getAbsolutePath());
        }
        throw last;
    }

    public void close() {
        if (stream == null) {
            return;
        }
        try {
            stream.close();
        } catch (Exception ignored) {
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

    private static MediaSource tryOpen(File file, Setup setup, boolean useFd) {
        MediaPlayer player = new MediaPlayer();
        FileInputStream stream = null;
        try {
            if (setup != null) {
                setup.apply(player);
            }
            if (useFd) {
                stream = new FileInputStream(file);
                player.setDataSource(stream.getFD());
            } else {
                player.setDataSource(file.getAbsolutePath());
            }
            return new MediaSource(player, stream, file.getAbsolutePath());
        } catch (Exception e) {
            if (stream != null) {
                try {
                    stream.close();
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
