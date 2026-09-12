package com.changanhub.chat;

/** One chat turn. */
public final class Msg {
    public String role = "user";
    public String text = "";
    public long ts = System.currentTimeMillis();
    public boolean error;

    public static Msg of(String role, String text) {
        Msg m = new Msg();
        m.role = role;
        m.text = text == null ? "" : text;
        m.ts = System.currentTimeMillis();
        return m;
    }
}
