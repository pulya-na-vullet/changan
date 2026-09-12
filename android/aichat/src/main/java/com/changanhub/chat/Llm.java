package com.changanhub.chat;

import android.content.Context;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.util.List;

/** DeepSeek (OpenAI-compatible) and YandexGPT over HttpURLConnection. */
public final class Llm {
    public interface Listener {
        void onDelta(String token);

        void onDone(String full);

        void onError(String message);
    }

    public static final class Cancel {
        public volatile boolean stop;
    }

    private Llm() {
    }

    public static void complete(Context context, List<Msg> history, Listener listener, Cancel cancel) {
        String provider = Prefs.provider(context);
        try {
            if (Prefs.PROVIDER_YANDEX.equals(provider)) {
                yandex(context, history, listener, cancel);
            } else {
                deepseek(context, history, listener, cancel);
            }
        } catch (Exception e) {
            listener.onError(Net.explain(e, 0, ""));
        }
    }

    public static void ping(Context context, Listener listener) {
        Cancel cancel = new Cancel();
        List<Msg> one = new java.util.ArrayList<>();
        one.add(Msg.of("user", "Ответь одним словом: ок"));
        complete(context, one, listener, cancel);
    }

    private static void deepseek(Context context, List<Msg> history, Listener listener, Cancel cancel)
            throws Exception {
        String key = Prefs.deepseekKey(context).trim();
        if (key.length() == 0) {
            listener.onError("Нет ключа DeepSeek. Откройте Настройки.");
            return;
        }
        String base = Prefs.deepseekUrl(context).trim();
        if (base.endsWith("/")) {
            base = base.substring(0, base.length() - 1);
        }
        JSONObject body = new JSONObject();
        body.put("model", Prefs.deepseekModel(context));
        body.put("stream", true);
        body.put("temperature", Prefs.temperature(context));
        body.put("max_tokens", Prefs.maxTokens(context));
        JSONArray messages = new JSONArray();
        String system = Prefs.systemPrompt(context).trim();
        if (system.length() > 0) {
            JSONObject sys = new JSONObject();
            sys.put("role", "system");
            sys.put("content", system);
            messages.put(sys);
        }
        int start = Math.max(0, history.size() - Prefs.historyLimit(context));
        for (int i = start; i < history.size(); i++) {
            Msg m = history.get(i);
            if (m.error) {
                continue;
            }
            JSONObject row = new JSONObject();
            row.put("role", "assistant".equals(m.role) ? "assistant" : "user");
            row.put("content", m.text);
            messages.put(row);
        }
        body.put("messages", messages);
        HttpURLConnection conn = Net.open(context, base + "/chat/completions", "POST");
        conn.setRequestProperty("Authorization", "Bearer " + key);
        Net.write(conn, body.toString());
        int code = conn.getResponseCode();
        InputStream stream = code >= 400 ? conn.getErrorStream() : conn.getInputStream();
        if (code >= 400) {
            String err = readAll(stream);
            listener.onError(Net.explain(null, code, err));
            conn.disconnect();
            return;
        }
        BufferedReader reader = new BufferedReader(new InputStreamReader(stream, "UTF-8"));
        StringBuilder full = new StringBuilder();
        String line;
        while ((line = reader.readLine()) != null) {
            if (cancel != null && cancel.stop) {
                break;
            }
            if (!line.startsWith("data:")) {
                continue;
            }
            String payload = line.substring(5).trim();
            if ("[DONE]".equals(payload)) {
                break;
            }
            try {
                JSONObject chunk = new JSONObject(payload);
                JSONArray choices = chunk.optJSONArray("choices");
                if (choices == null || choices.length() == 0) {
                    continue;
                }
                JSONObject delta = choices.getJSONObject(0).optJSONObject("delta");
                if (delta == null) {
                    continue;
                }
                String token = delta.optString("content", "");
                if (token.length() > 0) {
                    full.append(token);
                    listener.onDelta(token);
                }
            } catch (Exception ignored) {
            }
        }
        reader.close();
        conn.disconnect();
        if (full.length() == 0 && (cancel == null || !cancel.stop)) {
            listener.onError("Пустой ответ DeepSeek. Проверьте модель и ключ.");
            return;
        }
        listener.onDone(full.toString());
    }

