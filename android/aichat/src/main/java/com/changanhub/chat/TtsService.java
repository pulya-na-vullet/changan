package com.changanhub.chat;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.media.AudioManager;
import android.os.Build;
import android.os.Bundle;
import android.os.IBinder;
import android.speech.tts.TextToSpeech;
import android.speech.tts.UtteranceProgressListener;
import android.speech.tts.Voice;

import java.util.ArrayDeque;
import java.util.Locale;
import java.util.Set;

/** Speaks AI replies in the background so Nav/climate do not kill TTS. */
public class TtsService extends Service implements TextToSpeech.OnInitListener {
    public static final String ACTION_SPEAK = "com.changanhub.aichat.SPEAK";
    public static final String ACTION_STOP = "com.changanhub.aichat.STOP";
    public static final String ACTION_STATUS = "com.changanhub.aichat.TTS_STATUS";
    public static final String EXTRA_TEXT = "text";

    private static TextToSpeech tts;
    private static boolean ready;
    private static String warning = "";
    private static final ArrayDeque<String> queue = new ArrayDeque<>();
    private static boolean speaking;

    public static void speak(Context context, String text) {
        Intent intent = new Intent(context, TtsService.class);
        intent.setAction(ACTION_SPEAK);
        intent.putExtra(EXTRA_TEXT, text);
        start(context, intent);
    }

    public static void stop(Context context) {
        Intent intent = new Intent(context, TtsService.class);
        intent.setAction(ACTION_STOP);
        start(context, intent);
    }

    public static String warning() {
        return warning == null ? "" : warning;
    }

    public static boolean isSpeaking() {
        return speaking;
    }

    private static void start(Context context, Intent intent) {
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(intent);
            } else {
                context.startService(intent);
            }
        } catch (Exception e) {
            try {
                context.startService(intent);
            } catch (Exception ignored) {
            }
        }
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    @Override
    public void onCreate() {
        super.onCreate();
        startInForeground();
        tts = new TextToSpeech(this, this);
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        startInForeground();
        String action = intent != null ? intent.getAction() : ACTION_STOP;
        if (ACTION_SPEAK.equals(action) && intent != null) {
            String text = intent.getStringExtra(EXTRA_TEXT);
            if (text != null && text.trim().length() > 0) {
                queue.addLast(text.trim());
                pump();
            }
        } else if (ACTION_STOP.equals(action)) {
            queue.clear();
            speaking = false;
            try {
                if (tts != null) {
                    tts.stop();
                }
            } catch (Exception ignored) {
            }
        }
        return START_STICKY;
    }

    @Override
    public void onInit(int status) {
        ready = status == TextToSpeech.SUCCESS;
        warning = "";
        if (!ready) {
            warning = "На ГУ нет TTS-движка. Установите синтез речи в системных настройках Android.";
            return;
        }
        try {
            int lang = tts.setLanguage(new Locale("ru", "RU"));
            if (lang == TextToSpeech.LANG_MISSING_DATA || lang == TextToSpeech.LANG_NOT_SUPPORTED) {
                warning = "Русский голос TTS недоступен. Выберите другой движок в настройках Android.";
            }
            applyVoice();
            tts.setOnUtteranceProgressListener(new UtteranceProgressListener() {
                @Override
                public void onStart(String utteranceId) {
                    speaking = true;
                }

                @Override
                public void onDone(String utteranceId) {
                    speaking = false;
                    pump();
                }

                @Override
                public void onError(String utteranceId) {
                    speaking = false;
                    pump();
                }
            });
        } catch (Exception e) {
            warning = "TTS не запустился: " + e.getMessage();
        }
        pump();
    }

    private void applyVoice() {
        if (tts == null) {
            return;
        }
        try {
            tts.setSpeechRate(Prefs.speechRate(this));
            tts.setPitch(Prefs.pitch(this));
            String wanted = Prefs.voiceName(this);
            if (wanted.length() == 0) {
                return;
            }
            Set<Voice> voices = tts.getVoices();
            if (voices == null) {
                return;
            }
            for (Voice voice : voices) {
                if (wanted.equals(voice.getName())) {
                    tts.setVoice(voice);
                    return;
                }
            }
        } catch (Exception ignored) {
        }
    }

    private void pump() {
        if (!ready || tts == null || speaking) {
            return;
        }
        String next = queue.pollFirst();
        if (next == null) {
            return;
        }
        applyVoice();
        try {
            AudioManager am = (AudioManager) getSystemService(AUDIO_SERVICE);
            if (am != null) {
                int max = am.getStreamMaxVolume(AudioManager.STREAM_MUSIC);
                int vol = Math.round(Prefs.volume(this) * max);
                am.setStreamVolume(AudioManager.STREAM_MUSIC, vol, 0);
            }
            Bundle params = new Bundle();
            params.putFloat(TextToSpeech.Engine.KEY_PARAM_VOLUME, Prefs.volume(this));
            tts.speak(next, TextToSpeech.QUEUE_FLUSH, params, "aichat");
            speaking = true;
        } catch (Exception ignored) {
            speaking = false;
        }
    }

    private void startInForeground() {
        String ch = "tts";
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel channel = new NotificationChannel(
                    ch, "AI Chat голос", NotificationManager.IMPORTANCE_LOW);
            NotificationManager nm = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
            if (nm != null) {
                nm.createNotificationChannel(channel);
            }
        }
        Intent open = new Intent(this, ChatActivity.class);
        int flags = PendingIntent.FLAG_UPDATE_CURRENT;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            flags |= PendingIntent.FLAG_IMMUTABLE;
        }
        PendingIntent pi = PendingIntent.getActivity(this, 2, open, flags);
        Notification.Builder b;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            b = new Notification.Builder(this, ch);
        } else {
            b = new Notification.Builder(this);
        }
        Notification n = b
                .setContentTitle("AI Chat")
                .setContentText(speaking ? "озвучка ответа" : "голос готов")
                .setSmallIcon(android.R.drawable.ic_lock_silent_mode_off)
                .setContentIntent(pi)
                .setOngoing(true)
                .build();
        startForeground(21, n);
    }

    @Override
    public void onDestroy() {
        queue.clear();
        speaking = false;
        if (tts != null) {
            try {
                tts.stop();
                tts.shutdown();
            } catch (Exception ignored) {
            }
            tts = null;
        }
        ready = false;
        super.onDestroy();
    }
}
