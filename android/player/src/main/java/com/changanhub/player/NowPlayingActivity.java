package com.changanhub.player;

import android.app.Activity;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.graphics.BitmapFactory;
import android.os.Bundle;
import android.os.Handler;
import android.view.KeyEvent;
import android.view.View;
import android.widget.Button;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.SeekBar;
import android.widget.TextView;

import java.io.File;
import java.util.Locale;

public class NowPlayingActivity extends Activity {
    private TextView track;
    private TextView folder;
    private TextView time;
    private SeekBar seek;
    private Button play;
    private Button shuffle;
    private Button repeat;
    private ImageView cover;
    private VisualizerView viz;
    private GlFogView glFog;
    private LinearLayout vizModes;
    private boolean seeking;
    private int attachedSession = -1;
    private String coverPath = "";
    private final Handler handler = new Handler();
    private final BroadcastReceiver status = new BroadcastReceiver() {
        @Override
        public void onReceive(Context context, Intent intent) {
            refresh();
        }
    };
    private final Runnable tick = new Runnable() {
        @Override
        public void run() {
            refreshProgress();
            handler.postDelayed(this, 400);
        }
    };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_now_playing);
        track = findViewById(R.id.track);
        folder = findViewById(R.id.folder);
        time = findViewById(R.id.time);
        seek = findViewById(R.id.seek);
        play = findViewById(R.id.btn_play);
        shuffle = findViewById(R.id.btn_shuffle);
        repeat = findViewById(R.id.btn_repeat);
        cover = findViewById(R.id.cover);
        viz = findViewById(R.id.viz);
        glFog = findViewById(R.id.gl_fog);
        vizModes = findViewById(R.id.viz_modes);
        findViewById(R.id.btn_prev).setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                PlayerService.command(NowPlayingActivity.this, PlayerService.ACTION_PREV);
            }
        });
        findViewById(R.id.btn_next).setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                PlayerService.command(NowPlayingActivity.this, PlayerService.ACTION_NEXT);
            }
        });
        play.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                PlayerService.command(NowPlayingActivity.this, PlayerService.ACTION_TOGGLE);
            }
        });
        shuffle.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                PlayerService.command(NowPlayingActivity.this, PlayerService.ACTION_SHUFFLE);
            }
        });
        repeat.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                PlayerService.command(NowPlayingActivity.this, PlayerService.ACTION_REPEAT);
            }
        });
        seek.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener() {
            @Override
            public void onProgressChanged(SeekBar seekBar, int progress, boolean fromUser) {
            }

            @Override
            public void onStartTrackingTouch(SeekBar seekBar) {
                seeking = true;
            }

            @Override
            public void onStopTrackingTouch(SeekBar seekBar) {
                seeking = false;
                Intent intent = new Intent(NowPlayingActivity.this, PlayerService.class);
                intent.setAction(PlayerService.ACTION_SEEK);
                intent.putExtra(PlayerService.EXTRA_MS, seekBar.getProgress());
                PlayerService.send(NowPlayingActivity.this, intent);
            }
        });
        buildVizModes();
        refresh();
    }

    @Override
    protected void onResume() {
        super.onResume();
        registerReceiver(status, new IntentFilter(PlayerService.ACTION_STATUS));
        handler.post(tick);
        if (EqPrefs.vizMode(this) == VisualizerView.MODE_FOG) {
            glFog.onResume();
        }
        refresh();
    }

    @Override
    protected void onPause() {
        handler.removeCallbacks(tick);
        try {
            unregisterReceiver(status);
        } catch (Exception ignored) {
        }
        viz.release();
        attachedSession = -1;
        glFog.onPause();
        super.onPause();
    }

    @Override
    public boolean onKeyDown(int keyCode, KeyEvent event) {
        if (keyCode == KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE
                || keyCode == KeyEvent.KEYCODE_HEADSETHOOK
                || keyCode == KeyEvent.KEYCODE_MEDIA_PLAY
                || keyCode == KeyEvent.KEYCODE_MEDIA_PAUSE) {
            PlayerService.command(this, PlayerService.ACTION_TOGGLE);
            return true;
        }
        if (keyCode == KeyEvent.KEYCODE_MEDIA_NEXT) {
            PlayerService.command(this, PlayerService.ACTION_NEXT);
            return true;
        }
        if (keyCode == KeyEvent.KEYCODE_MEDIA_PREVIOUS) {
            PlayerService.command(this, PlayerService.ACTION_PREV);
            return true;
        }
        return super.onKeyDown(keyCode, event);
    }

    private void refresh() {
        String name = PlayerService.title();
        if (name.length() == 0) {
            name = "выберите файл на флешке";
        }
        String err = PlayerService.error();
        track.setText(err.length() > 0 ? err : name);
        String path = PlayerService.currentPath();
        File file = path.length() == 0 ? null : new File(path);
        folder.setText(file != null && file.getParentFile() != null
                ? file.getParentFile().getAbsolutePath()
                : getString(R.string.usb));
        play.setText(PlayerService.isPlaying() ? "❚❚" : "▶");
        shuffle.setTextColor(PlayerService.shuffle() ? 0xFF0B1220 : 0xFFF3F6FB);
        shuffle.setBackgroundColor(PlayerService.shuffle() ? 0xFF3DDC97 : 0xFF182235);
        int rep = PlayerService.repeat();
        repeat.setText(rep == 2 ? "①" : (rep == 1 ? "∞" : "—"));
        int session = PlayerService.sessionId();
        if (session > 0 && session != attachedSession) {
            viz.attach(session);
            attachedSession = session;
        }
        loadCover(file);
        refreshProgress();
    }

    private void loadCover(File file) {
        String path = file == null ? "" : file.getAbsolutePath();
        if (path.equals(coverPath)) {
            return;
        }
        coverPath = path;
        cover.setImageDrawable(null);
        if (file == null) {
            return;
        }
        byte[] pic = Tags.picture(file);
        if (pic != null && pic.length > 0) {
            cover.setImageBitmap(BitmapFactory.decodeByteArray(pic, 0, pic.length));
        }
    }

    private void refreshProgress() {
        int dur = Math.max(0, PlayerService.duration());
        int pos = Math.max(0, PlayerService.position());
        if (!seeking) {
            seek.setMax(dur > 0 ? dur : 1);
            seek.setProgress(pos);
        }
        time.setText(fmt(pos) + "  /  " + fmt(dur));
    }

    private void buildVizModes() {
        vizModes.removeAllViews();
        String[] names = {"Спектр", "Волна", "Частицы", "Круг", "Туман"};
        int current = EqPrefs.vizMode(this);
        for (int i = 0; i < names.length; i++) {
            final int mode = i;
            Button b = new Button(this);
            b.setText(names[i]);
            boolean on = i == current;
            b.setTextColor(on ? 0xFF0B1220 : 0xFFF3F6FB);
            b.setBackgroundColor(on ? 0xFF3DDC97 : 0xFF223049);
            b.setOnClickListener(new View.OnClickListener() {
                @Override
                public void onClick(View v) {
                    EqPrefs.putInt(NowPlayingActivity.this, "viz_mode", mode);
                    applyVizMode(mode);
                    buildVizModes();
                }
            });
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.WRAP_CONTENT, 48);
            lp.setMargins(0, 0, 6, 0);
            vizModes.addView(b, lp);
        }
        applyVizMode(current);
    }

    private void applyVizMode(int mode) {
        viz.setMode(mode);
        boolean fog = mode == VisualizerView.MODE_FOG;
        glFog.setVisibility(fog ? View.VISIBLE : View.GONE);
        viz.setVisibility(fog ? View.GONE : View.VISIBLE);
        if (fog) {
            glFog.onResume();
        } else {
            glFog.onPause();
        }
    }

    private static String fmt(int ms) {
        int sec = Math.max(0, ms / 1000);
        return String.format(Locale.US, "%d:%02d", sec / 60, sec % 60);
    }
}
