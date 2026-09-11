package com.changanhub.player;

import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.media.AudioManager;
import android.media.MediaPlayer;
import android.os.Bundle;
import android.os.Handler;
import android.view.MotionEvent;
import android.view.SurfaceHolder;
import android.view.SurfaceView;
import android.view.View;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.SeekBar;
import android.widget.TextView;

import java.io.File;
import java.util.ArrayList;

public class VideoActivity extends Activity implements
        SurfaceHolder.Callback,
        MediaPlayer.OnPreparedListener,
        MediaPlayer.OnCompletionListener,
        MediaPlayer.OnErrorListener {

    public static void start(Context context, ArrayList<String> paths, int index) {
        Intent intent = new Intent(context, VideoActivity.class);
        intent.putStringArrayListExtra(PlayerService.EXTRA_QUEUE, paths);
        intent.putExtra("start", index);
        context.startActivity(intent);
    }

    private SurfaceView surface;
    private LinearLayout controls;
    private TextView track;
    private SeekBar seek;
    private Button play;
    private MediaPlayer player;
    private ArrayList<String> queue = new ArrayList<>();
    private int index;
    private boolean seeking;
    private boolean prepared;
    private final Handler handler = new Handler();
    private final Runnable hide = new Runnable() {
        @Override
        public void run() {
            if (player != null && player.isPlaying()) {
                controls.setVisibility(View.GONE);
            }
        }
    };
    private final Runnable tick = new Runnable() {
        @Override
        public void run() {
            if (player != null && prepared && !seeking) {
                try {
                    seek.setMax(Math.max(1, player.getDuration()));
                    seek.setProgress(player.getCurrentPosition());
                } catch (Exception ignored) {
                }
            }
            handler.postDelayed(this, 400);
        }
    };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        if (PlayerService.isPlaying()) {
            PlayerService.command(this, PlayerService.ACTION_PAUSE);
        }
        setContentView(R.layout.activity_video);
        surface = findViewById(R.id.surface);
        controls = findViewById(R.id.controls);
        track = findViewById(R.id.track);
        seek = findViewById(R.id.seek);
        play = findViewById(R.id.btn_play);
        ArrayList<String> q = getIntent().getStringArrayListExtra(PlayerService.EXTRA_QUEUE);
        if (q != null) {
            queue.addAll(q);
        }
        index = getIntent().getIntExtra("start", 0);
        surface.getHolder().addCallback(this);
        findViewById(R.id.btn_prev).setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                skip(-1);
            }
        });
        findViewById(R.id.btn_next).setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                skip(1);
            }
        });
        play.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                toggle();
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
                try {
                    if (player != null && prepared) {
                        player.seekTo(seekBar.getProgress());
                    }
                } catch (Exception ignored) {
                }
            }
        });
        surface.setOnTouchListener(new View.OnTouchListener() {
            @Override
            public boolean onTouch(View v, MotionEvent event) {
                if (event.getAction() == MotionEvent.ACTION_UP) {
                    controls.setVisibility(View.VISIBLE);
                    handler.removeCallbacks(hide);
                    handler.postDelayed(hide, 3500);
                }
                return true;
            }
        });
    }

    @Override
    public void surfaceCreated(SurfaceHolder holder) {
        open(holder);
        handler.post(tick);
        handler.postDelayed(hide, 3500);
    }

    @Override
    public void surfaceChanged(SurfaceHolder holder, int format, int width, int height) {
    }

    @Override
    public void surfaceDestroyed(SurfaceHolder holder) {
        release();
    }

    private void open(SurfaceHolder holder) {
        if (queue.isEmpty()) {
            finish();
            return;
        }
        if (index < 0 || index >= queue.size()) {
            index = 0;
        }
        String path = queue.get(index);
        track.setText(new File(path).getName());
        release();
        prepared = false;
        player = new MediaPlayer();
        player.setAudioStreamType(AudioManager.STREAM_MUSIC);
        player.setOnPreparedListener(this);
        player.setOnCompletionListener(this);
        player.setOnErrorListener(this);
        try {
            player.setDisplay(holder);
            player.setDataSource(path);
            player.prepareAsync();
        } catch (Exception e) {
            skip(1);
        }
    }

    @Override
    public void onPrepared(MediaPlayer mp) {
        prepared = true;
        try {
            mp.start();
            play.setText("❚❚");
        } catch (Exception ignored) {
        }
    }

    @Override
    public void onCompletion(MediaPlayer mp) {
        skip(1);
    }

    @Override
    public boolean onError(MediaPlayer mp, int what, int extra) {
        track.setText("ГУ не открыла это видео: " + new File(queue.get(index)).getName());
        return true;
    }

    private void toggle() {
        if (player == null || !prepared) {
            return;
        }
        try {
            if (player.isPlaying()) {
                player.pause();
                play.setText("▶");
            } else {
                player.start();
                play.setText("❚❚");
            }
        } catch (Exception ignored) {
        }
    }

    private void skip(int dir) {
        if (queue.isEmpty()) {
            return;
        }
        index = (index + dir + queue.size()) % queue.size();
        if (surface.getHolder().getSurface().isValid()) {
            open(surface.getHolder());
        }
    }

    private void release() {
        if (player != null) {
            try {
                player.reset();
                player.release();
            } catch (Exception ignored) {
            }
            player = null;
        }
        prepared = false;
    }

    @Override
    protected void onDestroy() {
        handler.removeCallbacks(tick);
        handler.removeCallbacks(hide);
        release();
        super.onDestroy();
    }
}
