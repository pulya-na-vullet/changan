package com.changanhub.player;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.Path;
import android.media.audiofx.Visualizer;
import android.util.AttributeSet;
import android.view.View;

import java.util.Random;

/** FFT / waveform visuals bound to the playing MediaPlayer audio session. */
public class VisualizerView extends View {
    public static final int MODE_BARS = 0;
    public static final int MODE_WAVE = 1;
    public static final int MODE_PARTICLES = 2;
    public static final int MODE_RADIAL = 3;
    public static final int MODE_FOG = 4;

    private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint dim = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Path path = new Path();
    private final Random random = new Random();
    private final Particle[] particles = new Particle[80];
    private final float[] bars = new float[32];
    private Visualizer visualizer;
    private byte[] fft = new byte[0];
    private byte[] wave = new byte[0];
    private int mode = MODE_BARS;
    private float pulse;
    private long lastBeat;

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
        paint.setStrokeWidth(3f);
        paint.setStyle(Paint.Style.FILL);
        dim.setColor(0xFF121A2B);
        setBackgroundColor(0xFF0B1220);
        for (int i = 0; i < particles.length; i++) {
            particles[i] = new Particle();
        }
    }

    public void setMode(int next) {
        mode = next;
        invalidate();
    }

    public int mode() {
        return mode;
    }

    public void attach(int sessionId) {
        release();
        if (sessionId <= 0) {
            return;
        }
        try {
            visualizer = new Visualizer(sessionId);
            visualizer.setCaptureSize(Visualizer.getCaptureSizeRange()[1]);
            visualizer.setDataCaptureListener(new Visualizer.OnDataCaptureListener() {
                @Override
                public void onWaveFormDataCapture(Visualizer v, byte[] waveform, int samplingRate) {
                    wave = waveform;
                    AudioEnergy.wave = waveform;
                    postInvalidate();
                }

                @Override
                public void onFftDataCapture(Visualizer v, byte[] fftData, int samplingRate) {
                    fft = fftData;
                    consumeFft(fftData);
                    postInvalidate();
                }
            }, Visualizer.getMaxCaptureRate() / 2, true, true);
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

    private void consumeFft(byte[] data) {
        if (data == null || data.length < 4) {
            return;
        }
        int n = bars.length;
        float bass = 0f;
        float mids = 0f;
        float highs = 0f;
        int usable = Math.min(data.length / 2, n);
        for (int i = 0; i < n; i++) {
            float mag = 0f;
            if (i < usable) {
                int idx = i * 2;
                float re = data[idx];
                float im = idx + 1 < data.length ? data[idx + 1] : 0;
                mag = (float) Math.sqrt(re * re + im * im) / 90f;
            }
            mag = Math.min(1f, mag);
            bars[i] = bars[i] * 0.55f + mag * 0.45f;
            if (i < 4) {
                bass += bars[i];
            } else if (i < 16) {
                mids += bars[i];
            } else {
                highs += bars[i];
            }
        }
        bass /= 4f;
        mids /= 12f;
        highs /= Math.max(1, n - 16);
        AudioEnergy.bass = bass;
        AudioEnergy.mids = mids;
        AudioEnergy.highs = highs;
        float[] copy = new float[n];
        System.arraycopy(bars, 0, copy, 0, n);
        AudioEnergy.spectrum = copy;
        long now = android.os.SystemClock.uptimeMillis();
        if (bass > 0.52f && bass > AudioEnergy.beat + 0.08f && now - lastBeat > 180) {
            lastBeat = now;
            pulse = 1f;
            spawnBurst(bass);
        }
        pulse *= 0.86f;
        AudioEnergy.beat = pulse;
    }

    private void spawnBurst(float energy) {
        int born = 6 + (int) (energy * 10);
        int w = Math.max(1, getWidth());
        int h = Math.max(1, getHeight());
        for (int i = 0; i < particles.length && born > 0; i++) {
            if (particles[i].life <= 0f) {
                particles[i].x = w / 2f + (random.nextFloat() - 0.5f) * 80f;
                particles[i].y = h * 0.72f;
                particles[i].vx = (random.nextFloat() - 0.5f) * 18f * energy;
                particles[i].vy = -8f - random.nextFloat() * 16f * energy;
                particles[i].life = 1f;
                particles[i].size = 4f + random.nextFloat() * 10f;
                born--;
            }
        }
    }

    @Override
    protected void onDraw(Canvas canvas) {
        super.onDraw(canvas);
        int w = getWidth();
        int h = getHeight();
        if (w <= 0 || h <= 0) {
            return;
        }
        if (mode == MODE_FOG) {
            canvas.drawColor(0x00000000);
            return;
        }
        if (mode == MODE_WAVE) {
            drawWave(canvas, w, h);
        } else if (mode == MODE_PARTICLES) {
            drawParticles(canvas, w, h);
        } else if (mode == MODE_RADIAL) {
            drawRadial(canvas, w, h);
        } else {
            drawBars(canvas, w, h);
        }
        if (pulse > 0.05f) {
            paint.setStyle(Paint.Style.FILL);
            paint.setColor(0x33FFFFFF);
            paint.setAlpha((int) (70 * pulse));
            canvas.drawCircle(w / 2f, h / 2f, Math.min(w, h) * 0.18f * (0.6f + pulse), paint);
            paint.setColor(0xFF3DDC97);
        }
    }

    private void drawBars(Canvas canvas, int w, int h) {
        paint.setStyle(Paint.Style.FILL);
        paint.setColor(0xFF3DDC97);
        int n = bars.length;
        float gap = 4f;
        float barW = (w - gap * (n + 1)) / n;
        for (int i = 0; i < n; i++) {
            float bh = Math.max(8f, bars[i] * (h - 16));
            float x = gap + i * (barW + gap);
            paint.setAlpha(160 + (int) (95 * bars[i]));
            canvas.drawRoundRect(x, h - bh - 8, x + barW, h - 8, 6, 6, paint);
        }
    }

    private void drawWave(Canvas canvas, int w, int h) {
        byte[] data = wave;
        paint.setStyle(Paint.Style.STROKE);
        paint.setStrokeWidth(3f);
        paint.setColor(0xFF3DDC97);
        paint.setAlpha(220);
        path.reset();
        if (data == null || data.length < 4) {
            path.moveTo(0, h / 2f);
            path.lineTo(w, h / 2f);
        } else {
            for (int i = 0; i < data.length; i++) {
                float x = i * (w / (float) (data.length - 1));
                float y = h / 2f + ((data[i] + 128) - 128) / 128f * (h * 0.42f);
                if (i == 0) {
                    path.moveTo(x, y);
                } else {
                    path.lineTo(x, y);
                }
            }
        }
        canvas.drawPath(path, paint);
    }

    private void drawParticles(Canvas canvas, int w, int h) {
        paint.setStyle(Paint.Style.FILL);
        canvas.drawRect(0, 0, w, h, dim);
        for (int i = 0; i < particles.length; i++) {
            Particle p = particles[i];
            if (p.life <= 0f) {
                continue;
            }
            p.x += p.vx;
            p.y += p.vy;
            p.vy += 0.35f;
            p.life -= 0.018f;
            paint.setColor(0xFF3DDC97);
            paint.setAlpha(Math.max(0, (int) (255 * p.life)));
            canvas.drawCircle(p.x, p.y, p.size * p.life, paint);
        }
        drawBars(canvas, w, h / 3);
    }

    private void drawRadial(Canvas canvas, int w, int h) {
        float cx = w / 2f;
        float cy = h / 2f;
        float radius = Math.min(w, h) * 0.38f;
        paint.setStyle(Paint.Style.STROKE);
        paint.setStrokeWidth(6f);
        int n = bars.length;
        for (int i = 0; i < n; i++) {
            double a = (Math.PI * 2 * i) / n - Math.PI / 2;
            float inner = radius * 0.35f;
            float outer = inner + bars[i] * radius;
            paint.setColor(0xFF3DDC97);
            paint.setAlpha(150 + (int) (100 * bars[i]));
            canvas.drawLine(
                    cx + (float) Math.cos(a) * inner,
                    cy + (float) Math.sin(a) * inner,
                    cx + (float) Math.cos(a) * outer,
                    cy + (float) Math.sin(a) * outer,
                    paint);
        }
        paint.setStyle(Paint.Style.FILL);
        paint.setAlpha(80);
        canvas.drawCircle(cx, cy, radius * 0.22f * (0.7f + AudioEnergy.bass), paint);
    }

    private static class Particle {
        float x;
        float y;
        float vx;
        float vy;
        float life;
        float size;
    }
}
