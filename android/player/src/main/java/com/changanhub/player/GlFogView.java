package com.changanhub.player;

import android.content.Context;
import android.opengl.GLES20;
import android.opengl.GLSurfaceView;
import android.util.AttributeSet;

import javax.microedition.khronos.egl.EGLConfig;
import javax.microedition.khronos.opengles.GL10;

/** OpenGL ES 2.0 nebula driven by Visualizer bass/treble. */
public class GlFogView extends GLSurfaceView {
    private final FogRenderer renderer = new FogRenderer();

    public GlFogView(Context context) {
        super(context);
        setup();
    }

    public GlFogView(Context context, AttributeSet attrs) {
        super(context, attrs);
        setup();
    }

    private void setup() {
        setEGLContextClientVersion(2);
        setRenderer(renderer);
        setRenderMode(RENDERMODE_CONTINUOUSLY);
    }

    private static class FogRenderer implements Renderer {
        private int program;
        private int uTime;
        private int uBass;
        private int uTreble;
        private int uBeat;
        private int uRes;
        private int aPos;
        private int buf;
        private float time;

        private static final String VERT =
                "attribute vec2 aPos;"
                        + "void main(){ gl_Position = vec4(aPos, 0.0, 1.0); }";
        private static final String FRAG =
                "precision mediump float;"
                        + "uniform float uTime;"
                        + "uniform float uBass;"
                        + "uniform float uTreble;"
                        + "uniform float uBeat;"
                        + "uniform vec2 uRes;"
                        + "void main(){"
                        + " vec2 uv = gl_FragCoord.xy / uRes;"
                        + " vec2 p = uv * 2.0 - 1.0;"
                        + " p.x *= uRes.x / max(uRes.y, 1.0);"
                        + " float r = length(p);"
                        + " float ang = atan(p.y, p.x);"
                        + " float tunnel = sin(8.0 * r - uTime * 1.4 + uBass * 6.0);"
                        + " float fog = 0.55 + 0.45 * sin(ang * 3.0 + uTime + uTreble * 4.0);"
                        + " vec3 col = vec3(0.03, 0.08, 0.16);"
                        + " col += vec3(0.05, 0.45, 0.32) * fog * (0.35 + uBass);"
                        + " col += vec3(0.2, 0.7, 1.0) * (0.15 + uTreble) * (0.5 + 0.5 * tunnel);"
                        + " col += vec3(1.0, 0.85, 0.4) * uBeat * (1.0 - smoothstep(0.0, 0.7, r));"
                        + " gl_FragColor = vec4(col, 1.0);"
                        + "}";

        @Override
        public void onSurfaceCreated(GL10 gl, EGLConfig config) {
            program = link(VERT, FRAG);
            uTime = GLES20.glGetUniformLocation(program, "uTime");
            uBass = GLES20.glGetUniformLocation(program, "uBass");
            uTreble = GLES20.glGetUniformLocation(program, "uTreble");
            uBeat = GLES20.glGetUniformLocation(program, "uBeat");
            uRes = GLES20.glGetUniformLocation(program, "uRes");
            aPos = GLES20.glGetAttribLocation(program, "aPos");
            int[] ids = new int[1];
            GLES20.glGenBuffers(1, ids, 0);
            buf = ids[0];
            java.nio.FloatBuffer quad = java.nio.ByteBuffer.allocateDirect(8 * 4)
                    .order(java.nio.ByteOrder.nativeOrder())
                    .asFloatBuffer();
            quad.put(new float[]{-1, -1, 1, -1, -1, 1, 1, 1}).position(0);
            GLES20.glBindBuffer(GLES20.GL_ARRAY_BUFFER, buf);
            GLES20.glBufferData(GLES20.GL_ARRAY_BUFFER, 8 * 4, quad, GLES20.GL_STATIC_DRAW);
            GLES20.glClearColor(0.04f, 0.07f, 0.12f, 1f);
        }

        @Override
        public void onSurfaceChanged(GL10 gl, int width, int height) {
            GLES20.glViewport(0, 0, width, height);
            GLES20.glUseProgram(program);
            GLES20.glUniform2f(uRes, width, height);
        }

        @Override
        public void onDrawFrame(GL10 gl) {
            time += 0.016f;
            GLES20.glClear(GLES20.GL_COLOR_BUFFER_BIT);
            GLES20.glUseProgram(program);
            GLES20.glUniform1f(uTime, time);
            GLES20.glUniform1f(uBass, AudioEnergy.bass);
            GLES20.glUniform1f(uTreble, AudioEnergy.highs);
            GLES20.glUniform1f(uBeat, AudioEnergy.beat);
            GLES20.glBindBuffer(GLES20.GL_ARRAY_BUFFER, buf);
            GLES20.glEnableVertexAttribArray(aPos);
            GLES20.glVertexAttribPointer(aPos, 2, GLES20.GL_FLOAT, false, 0, 0);
            GLES20.glDrawArrays(GLES20.GL_TRIANGLE_STRIP, 0, 4);
        }

        private static int link(String vert, String frag) {
            int vs = compile(GLES20.GL_VERTEX_SHADER, vert);
            int fs = compile(GLES20.GL_FRAGMENT_SHADER, frag);
            int p = GLES20.glCreateProgram();
            GLES20.glAttachShader(p, vs);
            GLES20.glAttachShader(p, fs);
            GLES20.glLinkProgram(p);
            return p;
        }

        private static int compile(int type, String src) {
            int s = GLES20.glCreateShader(type);
            GLES20.glShaderSource(s, src);
            GLES20.glCompileShader(s);
            return s;
        }
    }
}
