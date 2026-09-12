package com.changanhub.player;

import android.media.MediaMetadataRetriever;

import java.io.File;
import java.util.Locale;

/** ID3 / container tags without androidx. */
public final class Tags {
    public String title = "";
    public String artist = "";
    public String album = "";
    public int durationMs;
    public int width;
    public int height;

    private Tags() {
    }

    public static Tags read(File file) {
        Tags tags = new Tags();
        if (file == null) {
            return tags;
        }
        tags.title = file.getName();
        MediaMetadataRetriever mmr = new MediaMetadataRetriever();
        try {
            mmr.setDataSource(file.getAbsolutePath());
            String title = mmr.extractMetadata(MediaMetadataRetriever.METADATA_KEY_TITLE);
            String artist = mmr.extractMetadata(MediaMetadataRetriever.METADATA_KEY_ARTIST);
            String album = mmr.extractMetadata(MediaMetadataRetriever.METADATA_KEY_ALBUM);
            String dur = mmr.extractMetadata(MediaMetadataRetriever.METADATA_KEY_DURATION);
            String w = mmr.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_WIDTH);
            String h = mmr.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_HEIGHT);
            if (title != null && title.trim().length() > 0) {
                tags.title = title.trim();
            }
            tags.artist = artist == null ? "" : artist.trim();
            tags.album = album == null ? "" : album.trim();
            if (dur != null) {
                tags.durationMs = Integer.parseInt(dur);
            }
            if (w != null) {
                tags.width = Integer.parseInt(w);
            }
            if (h != null) {
                tags.height = Integer.parseInt(h);
            }
        } catch (Exception ignored) {
        } finally {
            try {
                mmr.release();
            } catch (Exception ignored) {
            }
        }
        return tags;
    }

    public static byte[] picture(File file) {
        if (file == null) {
            return null;
        }
        MediaMetadataRetriever mmr = new MediaMetadataRetriever();
        try {
            mmr.setDataSource(file.getAbsolutePath());
            return mmr.getEmbeddedPicture();
        } catch (Exception e) {
            return null;
        } finally {
            try {
                mmr.release();
            } catch (Exception ignored) {
            }
        }
    }

    public static String clock(int ms) {
        int sec = Math.max(0, ms / 1000);
        return String.format(Locale.US, "%d:%02d", sec / 60, sec % 60);
    }
}
