/* Copyright (C) 2013 Olga Yakovleva <yakovleva.o.v@gmail.com> */
/* GNU Lesser General Public License 2.1 or later. */

package com.github.olga_yakovleva.rhvoice;

public final class SynthesisParameters {
    private String voiceProfile;
    private boolean ssml_mode = false;
    private double rate = 1;
    private double pitch = 1;
    private double volume = 1;

    public void setVoiceProfile(String profile) {
        voiceProfile = profile;
    }

    public String getVoiceProfile() {
        return voiceProfile;
    }

    public void setSSMLMode(boolean mode) {
        ssml_mode = mode;
    }

    public boolean getSSMLMode() {
        return ssml_mode;
    }

    public void setRate(double value) {
        rate = value;
    }

    public double getRate() {
        return rate;
    }

    public void setPitch(double value) {
        pitch = value;
    }

    public double getPitch() {
        return pitch;
    }

    public void setVolume(double value) {
        volume = value;
    }

    public double getVolume() {
        return volume;
    }
}
