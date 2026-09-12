package com.changanhub.player;

import android.content.Context;
import android.content.SharedPreferences;

/** Named EQ + FX levels for Feiyu MediaPlayer sessions. */
public final class EqPrefs {
    public static final String[] PRESET_NAMES = {
            "Flat", "Rock", "Pop", "Jazz", "Classical", "Bass Boost", "Vocal", "Custom"
    };

    private EqPrefs() {
    }

    public static SharedPreferences prefs(Context context) {
        return context.getSharedPreferences("lamore_player", Context.MODE_PRIVATE);
    }

    public static int namedPreset(Context context) {
        return prefs(context).getInt("eq_named", 0);
    }

    public static int vizMode(Context context) {
        return prefs(context).getInt("viz_mode", 0);
    }

    public static boolean shuffle(Context context) {
        return prefs(context).getBoolean("shuffle", false);
    }

    public static int repeat(Context context) {
        return prefs(context).getInt("repeat", 1);
    }

    public static int bass(Context context) {
        return prefs(context).getInt("bass", 500);
    }

    public static int virt(Context context) {
        return prefs(context).getInt("virt", 400);
    }

    public static int loud(Context context) {
        return prefs(context).getInt("loud", 0);
    }

    public static int balance(Context context) {
        return prefs(context).getInt("balance", 50);
    }

    public static int mids(Context context) {
        return prefs(context).getInt("mids", 500);
    }

    public static int highs(Context context) {
        return prefs(context).getInt("highs", 500);
    }

    public static int volume(Context context) {
        return prefs(context).getInt("volume", 80);
    }

    public static int sortMode(Context context) {
        return prefs(context).getInt("sort", 0);
    }

    public static void putInt(Context context, String key, int value) {
        prefs(context).edit().putInt(key, value).apply();
    }

    public static void putBool(Context context, String key, boolean value) {
        prefs(context).edit().putBoolean(key, value).apply();
    }

    /** 10-band shape in millibels-ish -1200..1200, mapped onto hardware bands. */
    public static short[] shape(int named) {
        switch (named) {
            case 1: // Rock
                return new short[]{600, 400, 200, 0, -200, 0, 300, 500, 400, 300};
            case 2: // Pop
                return new short[]{-200, 0, 300, 400, 200, 0, 200, 300, 200, 0};
            case 3: // Jazz
                return new short[]{200, 100, 0, 200, 300, 200, 0, 100, 200, 100};
            case 4: // Classical
                return new short[]{400, 200, 0, -200, -200, 0, 200, 400, 500, 400};
            case 5: // Bass Boost
                return new short[]{900, 700, 400, 100, 0, 0, 0, 0, 0, 0};
            case 6: // Vocal
                return new short[]{-300, -100, 0, 400, 600, 500, 200, 0, -100, -200};
            case 7: // Custom — zeros; real levels stored per band
                return new short[]{0, 0, 0, 0, 0, 0, 0, 0, 0, 0};
            default: // Flat
                return new short[]{0, 0, 0, 0, 0, 0, 0, 0, 0, 0};
        }
    }

    public static short customBand(Context context, int band) {
        return (short) prefs(context).getInt("band_" + band, 0);
    }

    public static void saveCustomBand(Context context, int band, short level) {
        prefs(context).edit().putInt("eq_named", 7).putInt("band_" + band, level).apply();
    }
}
