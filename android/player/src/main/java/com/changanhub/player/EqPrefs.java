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
        return tone(context, "bass", namedPreset(context));
    }

    public static int virt(Context context) {
        return tone(context, "virt", namedPreset(context));
    }

    public static int loud(Context context) {
        return tone(context, "loud", namedPreset(context));
    }

    public static int balance(Context context) {
        return prefs(context).getInt("balance", 50);
    }

    public static int mids(Context context) {
        return tone(context, "mids", namedPreset(context));
    }

    public static int highs(Context context) {
        return tone(context, "highs", namedPreset(context));
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

    public static void putTone(Context context, String key, int value) {
        int named = namedPreset(context);
        SharedPreferences.Editor edit = prefs(context).edit();
        edit.putInt(key + "_" + named, value);
        if ("volume".equals(key) || "balance".equals(key)) {
            edit.putInt(key, value);
        }
        edit.apply();
    }

    public static int tone(Context context, String key, int named) {
        String namedKey = key + "_" + named;
        SharedPreferences p = prefs(context);
        if (p.contains(namedKey)) {
            return p.getInt(namedKey, toneDefault(named, key));
        }
        if (named == 7 && p.contains(key) && isPerPreset(key)) {
            return p.getInt(key, toneDefault(named, key));
        }
        return toneDefault(named, key);
    }

    public static int toneDefault(int named, String key) {
        if ("virt".equals(key)) {
            return 400;
        }
        if ("loud".equals(key)) {
            return 0;
        }
        if ("bass".equals(key) || "mids".equals(key) || "highs".equals(key)) {
            return millibelToSlider(thirdAverage(shape(named), key));
        }
        return 500;
    }

    /** Factory 10-band shape plus per-genre slider overlays. */
    public static short[] effectiveShape(Context context, int named) {
        short[] shape = shape(named);
        if (named == 7) {
            for (int i = 0; i < shape.length; i++) {
                shape[i] = customBand(context, i);
            }
        }
        overlayThird(shape, "bass", tone(context, "bass", named) - toneDefault(named, "bass"));
        overlayThird(shape, "mids", tone(context, "mids", named) - toneDefault(named, "mids"));
        overlayThird(shape, "highs", tone(context, "highs", named) - toneDefault(named, "highs"));
        return shape;
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

    public static int millibelToSlider(int millibel) {
        int slider = 500 + millibel * 500 / 1200;
        if (slider < 0) {
            return 0;
        }
        if (slider > 1000) {
            return 1000;
        }
        return slider;
    }

    private static boolean isPerPreset(String key) {
        return "bass".equals(key) || "mids".equals(key) || "highs".equals(key)
                || "virt".equals(key) || "loud".equals(key);
    }

    private static int thirdAverage(short[] shape, String key) {
        int start = 0;
        int end = 3;
        if ("mids".equals(key)) {
            start = 3;
            end = 7;
        } else if ("highs".equals(key)) {
            start = 7;
            end = 10;
        }
        if (end > shape.length) {
            end = shape.length;
        }
        if (end <= start) {
            return 0;
        }
        int sum = 0;
        for (int i = start; i < end; i++) {
            sum += shape[i];
        }
        return sum / (end - start);
    }

    private static void overlayThird(short[] shape, String key, int sliderDelta) {
        int start = 0;
        int end = 3;
        if ("mids".equals(key)) {
            start = 3;
            end = 7;
        } else if ("highs".equals(key)) {
            start = 7;
            end = 10;
        }
        int millibel = sliderDelta * 1200 / 500;
        if (end > shape.length) {
            end = shape.length;
        }
        for (int i = start; i < end; i++) {
            int next = shape[i] + millibel;
            if (next > 1500) {
                next = 1500;
            }
            if (next < -1500) {
                next = -1500;
            }
            shape[i] = (short) next;
        }
    }
}
