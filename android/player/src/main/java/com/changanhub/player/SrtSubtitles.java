package com.changanhub.player;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileInputStream;
import java.io.InputStreamReader;
import java.util.ArrayList;
import java.util.List;

/** Sidecar SRT next to a video file. ASS is treated as plain timed lines if present. */
public final class SrtSubtitles {
    public static class Cue {
        public int startMs;
        public int endMs;
        public String text = "";
    }

    private final List<Cue> cues = new ArrayList<>();

    public static File sidecar(File video) {
        if (video == null) {
            return null;
        }
        String path = video.getAbsolutePath();
        int dot = path.lastIndexOf('.');
        String stem = dot > 0 ? path.substring(0, dot) : path;
        File srt = new File(stem + ".srt");
        if (srt.isFile()) {
            return srt;
        }
        File ass = new File(stem + ".ass");
        if (ass.isFile()) {
            return ass;
        }
        return null;
    }

    public static SrtSubtitles load(File file) {
        SrtSubtitles out = new SrtSubtitles();
        if (file == null || !file.isFile()) {
            return out;
        }
        BufferedReader reader = null;
        try {
            reader = new BufferedReader(new InputStreamReader(new FileInputStream(file), "UTF-8"));
            String line;
            Cue cue = null;
            StringBuilder body = new StringBuilder();
            while ((line = reader.readLine()) != null) {
                line = line.trim();
                if (line.length() == 0) {
                    if (cue != null) {
                        cue.text = body.toString().trim();
                        if (cue.text.length() > 0) {
                            out.cues.add(cue);
                        }
                    }
                    cue = null;
                    body.setLength(0);
                    continue;
                }
                if (line.contains("-->")) {
                    cue = new Cue();
                    parseTimes(line, cue);
                    continue;
                }
                if (cue != null && !line.matches("\\d+")) {
                    if (body.length() > 0) {
                        body.append('\n');
                    }
                    body.append(stripAss(line));
                }
            }
            if (cue != null) {
                cue.text = body.toString().trim();
                if (cue.text.length() > 0) {
                    out.cues.add(cue);
                }
            }
        } catch (Exception ignored) {
        } finally {
            if (reader != null) {
                try {
                    reader.close();
                } catch (Exception ignored) {
                }
            }
        }
        return out;
    }

    public String at(int ms) {
        for (int i = 0; i < cues.size(); i++) {
            Cue cue = cues.get(i);
            if (ms >= cue.startMs && ms <= cue.endMs) {
                return cue.text;
            }
        }
        return "";
    }

    public boolean isEmpty() {
        return cues.isEmpty();
    }

    private static String stripAss(String line) {
        return line.replaceAll("\\{[^}]*\\}", "").replace("\\N", "\n");
    }

    private static void parseTimes(String line, Cue cue) {
        String[] parts = line.split("-->");
        if (parts.length < 2) {
            return;
        }
        cue.startMs = parseClock(parts[0].trim());
        String end = parts[1].trim();
        int space = end.indexOf(' ');
        if (space > 0) {
            end = end.substring(0, space);
        }
        cue.endMs = parseClock(end);
    }

    private static int parseClock(String raw) {
        raw = raw.replace(',', '.');
        String[] hms = raw.split(":");
        try {
            if (hms.length < 3) {
                return 0;
            }
            int h = Integer.parseInt(hms[0].trim());
            int m = Integer.parseInt(hms[1].trim());
            float s = Float.parseFloat(hms[2].trim());
            return (int) ((h * 3600 + m * 60 + s) * 1000);
        } catch (Exception e) {
            return 0;
        }
    }
}
