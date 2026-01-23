# corpTGbot

## Admin-панель

- Порт по умолчанию: `80`
- URL: `http://localhost/admin`
- Авторизация: сессия (пароль из `TG_DASHBOARD_PASSWORD`), страница входа `http://localhost/admin/login`
- Управление сессиями: `http://localhost/admin/sessions`

## Конфигурация портов

- `TG_DASHBOARD_LISTEN_PORT` — порт, на котором приложение слушает внутри контейнера (по умолчанию `80`).
- `TG_DASHBOARD_PORT` — порт публикации на хосте (по умолчанию `80`).

Если порт `80` занят другим сервисом, освободите его или временно поменяйте `TG_DASHBOARD_PORT` на свободный порт.

## Политика повторной аутентификации

- `TG_ADMIN_SESSION_MAX_AGE_SECONDS` — максимальная длительность сессии.
- `TG_ADMIN_SESSION_IDLE_SECONDS` — таймаут бездействия, после которого нужно войти заново.

## Логирование ZTNet

При наличии `ZT_NETWORK_ID` приложение периодически проверяет статус подключения ZeroTier внутри контейнера и пишет в stdout/file лог строки вида:

- `zt_monitor_start network_id=...`
- `zt_status network_id=... node_id=... status=OK msg=подключение установлено ips=...`

При проблемах статус логируется на `WARNING`/`ERROR` (например, `ACCESS_DENIED`).
