# VFS Visa Slot Checker Bot 🇫🇷

Автоматизированный бот для мониторинга свободных слотов записи на подачу визы во Францию через VFS Global.

## Возможности

- 🔄 **Автоматический мониторинг** - проверка слотов 24/7 с настраиваемым интервалом
- 📱 **Telegram уведомления** - мгновенные оповещения при появлении свободных слотов
- 📧 **Email уведомления** - дополнительный канал оповещений (опционально)
- 🛡️ **Антибот защита** - имитация поведения реального пользователя
- 🔐 **CAPTCHA** - детекция и интеграция с сервисами решения
- 📊 **Логирование** - подробные логи всех действий
- 🐳 **Docker** - готовая контейнеризация для простого деплоя

## Поддерживаемые визовые центры

- Москва
- Нижний Новгород
- (легко расширяется на другие города)

## Быстрый старт

### 1. Клонирование репозитория

```bash
git clone <repository-url>
cd visa_bot
```

### 2. Установка зависимостей

```bash
# Создайте виртуальное окружение
python -m venv venv
source venv/bin/activate  # Linux/Mac
# или
venv\Scripts\activate  # Windows

# Установите зависимости
pip install -r requirements.txt

# Установите браузер Playwright
playwright install chromium
```

### 3. Настройка конфигурации

```bash
# Скопируйте примеры конфигов
cp config/config.yaml.example config/config.yaml
cp .env.example .env

# Отредактируйте .env файл
nano .env
```

Заполните `.env`:
```env
VFS_EMAIL=your_email@example.com
VFS_PASSWORD=your_password
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

### 4. Настройка Telegram бота

1. Создайте бота через [@BotFather](https://t.me/BotFather)
2. Получите токен бота
3. Узнайте ваш chat_id через [@userinfobot](https://t.me/userinfobot)
4. Добавьте данные в `.env`

### 5. Запуск бота

```bash
# Обычный запуск
python -m src.main

# С отладочным выводом
python -m src.main --debug

# Тест Telegram подключения
python -m src.main --test-telegram

# Проверка конфигурации
python -m src.main --validate-config

# Одиночная проверка (без цикла)
python -m src.main --single-check
```

## Запуск через Docker

### Сборка и запуск

```bash
cd docker

# Сборка образа
docker-compose build

# Запуск в фоне
docker-compose up -d

# Просмотр логов
docker-compose logs -f

# Остановка
docker-compose down
```

### Переменные окружения для Docker

Создайте файл `.env` в папке `docker/`:

```env
VFS_EMAIL=your_email@example.com
VFS_PASSWORD=your_password
TELEGRAM_BOT_TOKEN=your_token
TELEGRAM_CHAT_ID=your_chat_id
```

## Конфигурация

### Основной конфиг (config/config.yaml)

```yaml
# Режим работы
mode: "prod"  # "debug" для отладки

# Настройки VFS
vfs:
  country_code: "rus"        # Страна подачи
  destination_country: "fra" # Страна назначения
  visa_type: "short_stay"    # Тип визы
  centers:                   # Визовые центры для мониторинга
    - "Nizhny Novgorod"
    - "Moscow"

# Расписание проверок
schedule:
  min_interval: 60    # Мин. интервал (секунды)
  max_interval: 300   # Макс. интервал (секунды)
  randomize: true     # Рандомизация интервала

# Настройки браузера
browser:
  headless: false     # true для безголового режима
  type: "chromium"    # chromium, firefox, webkit

# Антибот защита
antibot:
  stealth_mode: true
  mouse_movements: true
  random_scroll: true
```

### Описание параметров

| Параметр | Описание | По умолчанию |
|----------|----------|--------------|
| `mode` | Режим работы (debug/prod) | prod |
| `vfs.country_code` | Код страны подачи | rus |
| `vfs.destination_country` | Код страны назначения | fra |
| `vfs.centers` | Список визовых центров | ["Moscow"] |
| `schedule.min_interval` | Мин. интервал проверки (сек) | 60 |
| `schedule.max_interval` | Макс. интервал проверки (сек) | 300 |
| `browser.headless` | Безголовый режим | false |
| `telegram.enabled` | Telegram уведомления | true |

## Структура проекта

```
visa_bot/
├── src/
│   ├── __init__.py
│   ├── main.py              # Точка входа
│   ├── bot.py               # Основная логика бота
│   ├── browser.py           # Управление браузером
│   ├── vfs_navigator.py     # Навигация по VFS
│   ├── notifications/
│   │   ├── telegram.py      # Telegram уведомления
│   │   └── email.py         # Email уведомления
│   ├── captcha/
│   │   └── solver.py        # Решение CAPTCHA
│   ├── antibot/
│   │   └── stealth.py       # Антибот механизмы
│   └── utils/
│       ├── config.py        # Конфигурация
│       └── logger.py        # Логирование
├── config/
│   └── config.yaml.example
├── docker/
│   ├── Dockerfile
│   └── docker-compose.yml
├── logs/                    # Логи
├── requirements.txt
├── .env.example
└── README.md
```

## Уведомления

### Telegram

При обнаружении свободного слота бот отправит сообщение:

```
🎉 СВОБОДНЫЙ СЛОТ НАЙДЕН!

