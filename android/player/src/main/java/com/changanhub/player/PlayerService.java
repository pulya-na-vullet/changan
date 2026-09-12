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
import android.media.audiofx.LoudnessEnhancer;
import android.media.audiofx.Virtualizer;
import android.os.Build;
import android.os.IBinder;
import android.os.PowerManager;

import java.io.File;
import java.util.ArrayList;
import java.util.List;
import java.util.Random;

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
    public static final String ACTION_EQ_NAMED = "com.changanhub.player.EQ_NAMED";
    public static final String ACTION_EQ_BAND = "com.changanhub.player.EQ_BAND";
    public static final String ACTION_SHUFFLE = "com.changanhub.player.SHUFFLE";
    public static final String ACTION_REPEAT = "com.changanhub.player.REPEAT";
    public static final String ACTION_FX = "com.changanhub.player.FX";
    public static final String ACTION_STATUS = "com.changanhub.player.STATUS";
    public static final String EXTRA_PATH = "path";
    public static final String EXTRA_QUEUE = "queue";
    public static final String EXTRA_MS = "ms";
    public static final String EXTRA_PRESET = "preset";
    public static final String EXTRA_NAMED = "named";
    public static final String EXTRA_BAND = "band";
    public static final String EXTRA_LEVEL = "level";
    public static final String EXTRA_KIND = "kind";
    public static final String EXTRA_VALUE = "value";

    private static MediaPlayer player;
    private static Equalizer equalizer;
    private static BassBoost bass;
    private static Virtualizer virtualizer;
    private static LoudnessEnhancer loudness;
    private static final List<String> queue = new ArrayList<>();
    private static int index;
    private static String title = "";
    private static String error = "";
    private static int audioSession;
    private static boolean shuffle;
    private static int repeat = 1;
    private static float leftVol = 1f;
    private static float rightVol = 1f;
    private static final Random random = new Random();
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

    public static List<String> queue() {
        return new ArrayList<String>(queue);
    }

    public static int index() {
        return index;
    }

    public static boolean shuffle() {
        return shuffle;
    }

    public static int repeat() {
        return repeat;
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

    public static void send(Context context, Intent intent) {
        intent.setClass(context, PlayerService.class);
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
        shuffle = EqPrefs.shuffle(this);
        repeat = EqPrefs.repeat(this);
        applyBalance(EqPrefs.balance(this));
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
        } else if (ACTION_EQ_NAMED.equals(action) && intent != null) {
            applyNamed(intent.getIntExtra(EXTRA_NAMED, 0));
        } else if (ACTION_EQ_BAND.equals(action) && intent != null) {
            applyBand(intent.getIntExtra(EXTRA_BAND, 0), (short) intent.getIntExtra(EXTRA_LEVEL, 0));
        } else if (ACTION_SHUFFLE.equals(action)) {
            shuffle = !shuffle;
            EqPrefs.putBool(this, "shuffle", shuffle);
        } else if (ACTION_REPEAT.equals(action)) {
            repeat = (repeat + 1) % 3;
            EqPrefs.putInt(this, "repeat", repeat);
        } else if (ACTION_FX.equals(action) && intent != null) {
            applyFx(intent.getStringExtra(EXTRA_KIND), intent.getIntExtra(EXTRA_VALUE, 0));
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
        Tags tags = Tags.read(new File(path));
        if (tags.title.length() > 0) {
            title = tags.title;
            if (tags.artist.length() > 0) {
                title = tags.artist + " — " + tags.title;
            }
        }
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
            mp.setVolume(leftVol, rightVol);
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
        if (repeat == 2) {
            try {
                mp.seekTo(0);
                mp.start();
            } catch (Exception e) {
                skip(1);
            }
            broadcast();
            return;
        }
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
        if (shuffle && queue.size() > 1) {
            int next = index;
            int guard = 0;
            while (next == index && guard < 12) {
                next = random.nextInt(queue.size());
                guard++;
            }
            index = next;
        } else {
            int next = index + dir;
            if (next < 0 || next >= queue.size()) {
                if (repeat == 1) {
                    index = (next + queue.size()) % queue.size();
                } else {
                    pauseOnly();
                    return;
                }
            } else {
                index = next;
            }
        }
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
            applyNamed(EqPrefs.namedPreset(this));
        } catch (Exception e) {
            equalizer = null;
        }
        try {
            bass = new BassBoost(0, session);
            bass.setEnabled(true);
            bass.setStrength((short) clamp(EqPrefs.bass(this), 0, 1000));
        } catch (Exception e) {
            bass = null;
        }
        try {
            virtualizer = new Virtualizer(0, session);
            virtualizer.setEnabled(true);
            virtualizer.setStrength((short) clamp(EqPrefs.virt(this), 0, 1000));
        } catch (Exception e) {
            virtualizer = null;
        }
        try {
            loudness = new LoudnessEnhancer(session);
            loudness.setEnabled(true);
            loudness.setTargetGain(Math.max(0, EqPrefs.loud(this)));
        } catch (Exception e) {
            loudness = null;
        }
        applyBalance(EqPrefs.balance(this));
    }

    private void applyNamed(int named) {
        EqPrefs.putInt(this, "eq_named", named);
        if (equalizer == null) {
            return;
        }
        short[] shape = EqPrefs.shape(named);
        if (named == 7) {
            for (int i = 0; i < shape.length; i++) {
                shape[i] = EqPrefs.customBand(this, i);
            }
        }
        try {
            short n = equalizer.getNumberOfBands();
            short[] range = equalizer.getBandLevelRange();
            for (short b = 0; b < n; b++) {
                int src = n <= 1 ? 0 : (int) b * (shape.length - 1) / (n - 1);
                short level = shape[Math.min(src, shape.length - 1)];
                if (level < range[0]) {
                    level = range[0];
                }
                if (level > range[1]) {
                    level = range[1];
                }
                equalizer.setBandLevel(b, level);
            }
        } catch (Exception ignored) {
        }
    }

    private void applyFx(String kind, int value) {
        if (kind == null) {
            return;
        }
        if ("bass".equals(kind)) {
            EqPrefs.putInt(this, "bass", value);
            try {
                if (bass != null) {
                    bass.setStrength((short) clamp(value, 0, 1000));
                }
            } catch (Exception ignored) {
            }
        } else if ("mids".equals(kind)) {
            EqPrefs.putInt(this, "mids", value);
            applyTone(1, value);
        } else if ("highs".equals(kind)) {
            EqPrefs.putInt(this, "highs", value);
            applyTone(2, value);
        } else if ("virt".equals(kind)) {
            EqPrefs.putInt(this, "virt", value);
            try {
                if (virtualizer != null) {
                    virtualizer.setStrength((short) clamp(value, 0, 1000));
                }
            } catch (Exception ignored) {
            }
        } else if ("loud".equals(kind)) {
            EqPrefs.putInt(this, "loud", value);
            try {
                if (loudness != null) {
                    loudness.setTargetGain(Math.max(0, value));
                }
            } catch (Exception ignored) {
            }
        } else if ("balance".equals(kind)) {
            applyBalance(value);
        } else if ("volume".equals(kind)) {
            EqPrefs.putInt(this, "volume", value);
            if (audioManager != null) {
                int max = audioManager.getStreamMaxVolume(AudioManager.STREAM_MUSIC);
                audioManager.setStreamVolume(AudioManager.STREAM_MUSIC,
                        clamp(value, 0, 100) * max / 100, 0);
            }
        }
    }

    /** third: 0 bass bands, 1 mids, 2 highs. value 0..1000 mapped to chip range. */
    private void applyTone(int third, int value) {
        if (equalizer == null) {
            return;
        }
        try {
            short n = equalizer.getNumberOfBands();
            if (n <= 0) {
                return;
            }
            short[] range = equalizer.getBandLevelRange();
            int start = third * n / 3;
            int end = third == 2 ? n : (third + 1) * n / 3;
            if (end <= start) {
                end = Math.min(n, start + 1);
            }
            short level = (short) (range[0] + (range[1] - range[0]) * clamp(value, 0, 1000) / 1000);
            for (short b = (short) start; b < end; b++) {
                equalizer.setBandLevel(b, level);
            }
            EqPrefs.putInt(this, "eq_named", 7);
        } catch (Exception ignored) {
        }
    }

    private void applyBalance(int value) {
        value = clamp(value, 0, 100);
        EqPrefs.putInt(this, "balance", value);
        float t = value / 50f;
        if (t <= 1f) {
            leftVol = 1f;
            rightVol = t;
        } else {
            leftVol = 2f - t;
            rightVol = 1f;
        }
        try {
            if (player != null) {
                player.setVolume(leftVol, rightVol);
            }
        } catch (Exception ignored) {
        }
    }

    private static int clamp(int value, int min, int max) {
        if (value < min) {
            return min;
        }
        if (value > max) {
            return max;
        }
        return value;
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
            EqPrefs.saveCustomBand(this, band, level);
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
        if (virtualizer != null) {
            try {
                virtualizer.release();
            } catch (Exception ignored) {
            }
            virtualizer = null;
        }
        if (loudness != null) {
            try {
                loudness.release();
            } catch (Exception ignored) {
            }
            loudness = null;
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
