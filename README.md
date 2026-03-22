# ⚡ APEX PROTOCOL™ — Trading System

**Core 02** | 129.212.222.60 | Alex Sohokon | Montenegro | 2026

## Архитектура
Scanner → Strategy Engine → Signal Gate → Risk Manager → Execution Engine → Position Manager → Finalizer

## Структура
- `core/` — оркестратор, менеджеры времени, состояния, событий
- `modules/` — торговые модули
- `pipelines/` — торговый пайплайн
- `tables/` — data layer (SQLite)
- `storage/` — база данных, стратегии, конфиги
- `config/` — конфигурационные файлы
- `logs/` — системные логи
- `services/` — биржевой, временной, уведомительный сервисы
- `run/` — точки запуска
