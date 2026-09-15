package com.changanhub.chat;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.media.AudioAttributes;
import android.media.AudioFormat;
import android.media.AudioManager;
import android.media.AudioTrack;
import android.media.MediaPlayer;
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

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.List;

/**
 * Speaks AI replies with bundled RHVoice (Elena). PCM is played through
 * MediaPlayer (Feiyu cabin path). AudioTrack.stop() used to drop the buffer
 * before the HU mixer heard a short test phrase.
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

    private final ByteArrayOutputStream pcm = new ByteArrayOutputStream();
    private final Object playLock = new Object();
    private boolean playDone;
    private int sampleRate = 16000;
    private Thread worker;
    private boolean quit;
    private AudioManager audioManager;

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
        audioManager = (AudioManager) getSystemService(AUDIO_SERVICE);
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
            TTSEngine.ensureLoaded(this);
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
            broadcast();
        } catch (Throwable e) {
            ready = false;
            warning = "RHVoice не запустился: " + e.getMessage();
            Log.e("RHVoice", warning, e);
            broadcast();
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
            if (warning.length() == 0) {
                warning = "голос ещё не готов";
            }
            broadcast();
            return;
        }
        stopRequested = false;
        speaking = true;
        startInForeground();
        broadcast();
        pcm.reset();
        try {
            SynthesisParameters params = new SynthesisParameters();
            String wanted = Prefs.voiceName(this);
            params.setVoiceProfile(wanted.length() > 0 ? wanted : defaultVoice);
            params.setRate(clampRel(Prefs.speechRate(this)));
            params.setPitch(clampRel(Prefs.pitch(this)));
            params.setVolume(1.0);
            engine.speak(text, params, this);
            byte[] samples = pcm.toByteArray();
            if (stopRequested) {
                return;
            }
            if (samples.length < 64) {
                warning = "RHVoice не дал звук";
                broadcast();
                return;
            }
            warning = "";
            playPcm(samples);
        } catch (RHVoiceException e) {
            warning = "RHVoice: " + e.getMessage();
            Log.e("RHVoice", warning, e);
        } catch (Throwable e) {
            warning = "озвучка: " + e.getMessage();
            Log.e("RHVoice", warning, e);
        } finally {
            speaking = false;
            startInForeground();
            broadcast();
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
        synchronized (playLock) {
            playDone = true;
            playLock.notifyAll();
        }
        speaking = false;
    }

    @Override
    public boolean setSampleRate(int rate) {
        if (rate <= 0) {
            return false;
        }
        sampleRate = rate;
        return true;
    }

    @Override
    public boolean playSpeech(short[] samples) {
        if (stopRequested || samples == null || samples.length == 0) {
            return !stopRequested;
        }
        for (int i = 0; i < samples.length; i++) {
            short s = samples[i];
            pcm.write(s & 0xFF);
            pcm.write((s >> 8) & 0xFF);
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

    private void playPcm(byte[] samples) {
        requestFocus();
        bumpMusicVolume();
        File wav = writeWav(samples);
        if (wav != null && playWav(wav)) {
            return;
        }
        playTrack(samples);
    }

    private boolean playWav(File wav) {
        MediaPlayer mp = new MediaPlayer();
        playDone = false;
        try {
            mp.setAudioAttributes(new AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_MEDIA)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                    .setLegacyStreamType(AudioManager.STREAM_MUSIC)
                    .build());
            mp.setDataSource(wav.getAbsolutePath());
            mp.setOnCompletionListener(new MediaPlayer.OnCompletionListener() {
                @Override
                public void onCompletion(MediaPlayer player) {
                    synchronized (playLock) {
                        playDone = true;
                        playLock.notifyAll();
                    }
                }
            });
            mp.setOnErrorListener(new MediaPlayer.OnErrorListener() {
                @Override
                public boolean onError(MediaPlayer player, int what, int extra) {
                    synchronized (playLock) {
                        playDone = true;
                        playLock.notifyAll();
                    }
                    return true;
                }
            });
            mp.prepare();
            mp.start();
            int wait = (int) (samplesDurationMs(wav.length()) + 1500);
            synchronized (playLock) {
                long deadline = System.currentTimeMillis() + wait;
                while (!playDone && !stopRequested && System.currentTimeMillis() < deadline) {
                    playLock.wait(200);
                }
            }
            return true;
        } catch (Exception e) {
            Log.e("RHVoice", "MediaPlayer wav", e);
            return false;
        } finally {
            try {
                mp.reset();
                mp.release();
            } catch (Exception ignored) {
            }
        }
    }

    private void playTrack(byte[] samples) {
        int min = AudioTrack.getMinBufferSize(sampleRate, AudioFormat.CHANNEL_OUT_MONO,
                AudioFormat.ENCODING_PCM_16BIT);
        if (min < 4096) {
            min = 4096;
        }
        int buf = Math.max(min * 2, samples.length);
        AudioTrack track = new AudioTrack.Builder()
                .setAudioAttributes(new AudioAttributes.Builder()
                        .setUsage(AudioAttributes.USAGE_MEDIA)
                        .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                        .setLegacyStreamType(AudioManager.STREAM_MUSIC)
                        .build())
                .setAudioFormat(new AudioFormat.Builder()
                        .setSampleRate(sampleRate)
                        .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                        .setChannelMask(AudioFormat.CHANNEL_OUT_MONO)
                        .build())
                .setBufferSizeInBytes(buf)
                .setTransferMode(AudioTrack.MODE_STATIC)
                .build();
        try {
            if (track.getState() != AudioTrack.STATE_INITIALIZED) {
                warning = "AudioTrack не открылся";
                return;
            }
            track.write(samples, 0, samples.length);
            track.play();
            int wait = (int) (samples.length * 1000L / (2 * Math.max(1, sampleRate)) + 400);
            try {
                Thread.sleep(wait);
            } catch (InterruptedException ignored) {
            }
        } finally {
            try {
                track.stop();
                track.release();
            } catch (Exception ignored) {
            }
        }
    }

    private File writeWav(byte[] pcmBytes) {
        File dest = new File(getCacheDir(), "tts.wav");
        FileOutputStream out = null;
        try {
            out = new FileOutputStream(dest);
            int rate = sampleRate > 0 ? sampleRate : 16000;
            int data = pcmBytes.length;
            int byteRate = rate * 2;
            byte[] hdr = new byte[44];
            putAscii(hdr, 0, "RIFF");
            putInt(hdr, 4, 36 + data);
            putAscii(hdr, 8, "WAVE");
            putAscii(hdr, 12, "fmt ");
            putInt(hdr, 16, 16);
            putShort(hdr, 20, 1);
            putShort(hdr, 22, 1);
            putInt(hdr, 24, rate);
            putInt(hdr, 28, byteRate);
            putShort(hdr, 32, 2);
            putShort(hdr, 34, 16);
            putAscii(hdr, 36, "data");
            putInt(hdr, 40, data);
            out.write(hdr);
            out.write(pcmBytes);
            out.flush();
            return dest;
        } catch (Exception e) {
            Log.e("RHVoice", "wav", e);
            return null;
        } finally {
            if (out != null) {
                try {
                    out.close();
                } catch (Exception ignored) {
                }
            }
        }
    }

    private static void putAscii(byte[] b, int at, String s) {
        for (int i = 0; i < s.length(); i++) {
            b[at + i] = (byte) s.charAt(i);
        }
    }

    private static void putInt(byte[] b, int at, int v) {
        b[at] = (byte) (v);
        b[at + 1] = (byte) (v >> 8);
        b[at + 2] = (byte) (v >> 16);
        b[at + 3] = (byte) (v >> 24);
    }

    private static void putShort(byte[] b, int at, int v) {
        b[at] = (byte) (v);
        b[at + 1] = (byte) (v >> 8);
    }

    private long samplesDurationMs(long wavLength) {
        long data = Math.max(0, wavLength - 44);
        return data * 1000L / (2L * Math.max(1, sampleRate));
    }

    private void requestFocus() {
        if (audioManager == null) {
            return;
        }
        try {
            audioManager.requestAudioFocus(null, AudioManager.STREAM_MUSIC,
                    AudioManager.AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK);
        } catch (Exception ignored) {
        }
    }

    private void bumpMusicVolume() {
        if (audioManager == null) {
            return;
        }
        try {
            int max = audioManager.getStreamMaxVolume(AudioManager.STREAM_MUSIC);
            int cur = audioManager.getStreamVolume(AudioManager.STREAM_MUSIC);
            if (max > 0 && cur <= 0) {
                audioManager.setStreamVolume(AudioManager.STREAM_MUSIC, Math.max(1, max / 2), 0);
            }
        } catch (Exception ignored) {
        }
    }

    private void broadcast() {
        Intent i = new Intent(ACTION_STATUS);
        i.setPackage(getPackageName());
        sendBroadcast(i);
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