    private static void yandex(Context context, List<Msg> history, Listener listener, Cancel cancel)
            throws Exception {
        String key = Prefs.yandexKey(context).trim();
        String folder = Prefs.yandexFolder(context).trim();
        if (key.length() == 0 || folder.length() == 0) {
            listener.onError("Нужны Folder ID и ключ Yandex Cloud во вкладке Настройки.");
            return;
        }
        String url = Prefs.yandexUrl(context).trim();
        String model = Prefs.yandexModel(context);
        JSONObject body = new JSONObject();
        body.put("modelUri", "gpt://" + folder + "/" + model);
        JSONObject opts = new JSONObject();
        opts.put("stream", true);
        opts.put("temperature", Prefs.temperature(context));
        opts.put("maxTokens", String.valueOf(Prefs.maxTokens(context)));
        body.put("completionOptions", opts);
        JSONArray messages = new JSONArray();
        String system = Prefs.systemPrompt(context).trim();
        if (system.length() > 0) {
            JSONObject sys = new JSONObject();
            sys.put("role", "system");
            sys.put("text", system);
            messages.put(sys);
        }
        int start = Math.max(0, history.size() - Prefs.historyLimit(context));
        for (int i = start; i < history.size(); i++) {
            Msg m = history.get(i);
            if (m.error) {
                continue;
            }
            JSONObject row = new JSONObject();
            row.put("role", "assistant".equals(m.role) ? "assistant" : "user");
            row.put("text", m.text);
            messages.put(row);
        }
        body.put("messages", messages);
        HttpURLConnection conn = Net.open(context, url, "POST");
        if (key.startsWith("t1.") || key.length() > 80) {
            conn.setRequestProperty("Authorization", "Bearer " + key);
        } else {
            conn.setRequestProperty("Authorization", "Api-Key " + key);
        }
        conn.setRequestProperty("x-folder-id", folder);
        Net.write(conn, body.toString());
        int code = conn.getResponseCode();
        InputStream stream = code >= 400 ? conn.getErrorStream() : conn.getInputStream();
        if (code >= 400) {
            String err = readAll(stream);
            listener.onError(Net.explain(null, code, err));
            conn.disconnect();
            return;
        }
        BufferedReader reader = new BufferedReader(new InputStreamReader(stream, "UTF-8"));
        StringBuilder full = new StringBuilder();
        String line;
        while ((line = reader.readLine()) != null) {
            if (cancel != null && cancel.stop) {
                break;
            }
            line = line.trim();
            if (line.length() == 0 || line.startsWith("data: [DONE]")) {
                continue;
            }
            if (line.startsWith("data:")) {
                line = line.substring(5).trim();
            }
            try {
                JSONObject chunk = new JSONObject(line);
                JSONObject result = chunk.optJSONObject("result");
                if (result == null) {
                    result = chunk;
                }
                JSONArray alts = result.optJSONArray("alternatives");
                if (alts == null || alts.length() == 0) {
                    continue;
                }
                JSONObject message = alts.getJSONObject(0).optJSONObject("message");
                if (message == null) {
                    continue;
                }
                String text = message.optString("text", "");
                if (text.length() > full.length()) {
                    String delta = text.substring(full.length());
                    full.setLength(0);
                    full.append(text);
                    listener.onDelta(delta);
                } else if (text.length() > 0 && full.length() == 0) {
                    full.append(text);
                    listener.onDelta(text);
                }
            } catch (Exception ignored) {
            }
        }
        reader.close();
        conn.disconnect();
        if (full.length() == 0 && (cancel == null || !cancel.stop)) {
            listener.onError("Пустой ответ YandexGPT. Проверьте Folder ID, модель и ключ.");
            return;
        }
        listener.onDone(full.toString());
    }

    private static String readAll(InputStream stream) {
        if (stream == null) {
            return "";
        }
        try {
            BufferedReader reader = new BufferedReader(new InputStreamReader(stream, "UTF-8"));
            StringBuilder b = new StringBuilder();
            String line;
            while ((line = reader.readLine()) != null) {
                b.append(line);
            }
            reader.close();
            return b.toString();
        } catch (Exception e) {
            return "";
        }
    }
}
