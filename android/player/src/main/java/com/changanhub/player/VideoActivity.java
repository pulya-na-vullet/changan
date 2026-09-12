package com.changanhub.player;

import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.media.AudioManager;
import android.media.MediaPlayer;
import android.os.Bundle;
import android.os.Handler;
import android.view.KeyEvent;
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
import java.util.List;

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
    private TextView subtitle;
    private SeekBar seek;
    private Button play;
    private Button audioBtn;
    private Button subsBtn;
    private MediaPlayer player;
    private ArrayList<String> queue = new ArrayList<>();
    private final List<Integer> audioTracks = new ArrayList<>();
    private int index;
    private int audioIndex;
    private boolean seeking;
    private boolean prepared;
    private boolean resumeAfterPause;
    private boolean subsOn = true;
    private SrtSubtitles cues = new SrtSubtitles();
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
                    int pos = player.getCurrentPosition();
                    seek.setMax(Math.max(1, player.getDuration()));
                    seek.setProgress(pos);
                    if (subsOn && !cues.isEmpty()) {
                        subtitle.setText(cues.at(pos));
                    } else if (!subsOn) {
                        subtitle.setText("");
                    }
                } catch (Exception ignored) {
                }
            }
            handler.postDelayed(this, 250);
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
        subtitle = findViewById(R.id.subtitle);
        seek = findViewById(R.id.seek);
        play = findViewById(R.id.btn_play);
        audioBtn = findViewById(R.id.btn_audio);
        subsBtn = findViewById(R.id.btn_subs);
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
        audioBtn.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                cycleAudio();
            }
        });
        subsBtn.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                subsOn = !subsOn;
                if (!subsOn) {
                    subtitle.setText("");
                }
                labelSubs();
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
        labelSubs();
    }

    @Override
    public boolean onKeyDown(int keyCode, KeyEvent event) {
        if (keyCode == KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE
                || keyCode == KeyEvent.KEYCODE_HEADSETHOOK
                || keyCode == KeyEvent.KEYCODE_MEDIA_PLAY
                || keyCode == KeyEvent.KEYCODE_MEDIA_PAUSE
                || keyCode == KeyEvent.KEYCODE_DPAD_CENTER
                || keyCode == KeyEvent.KEYCODE_ENTER) {
            toggle();
            return true;
        }
        if (keyCode == KeyEvent.KEYCODE_MEDIA_NEXT) {
            skip(1);
            return true;
        }
        if (keyCode == KeyEvent.KEYCODE_MEDIA_PREVIOUS) {
            skip(-1);
            return true;
        }
        if (keyCode == KeyEvent.KEYCODE_MEDIA_FAST_FORWARD) {
            nudge(15000);
            return true;
        }
        if (keyCode == KeyEvent.KEYCODE_MEDIA_REWIND) {
            nudge(-15000);
            return true;
        }
        return super.onKeyDown(keyCode, event);
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
        File file = new File(path);
        track.setText(file.getName());
        cues = SrtSubtitles.load(SrtSubtitles.sidecar(file));
        subtitle.setText("");
        audioTracks.clear();
        audioIndex = 0;
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
        collectAudio();
        try {
            mp.start();
            play.setText("❚❚");
        } catch (Exception ignored) {
        }
        labelAudio();
        labelSubs();
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

    private void collectAudio() {
        audioTracks.clear();
        if (player == null) {
            return;
        }
        try {
            MediaPlayer.TrackInfo[] infos = player.getTrackInfo();
            for (int i = 0; i < infos.length; i++) {
                if (infos[i].getTrackType() == MediaPlayer.TrackInfo.MEDIA_TRACK_TYPE_AUDIO) {
                    audioTracks.add(i);
                }
            }
        } catch (Exception ignored) {
        }
    }

    private void cycleAudio() {
        if (player == null || !prepared || audioTracks.size() < 2) {
            labelAudio();
            return;
        }
        audioIndex = (audioIndex + 1) % audioTracks.size();
        try {
            player.selectTrack(audioTracks.get(audioIndex));
        } catch (Exception ignored) {
        }
        labelAudio();
    }

    private void labelAudio() {
        if (audioTracks.size() <= 1) {
            audioBtn.setText("Звук");
        } else {
            audioBtn.setText("Звук " + (audioIndex + 1) + "/" + audioTracks.size());
        }
    }

    private void labelSubs() {
        String mark = cues.isEmpty() ? "нет SRT" : (subsOn ? "SRT вкл" : "SRT выкл");
        subsBtn.setText(mark);
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

    private void nudge(int delta) {
        if (player == null || !prepared) {
            return;
        }
        try {
            int next = Math.max(0, player.getCurrentPosition() + delta);
            player.seekTo(next);
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
    protected void onPause() {
        resumeAfterPause = false;
        if (player != null && prepared) {
            try {
                if (player.isPlaying()) {
                    resumeAfterPause = true;
                    player.pause();
                    play.setText("▶");
                }
            } catch (Exception ignored) {
            }
        }
        super.onPause();
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (resumeAfterPause && player != null && prepared) {
            try {
                player.start();
                play.setText("❚❚");
            } catch (Exception ignored) {
            }
            resumeAfterPause = false;
        }
    }

    @Override
    protected void onDestroy() {
        handler.removeCallbacks(tick);
        handler.removeCallbacks(hide);
        release();
        super.onDestroy();
    }
}
