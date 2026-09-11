package com.changanhub.player;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.media.AudioManager;
import android.media.MediaPlayer;
import android.media.audiofx.BassBoost;
import android.media.audiofx.Equalizer;
import android.os.Build;
import android.os.IBinder;
import android.os.PowerManager;

import java.io.File;
import java.util.ArrayList;
import java.util.List;

/** Background audio for USB music so Nav can stay on screen. */
public class PlayerService extends Service implements
        MediaPlayer.OnPreparedListener,
        MediaPlayer.OnCompletionListener,
        MediaPlayer.OnErrorListener,
        AudioManager.OnAudioFocusChangeListener {

    public static final String ACTION_PLAY = "com.changanhub.player.PLAY";
    public static final String ACTION_TOGGLE = "com.changanhub.player.TOGGLE";
    public static final String ACTION_PAUSE = "com.changanhub.player.PAUSE";
    public static final String ACTION_NEXT = "com.changanhub.player.NEXT";
    public static final String ACTION_PREV = "com.changanhub.player.PREV";
    public static final String ACTION_SEEK = "com.changanhub.player.SEEK";
    public static final String ACTION_EQ_PRESET = "com.changanhub.player.EQ_PRESET";
    public static final String ACTION_EQ_BAND = "com.changanhub.player.EQ_BAND";
    public static final String ACTION_STATUS = "com.changanhub.player.STATUS";
    public static final String EXTRA_PATH = "path";
    public static final String EXTRA_QUEUE = "queue";
    public static final String EXTRA_MS = "ms";
    public static final String EXTRA_PRESET = "preset";
    public static final String EXTRA_BAND = "band";
    public static final String EXTRA_LEVEL = "level";

    private static MediaPlayer player;
    private static Equalizer equalizer;
    private static BassBoost bass;
    private static final List<String> queue = new ArrayList<>();
    private static int index;
    private static String title = "";
    private static String error = "";
    private static int audioSession;
    private PowerManager.WakeLock wakeLock;
    private AudioManager audioManager;

    public static boolean isPlaying() {
        try {
            return player != null && player.isPlaying();
        } catch (Exception e) {
            return false;
        }
    }

    public static int position() {
        try {
            return player != null ? player.getCurrentPosition() : 0;
        } catch (Exception e) {
            return 0;
        }
    }

    public static int duration() {
        try {
            return player != null ? player.getDuration() : 0;
        } catch (Exception e) {
            return 0;
        }
    }

    public static String title() {
        return title == null ? "" : title;
    }

    public static String error() {
        return error == null ? "" : error;
    }

    public static int sessionId() {
        return audioSession;
    }

    public static Equalizer equalizer() {
        return equalizer;
    }

    public static String currentPath() {
        if (index < 0 || index >= queue.size()) {
            return "";
        }
        return queue.get(index);
    }

    public static void play(Context context, List<String> paths, int start) {
        Intent intent = new Intent(context, PlayerService.class);
        intent.setAction(ACTION_PLAY);
        intent.putStringArrayListExtra(EXTRA_QUEUE, new ArrayList<String>(paths));
        intent.putExtra("start", start);
        startSvc(context, intent);
    }

    public static void command(Context context, String action) {
        Intent intent = new Intent(context, PlayerService.class);
        intent.setAction(action);
        startSvc(context, intent);
    }

    private static void startSvc(Context context, Intent intent) {
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
        PowerManager pm = (PowerManager) getSystemService(POWER_SERVICE);
        if (pm != null) {
            wakeLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "lamoreplayer:play");
            wakeLock.setReferenceCounted(false);
        }
        startInForeground();
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        startInForeground();
        String action = intent != null ? intent.getAction() : ACTION_TOGGLE;
        if (ACTION_PLAY.equals(action) && intent != null) {
            ArrayList<String> q = intent.getStringArrayListExtra(EXTRA_QUEUE);
            if (q != null && !q.isEmpty()) {
                queue.clear();
                queue.addAll(q);
                index = intent.getIntExtra("start", 0);
                if (index < 0 || index >= queue.size()) {
                    index = 0;
                }
                openCurrent();
            }
        } else if (ACTION_TOGGLE.equals(action)) {
            toggle();
        } else if (ACTION_PAUSE.equals(action)) {
            pauseOnly();
        } else if (ACTION_NEXT.equals(action)) {
            skip(1);
        } else if (ACTION_PREV.equals(action)) {
            skip(-1);
        } else if (ACTION_SEEK.equals(action) && intent != null) {
            seek(intent.getIntExtra(EXTRA_MS, 0));
        } else if (ACTION_EQ_PRESET.equals(action) && intent != null) {
            applyPreset(intent.getIntExtra(EXTRA_PRESET, 0));
        } else if (ACTION_EQ_BAND.equals(action) && intent != null) {
            applyBand(intent.getIntExtra(EXTRA_BAND, 0), (short) intent.getIntExtra(EXTRA_LEVEL, 0));
        }
        broadcast();
        return START_STICKY;
    }

    private void openCurrent() {
        error = "";
        if (index < 0 || index >= queue.size()) {
            return;
        }
        String path = queue.get(index);
        title = new File(path).getName();
        releasePlayer(false);
        player = new MediaPlayer();
        player.setWakeMode(getApplicationContext(), PowerManager.PARTIAL_WAKE_LOCK);
        player.setAudioStreamType(AudioManager.STREAM_MUSIC);
        player.setOnPreparedListener(this);
        player.setOnCompletionListener(this);
        player.setOnErrorListener(this);
        try {
            player.setDataSource(path);
            player.prepareAsync();
        } catch (Exception e) {
            error = "не открылось: " + title;
            skip(1);
        }
    }

    @Override
    public void onPrepared(MediaPlayer mp) {
        requestFocus();
        audioSession = mp.getAudioSessionId();
        attachFx(audioSession);
        try {
            mp.start();
        } catch (Exception ignored) {
        }
        if (wakeLock != null && !wakeLock.isHeld()) {
            wakeLock.acquire();
        }
        startInForeground();
        broadcast();
    }

    @Override
    public void onCompletion(MediaPlayer mp) {
        skip(1);
    }

    @Override
    public boolean onError(MediaPlayer mp, int what, int extra) {
        error = "ГУ не проиграла этот файл (кодек): " + title;
        skip(1);
        return true;
    }

    private void pauseOnly() {
        if (player == null) {
            return;
        }
        try {
            if (player.isPlaying()) {
                player.pause();
                if (wakeLock != null && wakeLock.isHeld()) {
                    wakeLock.release();
                }
            }
        } catch (Exception ignored) {
        }
        startInForeground();
    }

    private void toggle() {
        if (player == null) {
            return;
        }
        try {
            if (player.isPlaying()) {
                player.pause();
                if (wakeLock != null && wakeLock.isHeld()) {
                    wakeLock.release();
                }
            } else {
                requestFocus();
                player.start();
                if (wakeLock != null && !wakeLock.isHeld()) {
                    wakeLock.acquire();
                }
            }
        } catch (Exception ignored) {
        }
        startInForeground();
    }

    private void skip(int dir) {
        if (queue.isEmpty()) {
            return;
        }
        index = (index + dir + queue.size()) % queue.size();
        openCurrent();
    }

    private void seek(int ms) {
        try {
            if (player != null) {
                player.seekTo(ms);
            }
        } catch (Exception ignored) {
        }
    }

    private void attachFx(int session) {
        releaseFx();
        try {
            equalizer = new Equalizer(0, session);
            equalizer.setEnabled(true);
        } catch (Exception e) {
            equalizer = null;
        }
        try {
            bass = new BassBoost(0, session);
            bass.setEnabled(true);
            bass.setStrength((short) 500);
        } catch (Exception e) {
            bass = null;
        }
    }

    private void applyPreset(int preset) {
        if (equalizer == null) {
            return;
        }
        try {
            short n = equalizer.getNumberOfPresets();
            if (preset >= 0 && preset < n) {
                equalizer.usePreset((short) preset);
            }
        } catch (Exception ignored) {
        }
    }

    private void applyBand(int band, short level) {
        if (equalizer == null) {
            return;
        }
        try {
            short[] range = equalizer.getBandLevelRange();
            if (level < range[0]) {
                level = range[0];
            }
            if (level > range[1]) {
                level = range[1];
            }
            equalizer.setBandLevel((short) band, level);
        } catch (Exception ignored) {
        }
    }

    private void requestFocus() {
        if (audioManager != null) {
            audioManager.requestAudioFocus(this, AudioManager.STREAM_MUSIC,
                    AudioManager.AUDIOFOCUS_GAIN);
        }
    }

    @Override
    public void onAudioFocusChange(int focusChange) {
        if (player == null) {
            return;
        }
        try {
            if (focusChange == AudioManager.AUDIOFOCUS_LOSS
                    || focusChange == AudioManager.AUDIOFOCUS_LOSS_TRANSIENT) {
                if (player.isPlaying()) {
                    player.pause();
                }
            } else if (focusChange == AudioManager.AUDIOFOCUS_GAIN) {
                player.start();
            }
        } catch (Exception ignored) {
        }
        broadcast();
    }

    private void broadcast() {
        Intent i = new Intent(ACTION_STATUS);
        i.setPackage(getPackageName());
        sendBroadcast(i);
    }

    private void startInForeground() {
        String ch = "player";
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel channel = new NotificationChannel(
                    ch, "Lamore Player", NotificationManager.IMPORTANCE_LOW);
            NotificationManager nm = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
            if (nm != null) {
                nm.createNotificationChannel(channel);
            }
        }
        Intent open = new Intent(this, NowPlayingActivity.class);
        int flags = PendingIntent.FLAG_UPDATE_CURRENT;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            flags |= PendingIntent.FLAG_IMMUTABLE;
        }
        PendingIntent pi = PendingIntent.getActivity(this, 1, open, flags);
        Notification.Builder b;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            b = new Notification.Builder(this, ch);
        } else {
            b = new Notification.Builder(this);
        }
        Notification n = b
                .setContentTitle("Lamore Player")
                .setContentText(isPlaying() ? title : (title.length() == 0 ? "флешка ГУ" : "пауза · " + title))
                .setSmallIcon(android.R.drawable.ic_media_play)
                .setContentIntent(pi)
                .setOngoing(true)
                .build();
        startForeground(11, n);
    }

    private void releaseFx() {
        if (equalizer != null) {
            try {
                equalizer.release();
            } catch (Exception ignored) {
            }
            equalizer = null;
        }
        if (bass != null) {
            try {
                bass.release();
            } catch (Exception ignored) {
            }
            bass = null;
        }
    }

    private void releasePlayer(boolean fx) {
        if (player != null) {
            try {
                player.reset();
                player.release();
            } catch (Exception ignored) {
            }
            player = null;
        }
        if (fx) {
            releaseFx();
        }
    }

    @Override
    public void onDestroy() {
        if (wakeLock != null && wakeLock.isHeld()) {
            wakeLock.release();
        }
        if (audioManager != null) {
            audioManager.abandonAudioFocus(this);
        }
        releasePlayer(true);
        super.onDestroy();
    }
}
