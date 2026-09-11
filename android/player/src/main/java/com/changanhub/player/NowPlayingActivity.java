package com.changanhub.player;

import android.app.Activity;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.media.audiofx.Equalizer;
import android.os.Bundle;
import android.os.Handler;
import android.view.View;
import android.widget.Button;
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
    private VisualizerView viz;
    private LinearLayout presets;
    private LinearLayout bands;
    private boolean seeking;
    private int attachedSession = -1;
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
        viz = findViewById(R.id.viz);
        presets = findViewById(R.id.presets);
        bands = findViewById(R.id.eq_bands);
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
                startService(intent);
            }
        });
        buildEq();
        refresh();
    }

    @Override
    protected void onResume() {
        super.onResume();
        registerReceiver(status, new IntentFilter(PlayerService.ACTION_STATUS));
        handler.post(tick);
        refresh();
    }

    @Override
    protected void onPause() {
        handler.removeCallbacks(tick);
        try {
            unregisterReceiver(status);
        } catch (Exception ignored) {
        }
        super.onPause();
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
        int session = PlayerService.sessionId();
        if (session > 0 && session != attachedSession) {
            viz.attach(session);
            attachedSession = session;
            buildEq();
        }
        refreshProgress();
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

    private void buildEq() {
        presets.removeAllViews();
        bands.removeAllViews();
        Equalizer eq = PlayerService.equalizer();
        if (eq == null) {
            TextView hint = new TextView(this);
            hint.setText("Эквалайзер подключится после старта трека");
            hint.setTextColor(0xFF9AA7B8);
            hint.setTextSize(14);
            bands.addView(hint);
            return;
        }
        try {
            short n = eq.getNumberOfPresets();
            for (short i = 0; i < n; i++) {
                final short preset = i;
                Button b = new Button(this);
                b.setText(eq.getPresetName(i));
                b.setTextColor(0xFF0B1220);
                b.setBackgroundColor(0xFF3DDC97);
                b.setOnClickListener(new View.OnClickListener() {
                    @Override
                    public void onClick(View v) {
                        Intent intent = new Intent(NowPlayingActivity.this, PlayerService.class);
                        intent.setAction(PlayerService.ACTION_EQ_PRESET);
                        intent.putExtra(PlayerService.EXTRA_PRESET, (int) preset);
                        startService(intent);
                        v.postDelayed(new Runnable() {
                            @Override
                            public void run() {
                                buildEq();
                            }
                        }, 150);
                    }
                });
                LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                        LinearLayout.LayoutParams.WRAP_CONTENT, 56);
                lp.setMargins(0, 0, 8, 0);
                presets.addView(b, lp);
            }
            short[] range = eq.getBandLevelRange();
            short bandCount = eq.getNumberOfBands();
            for (short b = 0; b < bandCount; b++) {
                final short band = b;
                TextView label = new TextView(this);
                int hz = eq.getCenterFreq(b) / 1000;
                label.setText(hz >= 1000 ? (hz / 1000) + " кГц" : hz + " Гц");
                label.setTextColor(0xFFF3F6FB);
                SeekBar bar = new SeekBar(this);
                bar.setMax(range[1] - range[0]);
                bar.setProgress(eq.getBandLevel(b) - range[0]);
                bar.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener() {
                    @Override
                    public void onProgressChanged(SeekBar seekBar, int progress, boolean fromUser) {
                        if (!fromUser) {
                            return;
                        }
                        Intent intent = new Intent(NowPlayingActivity.this, PlayerService.class);
                        intent.setAction(PlayerService.ACTION_EQ_BAND);
                        intent.putExtra(PlayerService.EXTRA_BAND, (int) band);
                        intent.putExtra(PlayerService.EXTRA_LEVEL, progress + range[0]);
                        startService(intent);
                    }

                    @Override
                    public void onStartTrackingTouch(SeekBar seekBar) {
                    }

                    @Override
                    public void onStopTrackingTouch(SeekBar seekBar) {
                    }
                });
                bands.addView(label);
                bands.addView(bar);
            }
        } catch (Exception e) {
            TextView hint = new TextView(this);
            hint.setText("эквалайзер недоступен на этом тракте ГУ");
            hint.setTextColor(0xFF9AA7B8);
            bands.addView(hint);
        }
    }

    private static String fmt(int ms) {
        int sec = Math.max(0, ms / 1000);
        return String.format(Locale.US, "%d:%02d", sec / 60, sec % 60);
    }
}
