package com.changanhub.chat;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.media.AudioFormat;
import android.media.AudioManager;
import android.media.AudioTrack;
import android.os.Build;
import android.os.IBinder;
import android.util.Log;

import com.github.olga_yakovleva.rhvoice.LogLevel;
import com.github.olga_yakovleva.rhvoice.Logger;
import com.github.olga_yakovleva.rhvoice.RHVoiceException;
import com.github.olga_yakovleva.rhvoice.SynthesisParameters;
import com.github.olga_yakovleva.rhvoice.TTSClient;
import com.github.olga_yakovleva.rhvoice.TTSEngine;
import com.github.olga_yakovleva.rhvoice.VoiceInfo;

import java.io.File;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.List;

/**
 * Speaks AI replies with bundled RHVoice (Elena). Does not use Android TTS,
 * so Feiyu's missing Google/iFlytek engine does not matter.
 */
public class TtsService extends Service implements TTSClient, Logger {
    public static final String ACTION_SPEAK = "com.changanhub.aichat.SPEAK";
    public static final String ACTION_STOP = "com.changanhub.aichat.STOP";
    public static final String ACTION_PREPARE = "com.changanhub.aichat.PREPARE";
    public static final String ACTION_STATUS = "com.changanhub.aichat.TTS_STATUS";
    public static final String EXTRA_TEXT = "text";

    private static TTSEngine engine;
    private static boolean ready;
    private static String warning = "";
    private static final ArrayDeque<String> queue = new ArrayDeque<>();
    private static boolean speaking;
    private static boolean stopRequested;
    private static String defaultVoice = "Elena";
    private static final List<String> voices = new ArrayList<>();

    private AudioTrack track;
    private int sampleRate = 16000;
    private Thread worker;
    private boolean quit;

    public static void speak(Context context, String text) {
        Intent intent = new Intent(context, TtsService.class);
        intent.setAction(ACTION_SPEAK);
        intent.putExtra(EXTRA_TEXT, text);
        start(context, intent);
    }

    public static void prepare(Context context) {
        Intent intent = new Intent(context, TtsService.class);
        intent.setAction(ACTION_PREPARE);
        start(context, intent);
    }

    public static void stop(Context context) {
        Intent intent = new Intent(context, TtsService.class);
        intent.setAction(ACTION_STOP);
        start(context, intent);
    }

    public static boolean isReady() {
        return ready;
    }

    public static String warning() {
        return warning == null ? "" : warning;
    }

    public static boolean isSpeaking() {
        return speaking;
    }

    public static List<String> voiceNames() {
        synchronized (voices) {
            return new ArrayList<String>(voices);
        }
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
        quit = false;
        worker = new Thread(new Runnable() {
            @Override
            public void run() {
                loop();
            }
        }, "rhvoice");
        worker.start();
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        startInForeground();
        String action = intent != null ? intent.getAction() : ACTION_STOP;
        if (ACTION_SPEAK.equals(action) && intent != null) {
            String text = intent.getStringExtra(EXTRA_TEXT);
            if (text != null && text.trim().length() > 0) {
                synchronized (queue) {
                    queue.addLast(text.trim());
                    queue.notifyAll();
                }
            }
        } else if (ACTION_STOP.equals(action)) {
            stopNow();
        }
        return START_STICKY;
    }

    private void loop() {
        try {
            File data = RhVoiceData.ensure(this);
            File cfg = RhVoiceData.configDir(this);
            engine = new TTSEngine(data.getAbsolutePath(), cfg.getAbsolutePath(), new String[0], "", this);
            List list = engine.getVoices();
            synchronized (voices) {
                voices.clear();
                if (list != null) {
                    for (int i = 0; i < list.size(); i++) {
                        Object item = list.get(i);
                        if (item instanceof VoiceInfo) {
                            String name = ((VoiceInfo) item).getName();
                            if (name != null && name.length() > 0) {
                                voices.add(name);
                            }
                        }
                    }
                }
                if (voices.isEmpty()) {
                    voices.add("Elena");
                }
                defaultVoice = voices.get(0);
            }
            ready = true;
            warning = "";
        } catch (Throwable e) {
            ready = false;
            warning = "RHVoice не запустился: " + e.getMessage();
            Log.e("RHVoice", warning, e);
        }
        while (!quit) {
            String next = null;
            synchronized (queue) {
                while (!quit && queue.isEmpty()) {
                    try {
                        queue.wait();
                    } catch (InterruptedException ignored) {
                    }
                }
                if (!quit) {
                    next = queue.pollFirst();
                }
            }
            if (next == null) {
                continue;
            }
            speakNow(next);
        }
    }

