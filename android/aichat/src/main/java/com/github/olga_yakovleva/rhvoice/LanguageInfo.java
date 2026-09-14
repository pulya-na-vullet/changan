/* Copyright (C) 2013, 2016, 2017 Olga Yakovleva <yakovleva.o.v@gmail.com> */
/* GNU Lesser General Public License 2.1 or later. */

package com.github.olga_yakovleva.rhvoice;

import android.text.TextUtils;

public final class LanguageInfo {
    private String name = null;
    private String alpha2_code = null;
    private String alpha3_code = null;
    private String alpha2_country_code = null;
    private String alpha3_country_code = null;
    private boolean pseudoEnglish = false;

    void setName(String name) {
        this.name = name;
    }

    public String getName() {
        return name;
    }

    void setAlpha2Code(String code) {
        alpha2_code = code;
    }

    public String getAlpha2Code() {
        return alpha2_code;
    }

    void setAlpha3Code(String code) {
        alpha3_code = code;
    }

    public String getAlpha3Code() {
        return alpha3_code;
    }

    void setAlpha2CountryCode(String code) {
        alpha2_country_code = code;
    }

    public String getAlpha2CountryCode() {
        if (TextUtils.isEmpty(alpha2_country_code)) {
            return "ZZ";
        }
        return alpha2_country_code;
    }

    void setAlpha3CountryCode(String code) {
        alpha3_country_code = code;
    }

    public String getAlpha3CountryCode() {
        if (TextUtils.isEmpty(alpha3_country_code)) {
            return "ZZZ";
        }
        return alpha3_country_code;
    }

    void setPseudoEnglish(boolean value) {
        pseudoEnglish = value;
    }

    public boolean getPseudoEnglish() {
        return pseudoEnglish;
    }

    public String getTag3() {
        if (TextUtils.isEmpty(alpha3_country_code)) {
            return alpha3_code;
        }
        return alpha3_code + "-" + alpha3_country_code.toUpperCase();
    }
}
