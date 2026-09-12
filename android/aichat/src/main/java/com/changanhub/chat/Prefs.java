package com.changanhub.chat;

import android.content.Context;
import android.content.SharedPreferences;

/** Settings in SharedPreferences; API keys go through SecretBox / Keystore. */
public final class Prefs {
    public static final String PROVIDER_DEEPSEEK = "deepseek";
    public static final String PROVIDER_YANDEX = "yandex";

    private Prefs() {
    }

    public static SharedPreferences raw(Context context) {
        return context.getSharedPreferences("aichat", Context.MODE_PRIVATE);
    }

    public static String provider(Context context) {
        return raw(context).getString("provider", PROVIDER_DEEPSEEK);
    }

    public static String deepseekUrl(Context context) {
        return raw(context).getString("ds_url", "https://api.deepseek.com/v1");
    }

    public static String deepseekModel(Context context) {
        return raw(context).getString("ds_model", "deepseek-chat");
    }

    public static String yandexUrl(Context context) {
        return raw(context).getString("ya_url",
                "https://llm.api.cloud.yandex.net/foundationModels/v1/completion");
    }

    public static String yandexModel(Context context) {
        return raw(context).getString("ya_model", "yandexgpt-lite");
    }

    public static String yandexFolder(Context context) {
        return raw(context).getString("ya_folder", "");
    }

    public static String systemPrompt(Context context) {
        return raw(context).getString("system",
                "Ты голосовой помощник в автомобиле Changan Lamore. Отвечай кратко и по-русски.");
    }

    public static String proxyHost(Context context) {
        return raw(context).getString("proxy_host", "");
    }

    public static int proxyPort(Context context) {
        return raw(context).getInt("proxy_port", 0);
    }

    public static String proxyType(Context context) {
        return raw(context).getString("proxy_type", "HTTP");
    }

    public static int timeoutSec(Context context) {
        return raw(context).getInt("timeout", 45);
    }

    public static float temperature(Context context) {
        try {
            return Float.parseFloat(raw(context).getString("temp", "0.7"));
        } catch (Exception e) {
            return 0.7f;
        }
    }

    public static int maxTokens(Context context) {
        return raw(context).getInt("max_tokens", 1024);
    }

    public static int historyLimit(Context context) {
        return raw(context).getInt("history_n", 20);
    }

    public static boolean autoTts(Context context) {
        return raw(context).getBoolean("auto_tts", true);
    }

    public static float speechRate(Context context) {
        return raw(context).getFloat("tts_rate", 1.0f);
    }

    public static float pitch(Context context) {
        return raw(context).getFloat("tts_pitch", 1.0f);
    }

    public static float volume(Context context) {
        return raw(context).getFloat("tts_vol", 1.0f);
    }

    public static String voiceName(Context context) {
        return raw(context).getString("tts_voice", "");
    }

    public static String chatId(Context context) {
        return raw(context).getString("chat_id", "");
    }

    public static String secret(Context context, String key) {
        return SecretBox.unwrap(context, raw(context).getString(key, ""));
    }

    public static void putSecret(Context context, String key, String value) {
        raw(context).edit().putString(key, SecretBox.wrap(context, value)).apply();
    }

    public static String deepseekKey(Context context) {
        return secret(context, "ds_key");
    }

    public static String yandexKey(Context context) {
        return secret(context, "ya_key");
    }

    public static void put(Context context, String key, String value) {
        raw(context).edit().putString(key, value == null ? "" : value).apply();
    }

    public static void putInt(Context context, String key, int value) {
        raw(context).edit().putInt(key, value).apply();
    }

    public static void putFloat(Context context, String key, float value) {
        raw(context).edit().putFloat(key, value).apply();
    }

    public static void putBool(Context context, String key, boolean value) {
        raw(context).edit().putBoolean(key, value).apply();
    }

    public static void reset(Context context) {
        raw(context).edit().clear().apply();
    }
}