    private void speakNow(String text) {
        if (!ready || engine == null) {
            return;
        }
        stopRequested = false;
        speaking = true;
        startInForeground();
        try {
            SynthesisParameters params = new SynthesisParameters();
            String wanted = Prefs.voiceName(this);
            params.setVoiceProfile(wanted.length() > 0 ? wanted : defaultVoice);
            params.setRate(clampRel(Prefs.speechRate(this)));
            params.setPitch(clampRel(Prefs.pitch(this)));
            params.setVolume(clampRel(Prefs.volume(this)));
            engine.speak(text, params, this);
        } catch (RHVoiceException e) {
            warning = "RHVoice: " + e.getMessage();
            Log.e("RHVoice", warning, e);
        } catch (Throwable e) {
            warning = "озвучка: " + e.getMessage();
            Log.e("RHVoice", warning, e);
        } finally {
            releaseTrack();
            speaking = false;
            startInForeground();
        }
    }

    private static double clampRel(float value) {
        if (value < 0.2f) {
            return 0.2;
        }
        if (value > 2f) {
            return 2;
        }
        return value;
    }

    private void stopNow() {
        stopRequested = true;
        synchronized (queue) {
            queue.clear();
            queue.notifyAll();
        }
        try {
            if (track != null) {
                track.stop();
            }
        } catch (Exception ignored) {
        }
        speaking = false;
    }

    @Override
    public boolean setSampleRate(int rate) {
        if (rate <= 0) {
            return false;
        }
        if (track != null && sampleRate == rate) {
            return true;
        }
        releaseTrack();
        sampleRate = rate;
        int min = AudioTrack.getMinBufferSize(rate, AudioFormat.CHANNEL_OUT_MONO, AudioFormat.ENCODING_PCM_16BIT);
        if (min < 4096) {
            min = 4096;
        }
        track = new AudioTrack(AudioManager.STREAM_MUSIC, rate, AudioFormat.CHANNEL_OUT_MONO,
                AudioFormat.ENCODING_PCM_16BIT, min * 2, AudioTrack.MODE_STREAM);
        track.play();
        return true;
    }

    @Override
    public boolean playSpeech(short[] samples) {
        if (stopRequested || samples == null || samples.length == 0) {
            return !stopRequested;
        }
        if (track == null) {
            setSampleRate(sampleRate);
        }
        int offset = 0;
        while (offset < samples.length && !stopRequested) {
            int n = track.write(samples, offset, samples.length - offset);
            if (n <= 0) {
                break;
            }
            offset += n;
        }
        return !stopRequested;
    }

    @Override
    public boolean rangeStart(int start, int end) {
        return !stopRequested;
    }

    @Override
    public void log(String tag, LogLevel level, String message) {
        if (level == LogLevel.ERROR) {
            Log.e("RHVoice", message);
        }
    }

    private void releaseTrack() {
        if (track == null) {
            return;
        }
        try {
            track.stop();
            track.release();
        } catch (Exception ignored) {
        }
        track = null;
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
                .setContentText(speaking ? "озвучка RHVoice" : "голос RHVoice готов")
                .setSmallIcon(android.R.drawable.ic_lock_silent_mode_off)
                .setContentIntent(pi)
                .setOngoing(true)
                .build();
        startForeground(21, n);
    }

    @Override
    public void onDestroy() {
        quit = true;
        stopNow();
        if (worker != null) {
            worker.interrupt();
            try {
                worker.join(1500);
            } catch (InterruptedException ignored) {
            }
        }
        if (engine != null) {
            try {
                engine.shutdown();
            } catch (Exception ignored) {
            }
            engine = null;
        }
        ready = false;
        super.onDestroy();
    }
}
