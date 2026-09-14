/* Copyright (C) 2013 Olga Yakovleva <yakovleva.o.v@gmail.com> */
/* GNU Lesser General Public License 2.1 or later. */

package com.github.olga_yakovleva.rhvoice;

public final class VoiceInfo {
    private String name = null;
    private String id;
    private LanguageInfo language = null;

    void setName(String name) {
        this.name = name;
    }

    public String getName() {
        return name;
    }

    void setId(String id) {
        this.id = id;
    }

    public String getId() {
        return id;
    }

    void setLanguage(LanguageInfo lang) {
        language = lang;
    }

    public LanguageInfo getLanguage() {
        return language;
    }
}
