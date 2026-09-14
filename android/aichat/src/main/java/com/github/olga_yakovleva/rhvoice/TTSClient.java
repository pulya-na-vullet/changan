/* Copyright (C) 2013, 2018 Olga Yakovleva <yakovleva.o.v@gmail.com> */
/* GNU Lesser General Public License 2.1 or later. */

package com.github.olga_yakovleva.rhvoice;

public interface TTSClient {
    boolean playSpeech(short[] samples);

    boolean setSampleRate(int sampleRate);

    boolean rangeStart(int start, int end);
}
