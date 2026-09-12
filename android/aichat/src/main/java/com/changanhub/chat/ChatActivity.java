package com.changanhub.chat;

import android.Manifest;
import android.app.Activity;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Context;
import android.content.pm.PackageManager;
import android.net.ConnectivityManager;
import android.net.NetworkInfo;
import android.os.Bundle;
import android.os.PowerManager;
import android.speech.RecognitionListener;
import android.speech.RecognizerIntent;
import android.speech.SpeechRecognizer;
import android.speech.tts.TextToSpeech;
import android.speech.tts.Voice;
import android.util.DisplayMetrics;
import android.view.View;
import android.view.ViewGroup;
import android.widget.AdapterView;
import android.widget.ArrayAdapter;
import android.widget.BaseAdapter;
import android.widget.Button;
import android.widget.CompoundButton;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ListView;
import android.widget.RadioButton;
import android.widget.RadioGroup;
import android.widget.SeekBar;
import android.widget.Spinner;
import android.widget.Switch;
import android.widget.TextView;
import android.widget.Toast;

import java.io.File;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.List;
import java.util.Locale;
import java.util.Set;

public class ChatActivity extends Activity {
    private View stage;
    private TextView tabChat;
    private TextView tabSettings;
    private TextView tabHistory;
    private TextView tabVoice;
    private View pageChat;
    private View pageSettings;
    private View pageHistory;
    private View pageVoice;
    private ListView list;
    private ListView historyList;
    private TextView empty;
    private TextView status;
    private EditText input;
    private Switch ttsSwitch;
    private LinearLayout settingsBox;
    private LinearLayout voiceBox;
    private LinearLayout prompts;
    private RadioGroup providerGroup;
    private EditText dsUrl;
    private EditText dsKey;
    private Spinner dsModel;
    private EditText yaUrl;
    private EditText yaKey;
    private EditText yaFolder;
    private Spinner yaModel;
    private EditText temp;
    private EditText maxTokens;
    private EditText timeout;
    private EditText proxyHost;
    private EditText proxyPort;
    private Spinner proxyType;
    private EditText systemPrompt;
    private Switch voiceAuto;
    private Spinner voiceSpinner;
    private SeekBar rateBar;
    private SeekBar pitchBar;
    private SeekBar volBar;
    private TextView voiceWarn;
    private int tab;
    private boolean busy;
    private ChatStore.Session session = new ChatStore.Session();
    private final Adapter adapter = new Adapter();
    private final List<ChatStore.Session> sessions = new ArrayList<>();
    private ArrayAdapter<String> historyAdapter;
    private Llm.Cancel cancel;
    private SpeechRecognizer stt;
    private PowerManager.WakeLock wakeLock;
    private final SimpleDateFormat clock = new SimpleDateFormat("HH:mm", Locale.US);

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_chat);
        stage = findViewById(R.id.stage);
        applyCenterPadding();
        tabChat = findViewById(R.id.tab_chat);
        tabSettings = findViewById(R.id.tab_settings);
        tabHistory = findViewById(R.id.tab_history);
        tabVoice = findViewById(R.id.tab_voice);
        pageChat = findViewById(R.id.page_chat);
        pageSettings = findViewById(R.id.page_settings);
        pageHistory = findViewById(R.id.page_history);
        pageVoice = findViewById(R.id.page_voice);
        list = findViewById(R.id.list);
        historyList = findViewById(R.id.history_list);
        empty = findViewById(R.id.empty);
        status = findViewById(R.id.status);
        input = findViewById(R.id.input);
        ttsSwitch = findViewById(R.id.tts_switch);
        settingsBox = findViewById(R.id.settings_box);
        voiceBox = findViewById(R.id.voice_box);
        prompts = findViewById(R.id.prompts);
        list.setAdapter(adapter);
        historyAdapter = new ArrayAdapter<String>(this, android.R.layout.simple_list_item_1, new ArrayList<String>());
        historyList.setAdapter(historyAdapter);
        PowerManager pm = (PowerManager) getSystemService(POWER_SERVICE);
        if (pm != null) {
            wakeLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "aichat:llm");
            wakeLock.setReferenceCounted(false);
        }
        tabChat.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                showTab(0);
            }
        });
        tabSettings.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                showTab(1);
            }
        });
        tabHistory.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                showTab(2);
            }
        });
        tabVoice.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                showTab(3);
            }
        });
        findViewById(R.id.btn_send).setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                send(input.getText().toString());
            }
        });
        findViewById(R.id.btn_stop).setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                if (cancel != null) {
                    cancel.stop = true;
                }
                TtsService.stop(ChatActivity.this);
                setBusy(false, "остановлено");
            }
        });
        View mic = findViewById(R.id.btn_mic);
        if (!SpeechRecognizer.isRecognitionAvailable(this)) {
            mic.setVisibility(View.GONE);
        } else {
            mic.setOnClickListener(new View.OnClickListener() {
                @Override
                public void onClick(View v) {
                    listen();
                }
            });
        }
        ttsSwitch.setChecked(Prefs.autoTts(this));
        ttsSwitch.setOnCheckedChangeListener(new CompoundButton.OnCheckedChangeListener() {
            @Override
            public void onCheckedChanged(CompoundButton buttonView, boolean isChecked) {
                Prefs.putBool(ChatActivity.this, "auto_tts", isChecked);
                if (voiceAuto != null) {
                    voiceAuto.setChecked(isChecked);
                }
            }
        });
        findViewById(R.id.btn_new_chat).setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                session = ChatStore.create(ChatActivity.this);
                refreshChat();
                showTab(0);
            }
        });
        findViewById(R.id.btn_export).setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                File file = ChatStore.exportFile(ChatActivity.this, session);
                copy(ChatStore.load(ChatActivity.this, session.id).title);
                toast("JSON: " + file.getAbsolutePath());
            }
        });
        findViewById(R.id.btn_import).setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                File file = new File(getFilesDir(), "export-chat.json");
                try {
                    session = ChatStore.importJson(ChatActivity.this, ChatStore.read(file));
                    refreshChat();
                    toast("импортирован " + session.title);
                } catch (Exception e) {
                    toast("положите JSON в " + file.getAbsolutePath());
                }
            }
        });
        historyList.setOnItemClickListener(new AdapterView.OnItemClickListener() {
            @Override
            public void onItemClick(AdapterView<?> parent, View view, int position, long id) {
                if (position < 0 || position >= sessions.size()) {
                    return;
                }
                session = ChatStore.load(ChatActivity.this, sessions.get(position).id);
                Prefs.put(ChatActivity.this, "chat_id", session.id);
                refreshChat();
                showTab(0);
            }
        });
        buildPrompts();
        buildSettings();
        buildVoice();
        loadSession();
        showTab(0);
        TtsService.stop(this);
        String warn = TtsService.warning();
        if (warn.length() > 0) {
            status.setText(warn);
        }
    }

    private void applyCenterPadding() {
        DisplayMetrics dm = getResources().getDisplayMetrics();
        int padX = Math.max(8, (int) (dm.widthPixels * 0.20f));
        int padY = Math.max(8, (int) (dm.heightPixels * 0.30f));
        stage.setPadding(padX, padY, padX, padY);
    }

    private void showTab(int next) {
        tab = next;
        paint(tabChat, next == 0);
        paint(tabSettings, next == 1);
        paint(tabHistory, next == 2);
        paint(tabVoice, next == 3);
        pageChat.setVisibility(next == 0 ? View.VISIBLE : View.GONE);
        pageSettings.setVisibility(next == 1 ? View.VISIBLE : View.GONE);
        pageHistory.setVisibility(next == 2 ? View.VISIBLE : View.GONE);
        pageVoice.setVisibility(next == 3 ? View.VISIBLE : View.GONE);
        if (next == 2) {
            refreshHistory();
        }
        if (next == 3) {
            voiceWarn.setText(TtsService.warning());
        }
    }

    private void paint(TextView view, boolean on) {
        view.setBackgroundColor(on ? 0xFF3DDC97 : 0xFF223049);
        view.setTextColor(on ? 0xFF0B1220 : 0xFFF3F6FB);
    }

    private void loadSession() {
        String id = Prefs.chatId(this);
        if (id.length() == 0) {
            session = ChatStore.create(this);
        } else {
            session = ChatStore.load(this, id);
            if (session.id.length() == 0) {
                session = ChatStore.create(this);
            }
        }
        refreshChat();
    }

    private void refreshChat() {
        adapter.notifyDataSetChanged();
        boolean none = session.messages.isEmpty();
        empty.setVisibility(none ? View.VISIBLE : View.GONE);
        list.setVisibility(none ? View.GONE : View.VISIBLE);
        if (!none) {
            list.setSelection(session.messages.size() - 1);
        }
    }

    private void refreshHistory() {
        sessions.clear();
        sessions.addAll(ChatStore.list(this));
        historyAdapter.clear();
        for (int i = 0; i < sessions.size(); i++) {
            ChatStore.Session s = sessions.get(i);
            historyAdapter.add(s.title + "  ·  " + clock.format(new Date(s.updated)));
        }
        historyAdapter.notifyDataSetChanged();
    }

    private void send(String text) {
        text = text == null ? "" : text.trim();
        if (text.length() == 0 || busy) {
            return;
        }
        if (!online()) {
            toast("Нет сети. Включите интернет на ГУ.");
            return;
        }
        input.setText("");
        session.messages.add(Msg.of("user", text));
        final Msg assistant = Msg.of("assistant", "");
        session.messages.add(assistant);
        ChatStore.save(this, session);
        refreshChat();
        setBusy(true, "думаю…");
        hold(true);
        cancel = new Llm.Cancel();
        final Llm.Cancel local = cancel;
        new Thread(new Runnable() {
            @Override
            public void run() {
                Llm.complete(ChatActivity.this, session.messages, new Llm.Listener() {
                    @Override
                    public void onDelta(final String token) {
                        runOnUiThread(new Runnable() {
                            @Override
                            public void run() {
                                assistant.text = assistant.text + token;
                                adapter.notifyDataSetChanged();
                                list.setSelection(session.messages.size() - 1);
                            }
                        });
                    }

                    @Override
                    public void onDone(final String full) {
                        runOnUiThread(new Runnable() {
                            @Override
                            public void run() {
                                assistant.text = full;
                                ChatStore.save(ChatActivity.this, session);
                                refreshChat();
                                setBusy(false, Prefs.provider(ChatActivity.this));
                                hold(false);
                                if (Prefs.autoTts(ChatActivity.this) && full.trim().length() > 0) {
                                    TtsService.speak(ChatActivity.this, full);
                                }
                            }
                        });
                    }

                    @Override
                    public void onError(final String message) {
                        runOnUiThread(new Runnable() {
                            @Override
                            public void run() {
                                assistant.text = message;
                                assistant.error = true;
                                ChatStore.save(ChatActivity.this, session);
                                refreshChat();
                                setBusy(false, message);
                                hold(false);
                            }
                        });
                    }
                }, local);
            }
        }).start();
    }

    private void setBusy(boolean on, String text) {
        busy = on;
        status.setText(text == null ? "" : text);
        findViewById(R.id.btn_send).setEnabled(!on);
    }

    private void hold(boolean on) {
        try {
            if (wakeLock == null) {
                return;
            }
            if (on && !wakeLock.isHeld()) {
                wakeLock.acquire(120000);
            } else if (!on && wakeLock.isHeld()) {
                wakeLock.release();
            }
        } catch (Exception ignored) {
        }
    }

    private boolean online() {
        try {
            ConnectivityManager cm = (ConnectivityManager) getSystemService(CONNECTIVITY_SERVICE);
            NetworkInfo info = cm == null ? null : cm.getActiveNetworkInfo();
            return info != null && info.isConnected();
        } catch (Exception e) {
            return true;
        }
    }

    private void listen() {
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, 9);
            toast("Разрешите микрофон и нажмите ещё раз.");
            return;
        }
        if (!SpeechRecognizer.isRecognitionAvailable(this)) {
            toast("На этой ГУ нет Android SpeechRecognizer. Пишите текстом.");
            return;
        }
        if (stt == null) {
            stt = SpeechRecognizer.createSpeechRecognizer(this);
            stt.setRecognitionListener(new RecognitionListener() {
                @Override
                public void onReadyForSpeech(Bundle params) {
                    status.setText("говорите…");
                }

                @Override
                public void onBeginningOfSpeech() {
                }

                @Override
                public void onRmsChanged(float rmsdB) {
                }

                @Override
                public void onBufferReceived(byte[] buffer) {
                }

                @Override
                public void onEndOfSpeech() {
                }

                @Override
                public void onError(int error) {
                    status.setText("микрофон: ошибка " + error);
                }

                @Override
                public void onResults(Bundle results) {
                    ArrayList<String> texts = results.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION);
                    if (texts != null && !texts.isEmpty()) {
                        input.setText(texts.get(0));
                        send(texts.get(0));
                    }
                }

                @Override
                public void onPartialResults(Bundle partialResults) {
                }

                @Override
                public void onEvent(int eventType, Bundle params) {
                }
            });
        }
        android.content.Intent intent = new android.content.Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH);
        intent.putExtra(RecognizerIntent.EXTRA_LANGUAGE, "ru-RU");
        intent.putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM);
        stt.startListening(intent);
    }

    private void buildPrompts() {
        String[] names = {"Переведи", "Объясни", "Сократи"};
        String[] texts = {
                "Переведи на русский кратко: ",
                "Объясни простыми словами: ",
                "Сократи до трёх предложений: "
        };
        for (int i = 0; i < names.length; i++) {
            final String prefix = texts[i];
            Button b = chip(names[i], false);
            b.setOnClickListener(new View.OnClickListener() {
                @Override
                public void onClick(View v) {
                    input.setText(prefix);
                    input.setSelection(prefix.length());
                }
            });
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.WRAP_CONTENT, 40);
            lp.setMargins(0, 0, 6, 6);
            prompts.addView(b, lp);
        }
    }

    private void buildSettings() {
        settingsBox.removeAllViews();
        addLabel(settingsBox, "Провайдер");
        providerGroup = new RadioGroup(this);
        providerGroup.setOrientation(LinearLayout.HORIZONTAL);
        RadioButton ds = radio("DeepSeek", Prefs.PROVIDER_DEEPSEEK.equals(Prefs.provider(this)));
        RadioButton ya = radio("Yandex", Prefs.PROVIDER_YANDEX.equals(Prefs.provider(this)));
        ds.setId(View.generateViewId());
        ya.setId(View.generateViewId());
        providerGroup.addView(ds);
        providerGroup.addView(ya);
        settingsBox.addView(providerGroup);
        addLabel(settingsBox, "DeepSeek URL");
        dsUrl = field(Prefs.deepseekUrl(this), false);
        settingsBox.addView(dsUrl);
        addLabel(settingsBox, "DeepSeek API Key");
        dsKey = field(Prefs.deepseekKey(this), true);
        settingsBox.addView(dsKey);
        addLabel(settingsBox, "Модель DeepSeek");
        dsModel = spinner(new String[]{"deepseek-chat", "deepseek-reasoner"}, Prefs.deepseekModel(this));
        settingsBox.addView(dsModel);
        addLabel(settingsBox, "Yandex URL");
        yaUrl = field(Prefs.yandexUrl(this), false);
        settingsBox.addView(yaUrl);
        addLabel(settingsBox, "Yandex Folder ID");
        yaFolder = field(Prefs.yandexFolder(this), false);
        settingsBox.addView(yaFolder);
        addLabel(settingsBox, "Yandex IAM / API-ключ");
        yaKey = field(Prefs.yandexKey(this), true);
        settingsBox.addView(yaKey);
        addLabel(settingsBox, "Модель Yandex");
        yaModel = spinner(new String[]{"yandexgpt-lite", "yandexgpt", "yandexgpt-32k"}, Prefs.yandexModel(this));
        settingsBox.addView(yaModel);
        addLabel(settingsBox, "Temperature");
        temp = field(String.valueOf(Prefs.temperature(this)), false);
        settingsBox.addView(temp);
        addLabel(settingsBox, "max_tokens");
        maxTokens = field(String.valueOf(Prefs.maxTokens(this)), false);
        settingsBox.addView(maxTokens);
        addLabel(settingsBox, "Таймаут, сек");
        timeout = field(String.valueOf(Prefs.timeoutSec(this)), false);
        settingsBox.addView(timeout);
        addLabel(settingsBox, "Прокси host");
        proxyHost = field(Prefs.proxyHost(this), false);
        settingsBox.addView(proxyHost);
        addLabel(settingsBox, "Прокси port");
        proxyPort = field(Prefs.proxyPort(this) == 0 ? "" : String.valueOf(Prefs.proxyPort(this)), false);
        settingsBox.addView(proxyPort);
        addLabel(settingsBox, "Тип прокси");
        proxyType = spinner(new String[]{"HTTP", "SOCKS"}, Prefs.proxyType(this));
        settingsBox.addView(proxyType);
        addLabel(settingsBox, "Системный промпт");
        systemPrompt = field(Prefs.systemPrompt(this), false);
        systemPrompt.setMinLines(2);
        settingsBox.addView(systemPrompt);
        Button save = chip("Сохранить", true);
        save.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                persistSettings();
                toast("сохранено");
            }
        });
        Button ping = chip("Проверить подключение", true);
        ping.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                persistSettings();
                pingApi();
            }
        });
        Button reset = chip("Сбросить настройки", false);
        reset.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                Prefs.reset(ChatActivity.this);
                settingsBox.removeAllViews();
                buildSettings();
                toast("сброшено");
            }
        });
        settingsBox.addView(save);
        settingsBox.addView(ping);
        settingsBox.addView(reset);
    }

    private void persistSettings() {
        boolean yandex = providerGroup.getCheckedRadioButtonId() == providerGroup.getChildAt(1).getId();
        Prefs.put(this, "provider", yandex ? Prefs.PROVIDER_YANDEX : Prefs.PROVIDER_DEEPSEEK);
        Prefs.put(this, "ds_url", dsUrl.getText().toString().trim());
        Prefs.putSecret(this, "ds_key", dsKey.getText().toString().trim());
        Prefs.put(this, "ds_model", String.valueOf(dsModel.getSelectedItem()));
        Prefs.put(this, "ya_url", yaUrl.getText().toString().trim());
        Prefs.put(this, "ya_folder", yaFolder.getText().toString().trim());
        Prefs.putSecret(this, "ya_key", yaKey.getText().toString().trim());
        Prefs.put(this, "ya_model", String.valueOf(yaModel.getSelectedItem()));
        Prefs.put(this, "temp", temp.getText().toString().trim());
        Prefs.putInt(this, "max_tokens", parseInt(maxTokens.getText().toString(), 1024));
        Prefs.putInt(this, "timeout", parseInt(timeout.getText().toString(), 45));
        Prefs.put(this, "proxy_host", proxyHost.getText().toString().trim());
        Prefs.putInt(this, "proxy_port", parseInt(proxyPort.getText().toString(), 0));
        Prefs.put(this, "proxy_type", String.valueOf(proxyType.getSelectedItem()));
        Prefs.put(this, "system", systemPrompt.getText().toString());
    }

    private void pingApi() {
        setBusy(true, "проверка API…");
        new Thread(new Runnable() {
            @Override
            public void run() {
                Llm.ping(ChatActivity.this, new Llm.Listener() {
                    @Override
                    public void onDelta(String token) {
                    }

                    @Override
                    public void onDone(final String full) {
                        runOnUiThread(new Runnable() {
                            @Override
                            public void run() {
                                setBusy(false, "связь есть: " + full);
                                toast("Подключение успешно");
                            }
                        });
                    }

                    @Override
                    public void onError(final String message) {
                        runOnUiThread(new Runnable() {
                            @Override
                            public void run() {
                                setBusy(false, message);
                                toast(message);
                            }
                        });
                    }
                });
            }
        }).start();
    }

    private void buildVoice() {
        voiceBox.removeAllViews();
        voiceAuto = new Switch(this);
        voiceAuto.setText("Автоозвучка ответов");
        voiceAuto.setTextColor(0xFFF3F6FB);
        voiceAuto.setChecked(Prefs.autoTts(this));
        voiceAuto.setOnCheckedChangeListener(new CompoundButton.OnCheckedChangeListener() {
            @Override
            public void onCheckedChanged(CompoundButton buttonView, boolean isChecked) {
                Prefs.putBool(ChatActivity.this, "auto_tts", isChecked);
                ttsSwitch.setChecked(isChecked);
            }
        });
        voiceBox.addView(voiceAuto);
        TextView sttNote = new TextView(this);
        sttNote.setTextColor(0xFF9AA7B8);
        sttNote.setTextSize(14);
        sttNote.setPadding(0, 8, 0, 8);
        if (!SpeechRecognizer.isRecognitionAvailable(this)) {
            sttNote.setText(
                "Кнопки микрофона нет: на Feiyu нет Android SpeechRecognizer. "
                    + "Голосовой помощник машины (iFlytek) к этому чату не подключён. "
                    + "Пишите текстом — Яндекс-клавиатура работает. "
                    + "Русские вкладки — из приложения; язык системы ГУ может остаться китайским. "
                    + "Озвучка ответов ниже — это TTS, не распознавание речи."
            );
        } else {
            sttNote.setText("Голосовой ввод — кнопка микрофона в чате.");
        }
        voiceBox.addView(sttNote);
        addLabel(voiceBox, "Голос");
        voiceSpinner = spinner(new String[]{"по умолчанию (ru-RU)"}, "по умолчанию (ru-RU)");
        voiceBox.addView(voiceSpinner);
        addLabel(voiceBox, "Скорость");
        rateBar = seek((int) (Prefs.speechRate(this) * 50), 100);
        voiceBox.addView(rateBar);
        addLabel(voiceBox, "Тон");
        pitchBar = seek((int) (Prefs.pitch(this) * 50), 100);
        voiceBox.addView(pitchBar);
        addLabel(voiceBox, "Громкость");
        volBar = seek((int) (Prefs.volume(this) * 100), 100);
        voiceBox.addView(volBar);
        rateBar.setOnSeekBarChangeListener(simpleSeek(new Runnable() {
            @Override
            public void run() {
                Prefs.putFloat(ChatActivity.this, "tts_rate", Math.max(0.4f, rateBar.getProgress() / 50f));
            }
        }));
        pitchBar.setOnSeekBarChangeListener(simpleSeek(new Runnable() {
            @Override
            public void run() {
                Prefs.putFloat(ChatActivity.this, "tts_pitch", Math.max(0.4f, pitchBar.getProgress() / 50f));
            }
        }));
        volBar.setOnSeekBarChangeListener(simpleSeek(new Runnable() {
            @Override
            public void run() {
                Prefs.putFloat(ChatActivity.this, "tts_vol", volBar.getProgress() / 100f);
            }
        }));
        voiceWarn = new TextView(this);
        voiceWarn.setTextColor(0xFFFF6B6B);
        voiceWarn.setTextSize(14);
        voiceBox.addView(voiceWarn);
        Button test = chip("Проверить голос", true);
        test.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                TtsService.speak(ChatActivity.this, "Привет. Это проверка озвучки в машине.");
            }
        });
        voiceBox.addView(test);
        loadVoices();
    }

    private TextToSpeech voiceProbe;

    private void loadVoices() {
        if (voiceProbe != null) {
            try {
                voiceProbe.shutdown();
            } catch (Exception ignored) {
            }
        }
        voiceProbe = new TextToSpeech(getApplicationContext(), new TextToSpeech.OnInitListener() {
            @Override
            public void onInit(int status) {
                if (status != TextToSpeech.SUCCESS || voiceProbe == null) {
                    voiceWarn.setText("На ГУ нет TTS-движка. Откройте системные настройки синтеза речи.");
                    return;
                }
                try {
                    int lang = voiceProbe.setLanguage(new Locale("ru", "RU"));
                    if (lang == TextToSpeech.LANG_MISSING_DATA || lang == TextToSpeech.LANG_NOT_SUPPORTED) {
                        voiceWarn.setText("Русский голос недоступен. Выберите другой движок в настройках Android.");
                    }
                    List<String> names = new ArrayList<>();
                    names.add("по умолчанию (ru-RU)");
                    Set<Voice> voices = voiceProbe.getVoices();
                    String current = Prefs.voiceName(ChatActivity.this);
                    int selected = 0;
                    if (voices != null) {
                        int i = 1;
                        for (Voice voice : voices) {
                            Locale loc = voice.getLocale();
                            String label = voice.getName();
                            if (loc != null) {
                                label = loc.getLanguage() + " · " + voice.getName();
                            }
                            names.add(label + "\t" + voice.getName());
                            if (voice.getName().equals(current)) {
                                selected = i;
                            }
                            i++;
                        }
                    }
                    ArrayAdapter<String> ad = new ArrayAdapter<String>(
                            ChatActivity.this, android.R.layout.simple_spinner_item, names);
                    ad.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item);
                    voiceSpinner.setAdapter(ad);
                    voiceSpinner.setSelection(Math.min(selected, names.size() - 1));
                    voiceSpinner.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener() {
                        @Override
                        public void onItemSelected(AdapterView<?> parent, View view, int position, long id) {
                            String item = String.valueOf(parent.getItemAtPosition(position));
                            int tabAt = item.lastIndexOf('\t');
                            Prefs.put(ChatActivity.this, "tts_voice", tabAt > 0 ? item.substring(tabAt + 1) : "");
                        }

                        @Override
                        public void onNothingSelected(AdapterView<?> parent) {
                        }
                    });
                } catch (Exception ignored) {
                }
            }
        });
    }

    private Button chip(String text, boolean accent) {
        Button b = new Button(this);
        b.setText(text);
        b.setTextColor(accent ? 0xFF0B1220 : 0xFFF3F6FB);
        b.setBackgroundColor(accent ? 0xFF3DDC97 : 0xFF223049);
        b.setMinHeight(48);
        return b;
    }

    private RadioButton radio(String text, boolean on) {
        RadioButton b = new RadioButton(this);
        b.setText(text);
        b.setTextColor(0xFFF3F6FB);
        b.setChecked(on);
        b.setTextSize(16);
        return b;
    }

    private EditText field(String value, boolean password) {
        EditText e = new EditText(this);
        e.setText(value);
        e.setTextColor(0xFFF3F6FB);
        e.setHintTextColor(0xFF9AA7B8);
        e.setBackgroundColor(0xFF182235);
        e.setPadding(10, 10, 10, 10);
        e.setTextSize(15);
        e.setSingleLine(!password ? false : true);
        if (password) {
            e.setInputType(android.text.InputType.TYPE_CLASS_TEXT
                    | android.text.InputType.TYPE_TEXT_VARIATION_PASSWORD);
        }
        return e;
    }

    private Spinner spinner(String[] items, String selected) {
        Spinner s = new Spinner(this);
        ArrayAdapter<String> ad = new ArrayAdapter<String>(this, android.R.layout.simple_spinner_item, items);
        ad.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item);
        s.setAdapter(ad);
        for (int i = 0; i < items.length; i++) {
            if (items[i].equals(selected)) {
                s.setSelection(i);
            }
        }
        return s;
    }

    private SeekBar seek(int progress, int max) {
        SeekBar bar = new SeekBar(this);
        bar.setMax(max);
        bar.setProgress(progress);
        return bar;
    }

    private SeekBar.OnSeekBarChangeListener simpleSeek(final Runnable run) {
        return new SeekBar.OnSeekBarChangeListener() {
            @Override
            public void onProgressChanged(SeekBar seekBar, int progress, boolean fromUser) {
            }

            @Override
            public void onStartTrackingTouch(SeekBar seekBar) {
            }

            @Override
            public void onStopTrackingTouch(SeekBar seekBar) {
                run.run();
            }
        };
    }

    private void addLabel(LinearLayout box, String text) {
        TextView t = new TextView(this);
        t.setText(text);
        t.setTextColor(0xFF9AA7B8);
        t.setTextSize(13);
        t.setPadding(0, 8, 0, 2);
        box.addView(t);
    }

    private static int parseInt(String raw, int fallback) {
        try {
            return Integer.parseInt(raw.trim());
        } catch (Exception e) {
            return fallback;
        }
    }

    private void copy(String text) {
        ClipboardManager cm = (ClipboardManager) getSystemService(CLIPBOARD_SERVICE);
        if (cm != null) {
            cm.setPrimaryClip(ClipData.newPlainText("chat", text == null ? "" : text));
        }
    }

    private void toast(String text) {
        Toast.makeText(this, text, Toast.LENGTH_SHORT).show();
    }

    @Override
    protected void onDestroy() {
        hold(false);
        if (stt != null) {
            try {
                stt.destroy();
            } catch (Exception ignored) {
            }
        }
        if (voiceProbe != null) {
            try {
                voiceProbe.shutdown();
            } catch (Exception ignored) {
            }
            voiceProbe = null;
        }
        super.onDestroy();
    }

    private class Adapter extends BaseAdapter {
        @Override
        public int getCount() {
            return session.messages.size();
        }

        @Override
        public Object getItem(int position) {
            return session.messages.get(position);
        }

        @Override
        public long getItemId(int position) {
            return position;
        }

        @Override
        public View getView(int position, View convertView, ViewGroup parent) {
            if (convertView == null) {
                convertView = getLayoutInflater().inflate(R.layout.row_message, parent, false);
            }
            final Msg m = session.messages.get(position);
            TextView who = convertView.findViewById(R.id.who);
            TextView body = convertView.findViewById(R.id.body);
            TextView when = convertView.findViewById(R.id.when);
            Button copyBtn = convertView.findViewById(R.id.btn_copy);
            Button speakBtn = convertView.findViewById(R.id.btn_speak);
            boolean ai = "assistant".equals(m.role);
            who.setText(ai ? "ИИ" : "Вы");
            body.setText(m.text);
            body.setTextColor(m.error ? 0xFFFF6B6B : 0xFFF3F6FB);
            when.setText(clock.format(new Date(m.ts)));
            convertView.setBackgroundColor(ai ? 0xFF182235 : 0xFF1E3A34);
            speakBtn.setVisibility(ai ? View.VISIBLE : View.GONE);
            copyBtn.setOnClickListener(new View.OnClickListener() {
                @Override
                public void onClick(View v) {
                    copy(m.text);
                    toast("скопировано");
                }
            });
            speakBtn.setOnClickListener(new View.OnClickListener() {
                @Override
                public void onClick(View v) {
                    TtsService.speak(ChatActivity.this, m.text);
                }
            });
            return convertView;
        }
    }
}
