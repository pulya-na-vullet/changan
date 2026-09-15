/* Copyright (C) 2013, 2014, 2016, 2017, 2021, 2022 Olga Yakovleva <olga@rhvoice.org> */
/* GNU Lesser General Public License 2.1 or later. */

package com.github.olga_yakovleva.rhvoice;

import android.text.TextUtils;

import java.util.Arrays;
import java.util.List;

public final class TTSEngine {
    private long data;

    private static boolean loaded;

    private static native void onClassInit();

    private native void onInit(String data_path, String config_path, String[] resource_paths, String pkgPath, Logger logger) throws RHVoiceException;

    private native void onShutdown();

    private native VoiceInfo[] doGetVoices();

    private native void doSpeak(String text, SynthesisParameters params, TTSClient client) throws RHVoiceException;

    private native boolean doConfigure(String key, String value);

    private native String doGetCachedPackageDir();

    private native String doGetPackageDirFromServer();

    public static synchronized void ensureLoaded(android.content.Context context) {
        if (loaded) {
            return;
        }
        try {
            System.loadLibrary("RHVoice_jni");
        } catch (UnsatisfiedLinkError e) {
            try {
                java.io.File so = com.changanhub.chat.NativeLib.extract(context, "RHVoice_jni");
                System.load(so.getAbsolutePath());
            } catch (Throwable t) {
                UnsatisfiedLinkError fail = new UnsatisfiedLinkError(
                        "RHVoice_jni: " + e.getMessage() + " / " + t.getMessage());
                fail.initCause(t);
                throw fail;
            }
        }
        onClassInit();
        loaded = true;
    }

    public TTSEngine(String data_path, String config_path, String[] resource_paths, String pkgPath, Logger logger) throws RHVoiceException {
        onInit(data_path, config_path, resource_paths, pkgPath, logger);
    }

    public TTSEngine(String data_path, String config_path, List resource_paths, String pkgPath, Logger logger) throws RHVoiceException {
        this(data_path, config_path, (String[]) resource_paths.toArray(new String[resource_paths.size()]), pkgPath, logger);
    }

    public TTSEngine() throws RHVoiceException {
        this("", "", new String[0], "", null);
    }

    public void shutdown() {
        onShutdown();
    }

    public List getVoices() {
        return Arrays.asList(doGetVoices());
    }

    public void speak(String text, SynthesisParameters params, TTSClient client) throws RHVoiceException {
        if (params.getVoiceProfile() == null) {
            throw new RHVoiceException("Voice not set");
        }
        doSpeak(text, params, client);
    }

    public boolean configure(String key, String value) {
        if (TextUtils.isEmpty(key)) {
            return false;
        }
        if (TextUtils.isEmpty(value)) {
            return false;
        }
        return doConfigure(key, value);
    }

    public String getCachedPackageDir() {
        return doGetCachedPackageDir();
    }

    public String getPackageDirFromServer() {
        return doGetPackageDirFromServer();
    }
}
