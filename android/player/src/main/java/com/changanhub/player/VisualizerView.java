package com.changanhub.player;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.media.audiofx.Visualizer;
import android.util.AttributeSet;
import android.view.View;

/** FFT bars bound to the playing MediaPlayer audio session. */
public class VisualizerView extends View {
    private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private Visualizer visualizer;
    private byte[] fft = new byte[0];
    private final float[] bars = new float[24];

    public VisualizerView(Context context) {
        super(context);
        init();
    }

    public VisualizerView(Context context, AttributeSet attrs) {
        super(context, attrs);
        init();
    }

    private void init() {
        paint.setColor(0xFF3DDC97);
        setBackgroundColor(0xFF121A2B);
    }

    public void attach(int sessionId) {
        release();
        try {
            visualizer = new Visualizer(sessionId);
            visualizer.setCaptureSize(Visualizer.getCaptureSizeRange()[1]);
            visualizer.setDataCaptureListener(new Visualizer.OnDataCaptureListener() {
                @Override
                public void onWaveFormDataCapture(Visualizer v, byte[] waveform, int samplingRate) {
                }

                @Override
                public void onFftDataCapture(Visualizer v, byte[] fftData, int samplingRate) {
                    fft = fftData;
                    postInvalidate();
                }
            }, Visualizer.getMaxCaptureRate() / 2, false, true);
            visualizer.setEnabled(true);
        } catch (Exception ignored) {
            visualizer = null;
        }
    }

    public void release() {
        if (visualizer != null) {
            try {
                visualizer.setEnabled(false);
                visualizer.release();
            } catch (Exception ignored) {
            }
            visualizer = null;
        }
    }

    @Override
    protected void onDetachedFromWindow() {
        release();
        super.onDetachedFromWindow();
    }

    @Override
    protected void onDraw(Canvas canvas) {
        super.onDraw(canvas);
        int w = getWidth();
        int h = getHeight();
        if (w <= 0 || h <= 0) {
            return;
        }
        int n = bars.length;
        if (fft != null && fft.length > 2) {
            int usable = Math.min(fft.length / 2, n);
            for (int i = 0; i < n; i++) {
                float mag = 0f;
                if (i < usable) {
                    int idx = i * 2;
                    float re = fft[idx];
                    float im = idx + 1 < fft.length ? fft[idx + 1] : 0;
                    mag = (float) Math.sqrt(re * re + im * im) / 90f;
                }
                bars[i] = bars[i] * 0.6f + Math.min(1f, mag) * 0.4f;
            }
        }
        float gap = 6f;
        float barW = (w - gap * (n + 1)) / n;
        for (int i = 0; i < n; i++) {
            float bh = Math.max(8f, bars[i] * (h - 16));
            float x = gap + i * (barW + gap);
            paint.setAlpha(180 + (int) (75 * bars[i]));
            canvas.drawRoundRect(x, h - bh - 8, x + barW, h - 8, 8, 8, paint);
        }
    }
}
