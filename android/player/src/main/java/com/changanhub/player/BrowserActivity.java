package com.changanhub.player;

import android.Manifest;
import android.app.Activity;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.pm.PackageManager;
import android.media.audiofx.Equalizer;
import android.os.Bundle;
import android.util.DisplayMetrics;
import android.view.KeyEvent;
import android.view.View;
import android.view.ViewGroup;
import android.widget.AdapterView;
import android.widget.BaseAdapter;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ListView;
import android.widget.SeekBar;
import android.widget.TextView;

import java.io.File;
import java.util.ArrayList;
import java.util.List;

public class BrowserActivity extends Activity {
    private static final String[] PERMS = {
            Manifest.permission.READ_EXTERNAL_STORAGE,
            Manifest.permission.WRITE_EXTERNAL_STORAGE,
            Manifest.permission.RECORD_AUDIO
    };

    private View stage;
    private TextView pathView;
    private TextView empty;
    private TextView nowTitle;
    private TextView tabMusic;
    private TextView tabVideo;
    private TextView tabEq;
    private TextView tabViz;
    private View pageMedia;
    private View pageEq;
    private View pageViz;
    private ListView list;
    private Button btnSort;
    private Button btnShuffle;
    private Button btnRepeat;
    private Button btnPlay;
    private LinearLayout namedPresets;
    private LinearLayout eqBands;
    private LinearLayout vizModes;
    private EqCurveView eqCurve;
    private VisualizerView viz;
    private GlFogView glFog;
    private SeekBar eqBass;
    private SeekBar eqMids;
    private SeekBar eqHighs;
    private SeekBar eqVolume;
    private SeekBar eqBalance;
    private SeekBar eqVirt;
    private SeekBar eqLoud;
    private File cwd;
    private int tab;
    private int sortMode;
    private int attachedSession = -1;
    private boolean scanning;
    private final List<UsbMedia.Entry> rows = new ArrayList<>();
    private final Adapter adapter = new Adapter();
    private final BroadcastReceiver status = new BroadcastReceiver() {
        @Override
        public void onReceive(Context context, Intent intent) {
            refreshNow();
        }
    };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_browser);
        stage = findViewById(R.id.stage);
        applyCenterPadding();
        pathView = findViewById(R.id.path);
        empty = findViewById(R.id.empty);
        nowTitle = findViewById(R.id.now_title);
        tabMusic = findViewById(R.id.tab_music);
        tabVideo = findViewById(R.id.tab_video);
        tabEq = findViewById(R.id.tab_eq);
        tabViz = findViewById(R.id.tab_viz);
        pageMedia = findViewById(R.id.page_media);
        pageEq = findViewById(R.id.page_eq);
        pageViz = findViewById(R.id.page_viz);
        list = findViewById(R.id.list);
        btnSort = findViewById(R.id.btn_sort);
        btnShuffle = findViewById(R.id.btn_shuffle);
        btnRepeat = findViewById(R.id.btn_repeat);
        btnPlay = findViewById(R.id.btn_play);
        namedPresets = findViewById(R.id.named_presets);
        eqBands = findViewById(R.id.eq_bands);
        vizModes = findViewById(R.id.viz_modes);
        eqCurve = findViewById(R.id.eq_curve);
        viz = findViewById(R.id.viz);
        glFog = findViewById(R.id.gl_fog);
        eqBass = findViewById(R.id.eq_bass);
        eqMids = findViewById(R.id.eq_mids);
        eqHighs = findViewById(R.id.eq_highs);
        eqVolume = findViewById(R.id.eq_volume);
        eqBalance = findViewById(R.id.eq_balance);
        eqVirt = findViewById(R.id.eq_virt);
        eqLoud = findViewById(R.id.eq_loud);
        list.setAdapter(adapter);
        sortMode = EqPrefs.sortMode(this);
        tabMusic.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                showTab(0);
            }
        });
        tabVideo.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                showTab(1);
            }
        });
        tabEq.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                showTab(2);
            }
        });
        tabViz.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                showTab(3);
            }
        });
        findViewById(R.id.btn_up).setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                goUp();
            }
        });
        findViewById(R.id.btn_scan).setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                scanUsb(true);
            }
        });
        btnSort.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                sortMode = (sortMode + 1) % 4;
                EqPrefs.putInt(BrowserActivity.this, "sort", sortMode);
                labelSort();
                if (sortMode == 0) {
                    if (cwd == null) {
                        showRoots();
                    } else {
                        openDir(cwd);
                    }
                } else {
                    scanUsb(false);
                }
            }
        });
        findViewById(R.id.nowbar).setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                startActivity(new Intent(BrowserActivity.this, NowPlayingActivity.class));
            }
        });
        findViewById(R.id.btn_prev).setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                PlayerService.command(BrowserActivity.this, PlayerService.ACTION_PREV);
            }
        });
        findViewById(R.id.btn_next).setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                PlayerService.command(BrowserActivity.this, PlayerService.ACTION_NEXT);
            }
        });
        btnPlay.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                PlayerService.command(BrowserActivity.this, PlayerService.ACTION_TOGGLE);
            }
        });
        btnShuffle.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                PlayerService.command(BrowserActivity.this, PlayerService.ACTION_SHUFFLE);
            }
        });
        btnRepeat.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                PlayerService.command(BrowserActivity.this, PlayerService.ACTION_REPEAT);
            }
        });
        list.setOnItemClickListener(new AdapterView.OnItemClickListener() {
            @Override
            public void onItemClick(AdapterView<?> parent, View view, int position, long id) {
                if (position < 0 || position >= rows.size()) {
                    return;
                }
                open(rows.get(position));
            }
        });
        bindFxBar(eqBass, "bass");
        bindFxBar(eqMids, "mids");
        bindFxBar(eqHighs, "highs");
        bindFxBar(eqVolume, "volume");
        bindFxBar(eqBalance, "balance");
        bindFxBar(eqVirt, "virt");
        bindFxBar(eqLoud, "loud");
        buildNamedPresets();
        buildVizModes();
        loadFxSliders();
        labelSort();
        showTab(0);
        requestPerms();
        scanUsb(true);
        handleViewIntent(getIntent());
    }

    private void applyCenterPadding() {
        DisplayMetrics dm = getResources().getDisplayMetrics();
        int padX = Math.max(8, (int) (dm.widthPixels * 0.20f));
        int padY = Math.max(8, (int) (dm.heightPixels * 0.30f));
        stage.setPadding(padX, padY, padX, padY);
    }

    private void requestPerms() {
        List<String> missing = new ArrayList<>();
        for (int i = 0; i < PERMS.length; i++) {
            if (checkSelfPermission(PERMS[i]) != PackageManager.PERMISSION_GRANTED) {
                missing.add(PERMS[i]);
            }
        }
        if (!missing.isEmpty()) {
            requestPermissions(missing.toArray(new String[0]), 7);
        }
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        handleViewIntent(intent);
    }

    @Override
    protected void onResume() {
        super.onResume();
        registerReceiver(status, new IntentFilter(PlayerService.ACTION_STATUS));
        refreshNow();
        if (tab == 3) {
            attachViz();
            glFog.onResume();
        }
    }

    @Override
    protected void onPause() {
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
        if (keyCode == KeyEvent.KEYCODE_MEDIA_FAST_FORWARD) {
            Intent intent = new Intent(this, PlayerService.class);
            intent.setAction(PlayerService.ACTION_SEEK);
            intent.putExtra(PlayerService.EXTRA_MS, PlayerService.position() + 15000);
            PlayerService.send(this, intent);
            return true;
        }
        if (keyCode == KeyEvent.KEYCODE_MEDIA_REWIND) {
            Intent intent = new Intent(this, PlayerService.class);
            intent.setAction(PlayerService.ACTION_SEEK);
            intent.putExtra(PlayerService.EXTRA_MS, Math.max(0, PlayerService.position() - 15000));
            PlayerService.send(this, intent);
            return true;
        }
        return super.onKeyDown(keyCode, event);
    }

    private void handleViewIntent(Intent intent) {
        if (intent == null || intent.getData() == null) {
            return;
        }
        String path = intent.getData().getPath();
        if (path == null) {
            return;
        }
        File file = new File(path);
        if (!file.exists()) {
            return;
        }
        UsbMedia.Entry e = new UsbMedia.Entry();
        e.file = file;
        e.audio = MediaTypes.isAudio(file.getName());
        e.video = MediaTypes.isVideo(file.getName());
        e.label = file.getName();
        open(e);
    }

    private void showTab(int next) {
        tab = next;
        paintTab(tabMusic, next == 0);
        paintTab(tabVideo, next == 1);
        paintTab(tabEq, next == 2);
        paintTab(tabViz, next == 3);
        pageMedia.setVisibility(next <= 1 ? View.VISIBLE : View.GONE);
        pageEq.setVisibility(next == 2 ? View.VISIBLE : View.GONE);
        pageViz.setVisibility(next == 3 ? View.VISIBLE : View.GONE);
        btnSort.setVisibility(next == 0 ? View.VISIBLE : View.GONE);
        if (next <= 1) {
            scanUsb(false);
        }
        if (next == 2) {
            buildEqBands();
        }
        if (next == 3) {
            attachViz();
            applyVizMode(EqPrefs.vizMode(this));
            glFog.onResume();
        } else {
            viz.release();
            attachedSession = -1;
            glFog.onPause();
        }
    }

    private void paintTab(TextView view, boolean on) {
        view.setBackgroundColor(on ? 0xFF3DDC97 : 0xFF223049);
        view.setTextColor(on ? 0xFF0B1220 : 0xFFF3F6FB);
    }

    private void labelSort() {
        int id = R.string.sort_folder;
        if (sortMode == 1) {
            id = R.string.sort_artist;
        } else if (sortMode == 2) {
            id = R.string.sort_album;
        } else if (sortMode == 3) {
            id = R.string.sort_title;
        }
        btnSort.setText(getString(id));
    }

    private void showRoots() {
        cwd = null;
        rows.clear();
        List<File> roots = UsbMedia.roots(this);
        for (int i = 0; i < roots.size(); i++) {
            File root = roots.get(i);
            UsbMedia.Entry e = new UsbMedia.Entry();
            e.file = root;
            e.directory = true;
            e.label = "Флешка · " + root.getName();
            e.meta = root.getAbsolutePath();
            rows.add(e);
        }
        pathView.setText(getString(R.string.usb));
        apply();
    }

    private void openDir(File dir) {
        cwd = dir;
        rows.clear();
        rows.addAll(UsbMedia.list(dir));
        UsbMedia.sortEntries(rows, sortMode);
        pathView.setText(dir.getAbsolutePath());
        apply();
    }

    private void goUp() {
        if (tab == 1 || sortMode != 0) {
            showRoots();
            return;
        }
        if (cwd == null) {
            showRoots();
            return;
        }
        File parent = cwd.getParentFile();
        List<File> roots = UsbMedia.roots(this);
        for (int i = 0; i < roots.size(); i++) {
            if (cwd.equals(roots.get(i))) {
                showRoots();
                return;
            }
        }
        if (parent == null) {
            showRoots();
        } else {
            openDir(parent);
        }
    }

    private void scanUsb(boolean force) {
        if (scanning) {
            return;
        }
        if (tab > 1) {
            return;
        }
        if (!force && sortMode == 0 && tab == 0) {
            if (cwd == null) {
                showRoots();
            } else {
                openDir(cwd);
            }
            return;
        }
        scanning = true;
        pathView.setText("сканирование флешки…");
        final boolean video = tab == 1;
        final int mode = sortMode;
        new Thread(new Runnable() {
            @Override
            public void run() {
                final List<UsbMedia.Entry> found = UsbMedia.scanAll(BrowserActivity.this, video);
                UsbMedia.sortEntries(found, video ? 3 : mode);
                runOnUiThread(new Runnable() {
                    @Override
                    public void run() {
                        scanning = false;
                        cwd = null;
                        rows.clear();
                        rows.addAll(found);
                        pathView.setText((video ? "видео · " : "музыка · ") + found.size() + " файлов");
                        apply();
                    }
                });
            }
        }).start();
    }

    private void open(UsbMedia.Entry entry) {
        if (entry.directory) {
            openDir(entry.file);
            return;
        }
        if (entry.video) {
            ArrayList<String> paths = queue(true);
            int start = Math.max(0, paths.indexOf(entry.file.getAbsolutePath()));
            if (paths.isEmpty()) {
                paths.add(entry.file.getAbsolutePath());
                start = 0;
            }
            VideoActivity.start(this, paths, start);
            return;
        }
        ArrayList<String> paths = queue(false);
        int start = Math.max(0, paths.indexOf(entry.file.getAbsolutePath()));
        if (paths.isEmpty()) {
            paths.add(entry.file.getAbsolutePath());
            start = 0;
        }
        PlayerService.play(this, paths, start);
        refreshNow();
    }

    private ArrayList<String> queue(boolean video) {
        ArrayList<String> paths = new ArrayList<>();
        for (int i = 0; i < rows.size(); i++) {
            UsbMedia.Entry e = rows.get(i);
            if (e.directory || e.file == null) {
                continue;
            }
            if (video && e.video) {
                paths.add(e.file.getAbsolutePath());
            } else if (!video && e.audio) {
                paths.add(e.file.getAbsolutePath());
            }
        }
        return paths;
    }

    private void apply() {
        boolean none = rows.isEmpty();
        empty.setVisibility(none ? View.VISIBLE : View.GONE);
        list.setVisibility(none ? View.GONE : View.VISIBLE);
        adapter.notifyDataSetChanged();
    }

    private void refreshNow() {
        String name = PlayerService.title();
        if (name.length() == 0) {
            name = "флешка ГУ · выберите трек";
        }
        String err = PlayerService.error();
        nowTitle.setText(err.length() > 0 ? err : name);
        btnPlay.setText(PlayerService.isPlaying() ? "❚❚" : "▶");
        btnShuffle.setTextColor(PlayerService.shuffle() ? 0xFF0B1220 : 0xFFF3F6FB);
        btnShuffle.setBackgroundColor(PlayerService.shuffle() ? 0xFF3DDC97 : 0xFF223049);
        int rep = PlayerService.repeat();
        btnRepeat.setText(rep == 2 ? "①" : (rep == 1 ? "∞" : "—"));
        attachViz();
        if (tab == 2) {
            eqCurve.capture(PlayerService.equalizer());
        }
    }

    private void attachViz() {
        int session = PlayerService.sessionId();
        if (session > 0 && session != attachedSession) {
            viz.attach(session);
            attachedSession = session;
            if (tab == 2) {
                buildEqBands();
            }
        }
    }

    private void bindFxBar(SeekBar bar, final String kind) {
        bar.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener() {
            @Override
            public void onProgressChanged(SeekBar seekBar, int progress, boolean fromUser) {
                if (!fromUser) {
                    return;
                }
                Intent intent = new Intent(BrowserActivity.this, PlayerService.class);
                intent.setAction(PlayerService.ACTION_FX);
                intent.putExtra(PlayerService.EXTRA_KIND, kind);
                intent.putExtra(PlayerService.EXTRA_VALUE, progress);
                PlayerService.send(BrowserActivity.this, intent);
            }

            @Override
            public void onStartTrackingTouch(SeekBar seekBar) {
            }

            @Override
            public void onStopTrackingTouch(SeekBar seekBar) {
                if (tab == 2) {
                    eqCurve.capture(PlayerService.equalizer());
                    buildEqBands();
                }
            }
        });
    }

    private void loadFxSliders() {
        eqBass.setProgress(EqPrefs.bass(this));
        eqMids.setProgress(EqPrefs.mids(this));
        eqHighs.setProgress(EqPrefs.highs(this));
        eqVolume.setProgress(EqPrefs.volume(this));
        eqBalance.setProgress(EqPrefs.balance(this));
        eqVirt.setProgress(EqPrefs.virt(this));
        eqLoud.setProgress(EqPrefs.loud(this));
    }

    private void buildNamedPresets() {
        namedPresets.removeAllViews();
        int current = EqPrefs.namedPreset(this);
        for (int i = 0; i < EqPrefs.PRESET_NAMES.length; i++) {
            final int named = i;
            Button b = new Button(this);
            b.setText(EqPrefs.PRESET_NAMES[i]);
            boolean on = i == current;
            b.setTextColor(on ? 0xFF0B1220 : 0xFFF3F6FB);
            b.setBackgroundColor(on ? 0xFF3DDC97 : 0xFF223049);
            b.setOnClickListener(new View.OnClickListener() {
                @Override
                public void onClick(View v) {
                    Intent intent = new Intent(BrowserActivity.this, PlayerService.class);
                    intent.setAction(PlayerService.ACTION_EQ_NAMED);
                    intent.putExtra(PlayerService.EXTRA_NAMED, named);
                    PlayerService.send(BrowserActivity.this, intent);
                    v.postDelayed(new Runnable() {
                        @Override
                        public void run() {
                            buildNamedPresets();
                            buildEqBands();
                            eqCurve.capture(PlayerService.equalizer());
                        }
                    }, 120);
                }
            });
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.WRAP_CONTENT, 56);
            lp.setMargins(0, 0, 8, 0);
            namedPresets.addView(b, lp);
        }
    }

    private void buildEqBands() {
        eqBands.removeAllViews();
        Equalizer eq = PlayerService.equalizer();
        eqCurve.capture(eq);
        if (eq == null) {
            TextView hint = new TextView(this);
            hint.setText("Полосы появятся после старта трека (audioSession ГУ)");
            hint.setTextColor(0xFF9AA7B8);
            hint.setTextSize(14);
            eqBands.addView(hint);
            return;
        }
        try {
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
                        Intent intent = new Intent(BrowserActivity.this, PlayerService.class);
                        intent.setAction(PlayerService.ACTION_EQ_BAND);
                        intent.putExtra(PlayerService.EXTRA_BAND, (int) band);
                        intent.putExtra(PlayerService.EXTRA_LEVEL, progress + range[0]);
                        PlayerService.send(BrowserActivity.this, intent);
                    }

                    @Override
                    public void onStartTrackingTouch(SeekBar seekBar) {
                    }

                    @Override
                    public void onStopTrackingTouch(SeekBar seekBar) {
                        eqCurve.capture(PlayerService.equalizer());
                        buildNamedPresets();
                    }
                });
                eqBands.addView(label);
                eqBands.addView(bar);
            }
        } catch (Exception e) {
            TextView hint = new TextView(this);
            hint.setText("эквалайзер недоступен на этом тракте ГУ");
            hint.setTextColor(0xFF9AA7B8);
            eqBands.addView(hint);
        }
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
                    EqPrefs.putInt(BrowserActivity.this, "viz_mode", mode);
                    applyVizMode(mode);
                    buildVizModes();
                }
            });
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.WRAP_CONTENT, 48);
            lp.setMargins(0, 0, 6, 0);
            vizModes.addView(b, lp);
        }
        Button full = new Button(this);
        full.setText("На весь экран");
        full.setTextColor(0xFF0B1220);
        full.setBackgroundColor(0xFF3DDC97);
        full.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                startActivity(new Intent(BrowserActivity.this, NowPlayingActivity.class));
            }
        });
        vizModes.addView(full, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.WRAP_CONTENT, 48));
        applyVizMode(current);
    }

    private void applyVizMode(int mode) {
        viz.setMode(mode);
        boolean fog = mode == VisualizerView.MODE_FOG;
        glFog.setVisibility(fog ? View.VISIBLE : View.GONE);
        viz.setVisibility(fog ? View.INVISIBLE : View.VISIBLE);
        if (fog) {
            glFog.onResume();
        } else {
            glFog.onPause();
        }
    }

    private class Adapter extends BaseAdapter {
        @Override
        public int getCount() {
            return rows.size();
        }

        @Override
        public Object getItem(int position) {
            return rows.get(position);
        }

        @Override
        public long getItemId(int position) {
            return position;
        }

        @Override
        public View getView(int position, View convertView, ViewGroup parent) {
            if (convertView == null) {
                convertView = getLayoutInflater().inflate(R.layout.row_media, parent, false);
            }
            UsbMedia.Entry e = rows.get(position);
            TextView kind = convertView.findViewById(R.id.kind);
            TextView name = convertView.findViewById(R.id.name);
            TextView meta = convertView.findViewById(R.id.meta);
            if (e.directory) {
                kind.setText("📁");
            } else if (e.video) {
                kind.setText("▶");
            } else {
                kind.setText("♪");
            }
            name.setText(e.label);
            meta.setText(e.meta);
            return convertView;
        }
    }
}
