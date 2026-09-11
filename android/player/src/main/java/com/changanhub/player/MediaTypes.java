package com.changanhub.player;

import java.util.Locale;

/** Common USB media extensions the HU decoder plus MediaPlayer can try. */
public final class MediaTypes {
    private MediaTypes() {
    }

    public static final String[] AUDIO = {
            "mp3", "m4a", "aac", "ogg", "oga", "wav", "flac", "amr", "mid", "midi",
            "wma", "ape", "opus", "mka"
    };
    public static final String[] VIDEO = {
            "mp4", "mkv", "webm", "3gp", "3gpp", "mov", "m4v", "avi", "flv",
            "wmv", "ts", "m2ts", "mpeg", "mpg"
    };

    public static String ext(String name) {
        if (name == null) {
            return "";
        }
        int dot = name.lastIndexOf('.');
        if (dot < 0 || dot == name.length() - 1) {
            return "";
        }
        return name.substring(dot + 1).toLowerCase(Locale.US);
    }

    public static boolean isAudio(String name) {
        return in(ext(name), AUDIO);
    }

    public static boolean isVideo(String name) {
        return in(ext(name), VIDEO);
    }

    public static boolean isMedia(String name) {
        return isAudio(name) || isVideo(name);
    }

    private static boolean in(String ext, String[] set) {
        for (int i = 0; i < set.length; i++) {
            if (set[i].equals(ext)) {
                return true;
            }
        }
        return false;
    }
}
