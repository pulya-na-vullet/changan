package com.changanhub.chat;

import android.content.Context;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.List;
import java.util.UUID;

/** Dialogues as JSON files in filesDir. */
public final class ChatStore {
    public static class Session {
        public String id = "";
        public String title = "";
        public long updated;
        public final List<Msg> messages = new ArrayList<>();
    }

    private ChatStore() {
    }

    public static File dir(Context context) {
        File folder = new File(context.getFilesDir(), "chats");
        folder.mkdirs();
        return folder;
    }

    public static Session load(Context context, String id) {
        Session s = new Session();
        if (id == null || id.length() == 0) {
            return s;
        }
        File file = new File(dir(context), id + ".json");
        if (!file.isFile()) {
            s.id = id;
            return s;
        }
        try {
            return parse(read(file));
        } catch (Exception e) {
            s.id = id;
            return s;
        }
    }

    public static Session create(Context context) {
        Session s = new Session();
        s.id = UUID.randomUUID().toString().replace("-", "").substring(0, 12);
        s.title = "Новый чат";
        s.updated = System.currentTimeMillis();
        save(context, s);
        Prefs.put(context, "chat_id", s.id);
        return s;
    }

    public static void save(Context context, Session session) {
        if (session == null || session.id.length() == 0) {
            return;
        }
        session.updated = System.currentTimeMillis();
        if ((session.title == null || session.title.length() == 0 || "Новый чат".equals(session.title))
                && !session.messages.isEmpty()) {
            String first = session.messages.get(0).text;
            session.title = first.length() > 40 ? first.substring(0, 40) : first;
        }
        try {
            JSONObject o = new JSONObject();
            o.put("id", session.id);
            o.put("title", session.title);
            o.put("updated", session.updated);
            JSONArray arr = new JSONArray();
            for (int i = 0; i < session.messages.size(); i++) {
                Msg m = session.messages.get(i);
                JSONObject row = new JSONObject();
                row.put("role", m.role);
                row.put("text", m.text);
                row.put("ts", m.ts);
                arr.put(row);
            }
            o.put("messages", arr);
            write(new File(dir(context), session.id + ".json"), o.toString());
        } catch (Exception ignored) {
        }
    }

    public static List<Session> list(Context context) {
        List<Session> out = new ArrayList<>();
        File[] files = dir(context).listFiles();
        if (files == null) {
            return out;
        }
        for (int i = 0; i < files.length; i++) {
            File file = files[i];
            if (!file.getName().endsWith(".json")) {
                continue;
            }
            try {
                out.add(parse(read(file)));
            } catch (Exception ignored) {
            }
        }
        Collections.sort(out, new Comparator<Session>() {
            @Override
            public int compare(Session a, Session b) {
                return Long.compare(b.updated, a.updated);
            }
        });
        return out;
    }

    public static void delete(Context context, String id) {
        if (id == null) {
            return;
        }
        new File(dir(context), id + ".json").delete();
    }

    public static File exportFile(Context context, Session session) {
        File out = new File(context.getFilesDir(), "export-chat.json");
        save(context, session);
        File src = new File(dir(context), session.id + ".json");
        try {
            write(out, read(src));
        } catch (Exception ignored) {
        }
        return out;
    }

    public static Session importJson(Context context, String json) throws Exception {
        Session s = parse(json);
        if (s.id.length() == 0) {
            s.id = UUID.randomUUID().toString().replace("-", "").substring(0, 12);
        }
        save(context, s);
        Prefs.put(context, "chat_id", s.id);
        return s;
    }

    public static Session parse(String json) throws Exception {
        JSONObject o = new JSONObject(json);
        Session s = new Session();
        s.id = o.optString("id", "");
        s.title = o.optString("title", "Чат");
        s.updated = o.optLong("updated", 0);
        JSONArray arr = o.optJSONArray("messages");
        if (arr != null) {
            for (int i = 0; i < arr.length(); i++) {
                JSONObject row = arr.getJSONObject(i);
                Msg m = new Msg();
                m.role = row.optString("role", "user");
                m.text = row.optString("text", "");
                m.ts = row.optLong("ts", 0);
                s.messages.add(m);
            }
        }
        return s;
    }

    public static String read(File file) throws Exception {
        FileInputStream in = new FileInputStream(file);
        try {
            byte[] buf = new byte[(int) file.length()];
            int n = in.read(buf);
            return new String(buf, 0, Math.max(0, n), StandardCharsets.UTF_8);
        } finally {
            in.close();
        }
    }

    private static void write(File file, String text) throws Exception {
        FileOutputStream out = new FileOutputStream(file);
        try {
            out.write(text.getBytes(StandardCharsets.UTF_8));
        } finally {
            out.close();
        }
    }
}
