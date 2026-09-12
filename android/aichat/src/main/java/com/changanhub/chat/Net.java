package com.changanhub.chat;

import java.net.HttpURLConnection;
import java.net.InetSocketAddress;
import java.net.Proxy;
import java.net.URL;

import android.content.Context;

/** HttpURLConnection with optional HTTP/SOCKS proxy. No OkHttp. */
public final class Net {
    private Net() {
    }

    public static HttpURLConnection open(Context context, String url, String method) throws Exception {
        URL parsed = new URL(url);
        Proxy proxy = proxy(context);
        HttpURLConnection conn = proxy == null
                ? (HttpURLConnection) parsed.openConnection()
                : (HttpURLConnection) parsed.openConnection(proxy);
        int timeout = Math.max(5, Prefs.timeoutSec(context)) * 1000;
        conn.setConnectTimeout(timeout);
        conn.setReadTimeout(timeout);
        conn.setRequestMethod(method);
        conn.setDoInput(true);
        conn.setInstanceFollowRedirects(true);
        conn.setRequestProperty("Accept", "application/json, text/event-stream");
        conn.setRequestProperty("User-Agent", "LamoreAiChat/1.0");
        return conn;
    }

    public static void write(HttpURLConnection conn, String body) throws Exception {
        conn.setDoOutput(true);
        conn.setRequestProperty("Content-Type", "application/json; charset=utf-8");
        byte[] raw = body.getBytes("UTF-8");
        conn.setFixedLengthStreamingMode(raw.length);
        conn.getOutputStream().write(raw);
        conn.getOutputStream().flush();
    }

    public static String explain(Exception e, int code, String body) {
        if (e instanceof java.net.UnknownHostException || e instanceof java.net.ConnectException) {
            return "Нет сети. Проверьте интернет на ГУ (SIM или Wi‑Fi).";
        }
        if (e instanceof java.net.SocketTimeoutException) {
            return "Сервер не ответил вовремя. Увеличьте таймаут или проверьте прокси.";
        }
        if (code == 401 || code == 403) {
            return "Неверный ключ API или нет доступа. Проверьте ключ во вкладке Настройки.";
        }
        if (code == 429) {
            return "Лимит запросов. Подождите и попробуйте снова.";
        }
        if (code == 402) {
            return "На аккаунте нет средств / квоты.";
        }
        if (code >= 500) {
            return "Сервер ИИ временно недоступен (" + code + ").";
        }
        if (code > 0) {
            String snippet = body == null ? "" : body;
            if (snippet.length() > 160) {
                snippet = snippet.substring(0, 160);
            }
            return "Ошибка API " + code + (snippet.length() == 0 ? "" : ": " + snippet);
        }
        return "Сбой запроса: " + (e == null ? "неизвестно" : e.getMessage());
    }

    private static Proxy proxy(Context context) {
        String host = Prefs.proxyHost(context).trim();
        int port = Prefs.proxyPort(context);
        if (host.length() == 0 || port <= 0) {
            return null;
        }
        Proxy.Type type = "SOCKS".equalsIgnoreCase(Prefs.proxyType(context))
                ? Proxy.Type.SOCKS : Proxy.Type.HTTP;
        return new Proxy(type, new InetSocketAddress(host, port));
    }
}
