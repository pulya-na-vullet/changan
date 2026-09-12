package com.changanhub.player;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.Path;
import android.media.audiofx.Equalizer;
import android.util.AttributeSet;
import android.view.View;

/** Live EQ frequency-response sketch from hardware band levels. */
public class EqCurveView extends View {
    private final Paint line = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint grid = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint fill = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Path path = new Path();
    private float[] levels = new float[0];

    public EqCurveView(Context context) {
        super(context);
        init();
    }

    public EqCurveView(Context context, AttributeSet attrs) {
        super(context, attrs);
        init();
    }

    private void init() {
        line.setColor(0xFF3DDC97);
        line.setStrokeWidth(4f);
        line.setStyle(Paint.Style.STROKE);
        fill.setColor(0x333DDC97);
        fill.setStyle(Paint.Style.FILL);
        grid.setColor(0x33445A73);
        grid.setStrokeWidth(1f);
        setBackgroundColor(0xFF121A2B);
    }

    public void capture(Equalizer eq) {
        if (eq == null) {
            levels = new float[0];
            postInvalidate();
            return;
        }
        try {
            short n = eq.getNumberOfBands();
            short[] range = eq.getBandLevelRange();
            float span = Math.max(1, range[1] - range[0]);
            float[] next = new float[n];
            for (short i = 0; i < n; i++) {
                next[i] = (eq.getBandLevel(i) - range[0]) / span;
            }
            levels = next;
        } catch (Exception e) {
            levels = new float[0];
        }
        postInvalidate();
    }

    @Override
    protected void onDraw(Canvas canvas) {
        super.onDraw(canvas);
        int w = getWidth();
        int h = getHeight();
        if (w <= 0 || h <= 0) {
            return;
        }
        for (int i = 1; i < 4; i++) {
            float y = h * i / 4f;
            canvas.drawLine(0, y, w, y, grid);
        }
        if (levels.length == 0) {
            return;
        }
        path.reset();
        path.moveTo(0, h);
        for (int i = 0; i < levels.length; i++) {
            float x = levels.length == 1 ? w / 2f : i * (w / (float) (levels.length - 1));
            float y = h - levels[i] * (h - 8) - 4;
            if (i == 0) {
                path.lineTo(x, y);
            } else {
                path.lineTo(x, y);
            }
        }
        path.lineTo(w, h);
        path.close();
        canvas.drawPath(path, fill);
        path.reset();
        for (int i = 0; i < levels.length; i++) {
            float x = levels.length == 1 ? w / 2f : i * (w / (float) (levels.length - 1));
            float y = h - levels[i] * (h - 8) - 4;
            if (i == 0) {
                path.moveTo(x, y);
            } else {
                path.lineTo(x, y);
            }
        }
        canvas.drawPath(path, line);
    }
}
