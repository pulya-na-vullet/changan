package com.changanhub.player;

/** Latest FFT energy for OpenGL fog and beat flashes. */
public final class AudioEnergy {
    public static volatile float bass;
    public static volatile float mids;
    public static volatile float highs;
    public static volatile float beat;
    public static volatile float[] spectrum = new float[32];
    public static volatile byte[] wave = new byte[0];

    private AudioEnergy() {
    }
}
