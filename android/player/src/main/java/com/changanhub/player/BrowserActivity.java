package com.changanhub.player;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;
import android.view.View;
import android.view.ViewGroup;
import android.widget.AdapterView;
import android.widget.BaseAdapter;
import android.widget.ListView;
import android.widget.TextView;

import java.io.File;
import java.util.ArrayList;
import java.util.List;

public class BrowserActivity extends Activity {
    private TextView pathView;
    private TextView empty;
    private ListView list;
    private File cwd;
    private final List<UsbMedia.Entry> rows = new ArrayList<>();
    private final Adapter adapter = new Adapter();

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_browser);
        pathView = findViewById(R.id.path);
        empty = findViewById(R.id.empty);
        list = findViewById(R.id.list);
        list.setAdapter(adapter);
        findViewById(R.id.btn_up).setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                goUp();
            }
        });
        findViewById(R.id.btn_scan).setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                scanDisk();
            }
        });
        findViewById(R.id.btn_now).setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                startActivity(new Intent(BrowserActivity.this, NowPlayingActivity.class));
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
        showRoots();
        handleViewIntent(getIntent());
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        handleViewIntent(intent);
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
        pathView.setText(dir.getAbsolutePath());
        apply();
    }

    private void goUp() {
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

    private void scanDisk() {
        File root = cwd;
        if (root == null) {
            java.util.List<File> roots = UsbMedia.roots(this);
            if (roots.isEmpty()) {
                return;
            }
            root = roots.get(0);
        }
        rows.clear();
        addScanned(UsbMedia.scan(root, false), false);
        addScanned(UsbMedia.scan(root, true), true);
        cwd = root;
        pathView.setText("все файлы · " + root.getAbsolutePath());
        apply();
    }

    private void addScanned(java.util.List<File> files, boolean video) {
        for (int i = 0; i < files.size(); i++) {
            File file = files.get(i);
            UsbMedia.Entry e = new UsbMedia.Entry();
            e.file = file;
            e.audio = !video;
            e.video = video;
            e.label = file.getName();
            e.meta = (video ? "видео · " : "аудио · ") + file.getParent();
            rows.add(e);
        }
    }

    private void open(UsbMedia.Entry entry) {
        if (entry.directory) {
            openDir(entry.file);
            return;
        }
        if (entry.video) {
            ArrayList<String> paths = queue(true);
            int start = Math.max(0, paths.indexOf(entry.file.getAbsolutePath()));
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
        startActivity(new Intent(this, NowPlayingActivity.class));
    }

    private ArrayList<String> queue(boolean video) {
        ArrayList<String> paths = new ArrayList<>();
        for (int i = 0; i < rows.size(); i++) {
            UsbMedia.Entry e = rows.get(i);
            if (e.directory) {
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
