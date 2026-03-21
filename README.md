# AI Polyglot Kit — Multi-Provider Voice and Translate AI for Windows

System-wide dictation, text normalization, and translation for Windows — powered by 7 STT and 8+ LLM providers with automatic failover.

> Built by **dmdukr** with [Claude](https://claude.ai) (Anthropic) as AI co-author.

---

*[Українська версія нижче / Ukrainian version below](#ai-polyglot-kit--багатосервісний-голосовий-ai-для-windows)*

---

## Features

- **7 STT providers** (6 with free tier) — Groq, Soniox, Deepgram, Gladia, Speechmatics, AssemblyAI + OpenAI (paid)
- **8+ LLM providers** (7 with free tier) — Groq, Google AI Studio, Cerebras, Mistral, OpenRouter, xAI, GitHub Models + OpenAI (paid)
- **3-slot failover** — when provider #1 exhausts its free limit, auto-switch to #2, then #3
- **Auto-detect provider** — paste API key → app detects the service and fetches available models
- **Two recording modes** — Hold (hold key to record, release to stop) or Toggle (press to start, press again to stop)
- **AI normalization** — LLM post-processing fixes recognition errors, removes filler words, formats text
- **Quick Translate** — double Ctrl+C on selected text → instant translation (DeepL or LLM)
- **Self-learning profile** — learns from your corrections via double-tap feedback
- **Auto-update** — checks GitHub releases, downloads and installs new versions
- **Dark/Light theme** — follows Windows theme or manual choice

## Installation

1. Download `AIPolyglotKit-setup.exe` from [Releases](https://github.com/dmdukr/ai-polyglot-kit/releases)
2. Run the installer
3. Get free API keys from one or more providers (see [Provider Guide](#stt-providers) below)
4. Click tray icon → **Settings** → paste API keys into STT, Normalization, and Translation tabs

> **Updating**: automatic — the app checks for new versions and notifies you.

---

## STT Providers

Speech-to-text providers for voice recognition. Add up to 3 in Settings → STT tab.

*Data as of March 2026*

| # | Provider | Model | Free Tier | Languages | WER | How to Get API Key |
|---|----------|-------|-----------|-----------|-----|-------------------|
| 1 | **Groq** | Whisper Large V3 Turbo | **~8 h/day** (daily reset) | 99+ | 0.16% | [console.groq.com](https://console.groq.com) → Sign Up → API Keys → Create |
| 2 | **Soniox** | stt-async-v4 | **$200 credit ≈ 2000 h** (one-time) | 60+ | Top benchmark | [soniox.com](https://soniox.com) → Sign Up → Dashboard → API Key |
| 3 | **Deepgram** | Nova-3 | **$200 credit ≈ 330 h** (one-time) | 50+ | 0.14% | [console.deepgram.com](https://console.deepgram.com) → Sign Up → API Keys |
| 4 | **Gladia** | Solaria-1 | **10 h/month** + $50 credit | 100+ | 0.16% | [app.gladia.io](https://app.gladia.io) → Sign Up → API Key |
| 5 | **Speechmatics** | Enhanced (Ursa) | **8 h/month** | 50+ | 0.18% | [portal.speechmatics.com](https://portal.speechmatics.com) → Sign Up → API Key |
| 6 | **AssemblyAI** | Universal-2 | **8 h/month** | 99 | 0.20% | [assemblyai.com](https://www.assemblyai.com) → Sign Up → Dashboard → API Key |
| 7 | **OpenAI** | Whisper, GPT-4o-transcribe | **No free tier** ($0.006/min) | 99+ | 0.11% | [platform.openai.com](https://platform.openai.com) → API Keys |

### Which STT to choose?

- **Best free for daily use**: **Groq** — 8 hours/day, every day, no expiry
- **Largest one-time credit**: **Soniox** (2000 h) or **Deepgram** (330 h)
- **Best for mixed languages (UK/RU/EN)**: **Groq Whisper V3** or **Soniox v4** (mid-sentence language switching)
- **Best absolute accuracy**: **OpenAI GPT-4o-transcribe** (paid only)

### Recommended setup (free)

| Slot | Provider | Why |
|------|----------|-----|
| #1 | Groq | Best daily free limit (8 h/day) |
| #2 | Soniox | 2000 h backup, great multilingual |
| #3 | Deepgram | 330 h backup, Nova-3 accuracy |

---

## LLM Providers

LLM providers for text normalization (fixing recognition errors) and translation. Add up to 3 in Settings → Normalization and Translation tabs.

All LLM providers use the same OpenAI-compatible API — just paste the key, the app detects the service automatically.

*Data as of March 2026*

| # | Provider | Best Free Model | Free Tier | Key Prefix | How to Get API Key |
|---|----------|----------------|-----------|------------|-------------------|
| 1 | **Groq** | Llama 3.3 70B | **1K req/day, 100K tok/day** | `gsk_` | [console.groq.com](https://console.groq.com) → API Keys |
| 2 | **Google AI Studio** | Gemini 2.5 Flash | **250 req/day, 250K tok/min** | `AIzaSy` | [aistudio.google.com](https://aistudio.google.com) → Get API Key |
| 3 | **Cerebras** | Llama 3.3 70B | **~1M tok/day** | `csk-` | [cloud.cerebras.ai](https://cloud.cerebras.ai) → Sign Up → API Key |
| 4 | **Mistral** | Mistral Small 4 | **~1B tok/month** | hex string | [console.mistral.ai](https://console.mistral.ai) → API Keys |
| 5 | **OpenRouter** | DeepSeek R1, Llama 4 | **50 req/day** | `sk-or-` | [openrouter.ai](https://openrouter.ai) → Keys |
| 6 | **xAI** | Grok 4 | **$25 credit** (one-time) | `xai-` | [console.x.ai](https://console.x.ai) → API Keys |
| 7 | **GitHub Models** | GPT-4o, o3 | **50-150 req/day** | `ghp_` | [github.com/settings/tokens](https://github.com/settings/tokens) |
| 8 | **OpenAI** | GPT-4o-mini | **No free tier** | `sk-` | [platform.openai.com](https://platform.openai.com) → API Keys |

### Which LLM to choose?

- **Best free for normalization**: **Groq** (Llama 3.3 70B, fast, good multilingual)
- **Most generous free**: **Google AI Studio** (Gemini 2.5 Flash, 250K tok/min)
- **Fastest inference**: **Groq** (300+ tok/s) or **Cerebras** (2000+ tok/s)

### Recommended setup (free)

| Slot | Provider | Why |
|------|----------|-----|
| #1 | Groq | Fast, good Llama 3.3 70B, same key as STT |
| #2 | Google AI Studio | Generous limits, strong multilingual |
| #3 | Cerebras | Ultra-fast backup |

---

## Translation Providers

Translation uses the same LLM slots (3 providers) plus optional DeepL keys for higher quality.

| Provider | Free Tier | Quality | How to Get |
|----------|-----------|---------|-----------|
| **DeepL** | **500K chars/month** per key | Best translation quality | [deepl.com/pro](https://www.deepl.com/pro) → API tab → Free |
| **Any LLM** | Same as LLM table above | Good, context-aware | Same API keys |

> **Tip**: You can create up to 5 free DeepL accounts for 2.5M chars/month total.

---

## How It Works

```
Hold hotkey → Record speech
    ↓
STT Provider (#1, #2, or #3) → Raw transcription
    ↓
LLM Provider → Fix errors, punctuation, filler words
    ↓
Type into active window
    ↓
User edits → Double-tap → App learns from corrections
```

## Usage

| Action | How |
|--------|-----|
| **Record** | Hold hotkey (default: `F12`) → speak → release |
| **Translate** | Select text → Ctrl+C twice quickly → translation overlay |
| **Feedback** | After dictation, edit text, then double-tap hotkey |
| **Settings** | Click tray icon → Settings |
| **Quit** | Right-click tray icon → Quit |

## Settings Tabs

| Tab | What's there |
|-----|-------------|
| **Interface** | Sounds, notifications, autostart, language, theme, telemetry |
| **STT** | 3 provider slots for speech recognition + language selection |
| **Dictation** | Hotkey, recording mode, microphone, noise filter |
| **Normalization** | 3 LLM provider slots + normalization toggle |
| **Translation** | 3 LLM provider slots + DeepL keys |

## Bug Reports

Found a bug? [Open an issue](https://github.com/dmdukr/ai-polyglot-kit/issues)

---

# AI Polyglot Kit — Багатосервісний голосовий та перекладацький AI для Windows

Системний голосовий ввід, нормалізація тексту та переклад для Windows — 7 STT та 8+ LLM провайдерів з автоматичним перемиканням.

> Створено **dmdukr** за участі [Claude](https://claude.ai) (Anthropic) як AI-співавтора.

---

## Можливості

- **7 STT провайдерів** (6 з безкоштовним доступом) — Groq, Soniox, Deepgram, Gladia, Speechmatics, AssemblyAI + OpenAI (платний)
- **8+ LLM провайдерів** (7 з безкоштовним доступом) — Groq, Google AI Studio, Cerebras, Mistral, OpenRouter, xAI, GitHub Models + OpenAI (платний)
- **3 слоти з failover** — коли лімт провайдера #1 вичерпано → автопереключення на #2 → #3
- **Автовизначення провайдера** — вставте API ключ → програма визначить сервіс та завантажить доступні моделі
- **Два режими запису** — Утримання (тримайте клавішу для запису, відпустіть для зупинки) або Перемикач (натисніть для старту, ще раз для зупинки)
- **AI-нормалізація** — LLM виправляє помилки розпізнавання, прибирає слова-паразити, форматує текст
- **Швидкий переклад** — подвійний Ctrl+C на виділеному тексті → миттєвий переклад (DeepL або LLM)
- **Самонавчання** — вчиться з ваших виправлень через подвійний тап
- **Автооновлення** — перевіряє релізи на GitHub, завантажує та встановлює
- **Темна/Світла тема** — слідкує за темою Windows або ручний вибір

## Встановлення

1. Завантажте `AIPolyglotKit-setup.exe` з [Releases](https://github.com/dmdukr/ai-polyglot-kit/releases)
2. Запустіть інсталятор
3. Отримайте безкоштовні API ключі від одного або кількох провайдерів (див. [Гід по провайдерах](#stt-провайдери) нижче)
4. Натисніть іконку в треї → **Налаштування** → вставте ключі у вкладки STT, Нормалізація та Переклад

---

## STT провайдери

Провайдери розпізнавання мовлення. Додайте до 3-х у Налаштування → STT.

*Дані станом на березень 2026*

| # | Провайдер | Модель | Безкоштовно | Мови | WER | Як отримати ключ |
|---|-----------|--------|-------------|------|-----|-----------------|
| 1 | **Groq** | Whisper Large V3 Turbo | **~8 год/день** (щоденне скидання) | 99+ | 0.16% | [console.groq.com](https://console.groq.com) → Sign Up → API Keys → Create |
| 2 | **Soniox** | stt-async-v4 | **$200 кредитів ≈ 2000 год** (одноразово) | 60+ | Топ бенчмарків | [soniox.com](https://soniox.com) → Sign Up → Dashboard → API Key |
| 3 | **Deepgram** | Nova-3 | **$200 кредитів ≈ 330 год** (одноразово) | 50+ | 0.14% | [console.deepgram.com](https://console.deepgram.com) → Sign Up → API Keys |
| 4 | **Gladia** | Solaria-1 | **10 год/місяць** + $50 кредитів | 100+ | 0.16% | [app.gladia.io](https://app.gladia.io) → Sign Up → API Key |
| 5 | **Speechmatics** | Enhanced (Ursa) | **8 год/місяць** | 50+ | 0.18% | [portal.speechmatics.com](https://portal.speechmatics.com) → Sign Up → API Key |
| 6 | **AssemblyAI** | Universal-2 | **8 год/місяць** | 99 | 0.20% | [assemblyai.com](https://www.assemblyai.com) → Sign Up → Dashboard → API Key |
| 7 | **OpenAI** | Whisper, GPT-4o-transcribe | **Немає безкоштовного** ($0.006/хв) | 99+ | 0.11% | [platform.openai.com](https://platform.openai.com) → API Keys |

### Який STT обрати?

- **Найкращий безкоштовний для щоденного використання**: **Groq** — 8 годин/день, щодня, без обмежень за часом
- **Найбільший одноразовий кредит**: **Soniox** (2000 год) або **Deepgram** (330 год)
- **Найкращий для змішаних мов (UK/RU/EN)**: **Groq Whisper V3** або **Soniox v4** (перемикання мов mid-sentence)
- **Найкраща абсолютна точність**: **OpenAI GPT-4o-transcribe** (тільки платний)

### Рекомендоване налаштування (безкоштовне)

| Слот | Провайдер | Чому |
|------|-----------|------|
| #1 | Groq | Найкращий щоденний ліміт (8 год/день) |
| #2 | Soniox | 2000 год запасу, відмінна мультимовність |
| #3 | Deepgram | 330 год запасу, точність Nova-3 |

---

## LLM провайдери

LLM провайдери для нормалізації тексту та перекладу. Додайте до 3-х у Налаштування → Нормалізація та Переклад.

Всі LLM провайдери використовують один формат API (OpenAI-сумісний) — просто вставте ключ, програма визначить сервіс автоматично.

*Дані станом на березень 2026*

| # | Провайдер | Найкраща безкоштовна модель | Безкоштовно | Префікс ключа | Як отримати |
|---|-----------|---------------------------|-------------|---------------|------------|
| 1 | **Groq** | Llama 3.3 70B | **1K запитів/день, 100K токенів/день** | `gsk_` | [console.groq.com](https://console.groq.com) → API Keys |
| 2 | **Google AI Studio** | Gemini 2.5 Flash | **250 запитів/день, 250K токенів/хв** | `AIzaSy` | [aistudio.google.com](https://aistudio.google.com) → Get API Key |
| 3 | **Cerebras** | Llama 3.3 70B | **~1M токенів/день** | `csk-` | [cloud.cerebras.ai](https://cloud.cerebras.ai) → Sign Up → API Key |
| 4 | **Mistral** | Mistral Small 4 | **~1B токенів/місяць** | hex рядок | [console.mistral.ai](https://console.mistral.ai) → API Keys |
| 5 | **OpenRouter** | DeepSeek R1, Llama 4 | **50 запитів/день** | `sk-or-` | [openrouter.ai](https://openrouter.ai) → Keys |
| 6 | **xAI** | Grok 4 | **$25 кредитів** (одноразово) | `xai-` | [console.x.ai](https://console.x.ai) → API Keys |
| 7 | **GitHub Models** | GPT-4o, o3 | **50-150 запитів/день** | `ghp_` | [github.com/settings/tokens](https://github.com/settings/tokens) |
| 8 | **OpenAI** | GPT-4o-mini | **Немає безкоштовного** | `sk-` | [platform.openai.com](https://platform.openai.com) → API Keys |

### Який LLM обрати?

- **Найкращий для нормалізації**: **Groq** (Llama 3.3 70B, швидкий, гарна мультимовність)
- **Найщедріший безкоштовний**: **Google AI Studio** (Gemini 2.5 Flash, 250K токенів/хв)
- **Найшвидший**: **Groq** (300+ ток/с) або **Cerebras** (2000+ ток/с)

### Рекомендоване налаштування (безкоштовне)

| Слот | Провайдер | Чому |
|------|-----------|------|
| #1 | Groq | Швидкий, Llama 3.3 70B, той самий ключ що й для STT |
| #2 | Google AI Studio | Щедрі ліміти, сильна мультимовність |
| #3 | Cerebras | Ультрашвидкий запасний |

---

## Провайдери перекладу

Переклад використовує ті самі LLM слоти (3 провайдери) плюс опціональні ключі DeepL для вищої якості.

| Провайдер | Безкоштовно | Якість | Як отримати |
|-----------|-------------|--------|------------|
| **DeepL** | **500K символів/місяць** на ключ | Найкраща якість перекладу | [deepl.com/pro](https://www.deepl.com/pro) → API → Free |
| **Будь-який LLM** | Як у таблиці LLM вище | Добра, контекстна | Ті самі ключі |

---

## Використання

| Дія | Як |
|-----|-----|
| **Запис** | Утримуйте гарячу клавішу (за замовч.: `F12`) → говоріть → відпустіть |
| **Переклад** | Виділіть текст → Ctrl+C двічі швидко → вікно перекладу |
| **Зворотній зв'язок** | Після диктування відредагуйте текст, потім двічі натисніть гарячу клавішу |
| **Налаштування** | Натисніть іконку в треї → Налаштування |
| **Вихід** | Правий клік на іконку → Вихід |

## Вкладки налаштувань

| Вкладка | Що там |
|---------|--------|
| **Інтерфейс** | Звуки, сповіщення, автозапуск, мова, тема, телеметрія |
| **STT** | 3 слоти провайдерів розпізнавання + вибір мов |
| **Диктування** | Гаряча клавіша, режим запису, мікрофон, фільтр шуму |
| **Нормалізація** | 3 слоти LLM провайдерів + перемикач нормалізації |
| **Переклад** | 3 слоти LLM провайдерів + ключі DeepL |

## Повідомлення про помилки

Знайшли баг? [Відкрийте issue](https://github.com/dmdukr/ai-polyglot-kit/issues)

---

## Privacy Policy

AI Polyglot Kit collects **anonymous usage statistics** (can be disabled in Settings → Interface → Telemetry).

**Collected**: session count, latency, model names, hallucination rates, app/OS version.
**NOT collected**: audio, text, API keys, personal information.

Data destination: [Amplitude](https://amplitude.com) analytics. No data sold or shared.

---

## License

[GNU GPL v3](LICENSE) — Copyright (c) 2026 Dmytro Dubinko