📍 Визовый центр: Moscow
📅 Дата: 2024-02-15

⏰ Доступные слоты:
  • 09:00
  • 10:30
  • 14:00

🔗 Ссылка для записи:
https://visa.vfsglobal.com/...

⚡️ Срочно бронируйте!
```

### Типы уведомлений

- `slot_available` - найден свободный слот
- `error` - произошла ошибка
- `captcha` - обнаружена CAPTCHA
- `daily_status` - ежедневный статус работы

## CAPTCHA

### Автоматическое решение

Бот поддерживает интеграцию с сервисами решения CAPTCHA:

- [2Captcha](https://2captcha.com/)
- [Anti-Captcha](https://anti-captcha.com/)

Настройка в `config.yaml`:

```yaml
captcha:
  auto_solve: true
  service: "2captcha"
  api_key: "${CAPTCHA_API_KEY}"  # В .env файле
```

### Без автоматического решения

Если CAPTCHA обнаружена и автоматическое решение отключено:
1. Бот отправит уведомление в Telegram
2. Приостановит работу
3. Автоматически повторит попытку через время

## Антибот защита

Бот использует множество техник для избежания детекции:

- **Stealth Mode** - скрытие признаков автоматизации
- **User-Agent Rotation** - смена идентификатора браузера
- **Human-like Behavior** - имитация человеческого поведения:
  - Случайные задержки между действиями
  - Движения мыши по кривым Безье
  - Случайный скроллинг
  - Реалистичная скорость ввода текста

## Обработка ошибок

- **Автоматический перезапуск** при критических ошибках
- **Экспоненциальный откат** при повторных ошибках
- **Пауза** после N последовательных ошибок
- **Уведомления** о проблемах в Telegram

## Логирование

Логи сохраняются в папку `logs/`:

```
2024-01-15 10:30:45 | INFO     | [Bot] Starting check for Moscow
2024-01-15 10:30:48 | INFO     | [VFS] Login successful
2024-01-15 10:30:52 | INFO     | [VFS] [NO SLOTS] Center: Moscow
2024-01-15 10:30:52 | INFO     | [Bot] Waiting 180s until next check
```

## Деплой на сервер

### VPS/VDS

1. Арендуйте сервер (рекомендуется Ubuntu 22.04)
2. Установите Docker и Docker Compose
3. Склонируйте репозиторий
4. Настройте конфигурацию
5. Запустите через docker-compose

### Рекомендации

- **RAM**: минимум 1GB (рекомендуется 2GB)
- **CPU**: 1-2 ядра
- **Диск**: 5GB+
- **ОС**: Ubuntu 22.04 / Debian 12

### Автозапуск

Для автоматического запуска при перезагрузке сервера:

```bash
# В docker-compose уже настроен restart: unless-stopped

# Или создайте systemd сервис
sudo nano /etc/systemd/system/visa-bot.service
```

```ini
[Unit]
Description=VFS Visa Slot Checker Bot
After=docker.service
Requires=docker.service

[Service]
WorkingDirectory=/path/to/visa_bot/docker
ExecStart=/usr/bin/docker-compose up
ExecStop=/usr/bin/docker-compose down
Restart=always

[Install]
WantedBy=multi-user.target
```

## Ограничения

- ⚠️ Бот **НЕ бронирует** слоты автоматически, только уведомляет
- ⚠️ Используйте на свой страх и риск
- ⚠️ Соблюдайте ToS VFS Global
- ⚠️ Не используйте агрессивные интервалы проверки

## Troubleshooting

### Бот не может залогиниться

1. Проверьте правильность email/пароля
2. Попробуйте залогиниться вручную на сайте
3. Возможно, требуется смена IP (используйте VPN/прокси)

### CAPTCHA появляется постоянно

1. Увеличьте интервал проверки
2. Используйте прокси
3. Включите автоматическое решение CAPTCHA

### Telegram уведомления не приходят

```bash
# Проверьте подключение
python -m src.main --test-telegram
```

### Браузер не запускается

```bash
# Переустановите Playwright
playwright install chromium --with-deps
```

## Разработка

### Запуск тестов

```bash
# TODO: Добавить тесты
pytest tests/
```

### Линтинг

```bash
pip install ruff
ruff check src/
```

## Лицензия

MIT License - используйте свободно для личных целей.

## Disclaimer

Этот инструмент предназначен исключительно для личного использования. Автор не несет ответственности за любые последствия использования данного ПО. Используйте ответственно и в соответствии с правилами VFS Global.

---

**Удачной записи на визу!** 🍀
