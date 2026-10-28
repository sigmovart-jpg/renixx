# Renixx — Project AGENTS.md

## Обзор проекта

Renixx — интерпретируемый динамически типизированный язык программирования (расширение `.rn`).
Реализован на Python 3.9+. Репозиторий: https://github.com/sigmovart-jpg/renixx

## Структура

```
renixx/
├── src/renixx/          # Исходный код языка (пакет renixx)
│   ├── lexer.py         # Токенизатор
│   ├── parser.py        # Рекурсивный нисходящий парсер
│   ├── ast.py           # AST-узлы (dataclasses)
│   ├── interpreter.py   # Tree-walking интерпретатор
│   ├── environment.py   # Области видимости
│   ├── errors.py        # Типы ошибок (LexError, ParseError, RuntimeError)
│   ├── formatter.py     # Pretty-printer
│   ├── lsp.py           # LSP-сервер (JSON-RPC over stdio)
│   ├── semantics.py     # Семантический анализ (scope, undefined vars, types)
│   ├── cli.py           # CLI (run, repl, check, fmt, lsp, version)
│   ├── __main__.py      # Точка входа для python -m renixx
│   └── stdlib/          # Стандартная библиотека (Python-модули)
├── tests/               # pytest-тесты (test_basic.py, test_lsp.py)
├── examples/            # Примеры программ (.rn)
├── docs/                # SPEC.md, GRAMMAR.ebnf, TUTORIAL.md
├── playground/          # Веб-плейграунд (Pyodide)
├── vscode-renixx/       # VS Code расширение
├── tools/               # Лаунчеры (renixx, renixx.cmd)
├── pyproject.toml       # Конфигурация проекта и entry points
└── AGENTS.md            # Этот файл
```

## Команды сборки и тестов

### Установка (editable)
```bash
cd "C:\Users\Ryzen\Downloads\Новая папка\renixx"
pip install -e .
```

### Запуск тестов
```bash
python -m pytest -q
```
Ожидаемый результат: 55 passed (24 базовых + 31 LSP).

### Компиляция
```bash
python -m compileall -q src
```

### Запуск LSP-сервера (для ручной проверки)
```bash
# Вариант 1: без установки пакета
$env:PYTHONPATH = "src"
python -m renixx lsp

# Вариант 2: после pip install -e .
python -m renixx lsp
```

### CLI
```bash
python -m renixx run examples/fibonacci.rn
python -m renixx repl
python -m renixx check examples/fibonacci.rn
python -m renixx fmt examples/fibonacci.rn
python -m renixx version
```

### Сборка VS Code расширения
```bash
cd vscode-renixx
npm install
vsce package
```

## Важные замечания
- Пакет `renixx` **не установлен** по умолчанию в Python. Для работы LSP и CLI используйте `PYTHONPATH=src` или `pip install -e .`.
- Тесты LSP запускают сервер как subprocess (`python -m renixx lsp`) и общаются по JSON-RPC через stdin/stdout.
- Файл `vscode-renixx/extension.js` имеет незакоммиченные изменения (аудит LSP: проверки Python/renixx, output channel, error handling, restart on crash). Не перезаписывайте без согласования.
- Ветка `main` — основная. Не работайте напрямую в `main` при параллельной работе с GitHub Copilot Agent; используйте feature-ветки и PR.
- Git remote содержит токен в URL (локально, в `.git/config`). Не коммитьте `.git/config`.

## Архитектура языка
- Парсер: рекурсивный нисходящий, NEWLINE как терминатор операторов.
- Интерпретатор: tree-walking, лексическая область видимости.
- Типы: nil, bool, int, float, string, list, dict, function, class, instance.
- Модули: math, random, time, json, os, fs, re, http, collections.

## Конвенции
- Код на Python, стиль PEP 8.
- Тесты в `tests/` (pytest).
- Примеры в `examples/` (файлы `.rn`).
- Документация в `docs/` (SPEC.md, GRAMMAR.ebnf, TUTORIAL.md).
- Не добавляйте новые функции без тестов.

---

## Agent Automation (OpenCode ↔ Copilot)

### Инструменты
- `python tools/agent.py task "описание"` — создать задачу
- `python tools/agent.py run` — запустить OpenCode на pending-задачах
- `python tools/agent.py fix` — применить исправления из ревью
- `python tools/agent.py cycle` — полный цикл (run → review → fix)
- `python tools/agent.py status` — показать статус
- `python tools/agent.py lock/unlock` — блокировка параллельной обработки

### Протокол
- Задачи: `.agent/tasks/TASK-XXX.md`
- Ревью: `.agent/reviews/REVIEW-XXX.md`
- Статус: `.agent/status.json`
- Передача: `.agent/handoff.md`
- Решения: `.agent/decisions.md`
- Шаблоны: `.agent/templates/`

### VS Code задачи
`.vscode/tasks.json` содержит задачи для запуска через Ctrl+Shift+P → "Run Task".

### Copilot интеграция
- `.github/copilot-instructions.md` — инструкции для Copilot (роль ревьюера)
- `.github/prompts/review-task.prompt.md` — промпт для ревью задачи

### Ограничения
- Copilot нельзя запускать автономно — ревью запускается вручную в VS Code Copilot Chat
- OpenCode запускается автоматически через `agent.py run`
- Не коммитить/пушить без разрешения пользователя

---

## Agent Collaboration Protocol

### Роли по умолчанию

- **Пользователь** — выбирает задачи, утверждает рискованные действия, принимает финальный результат.
- **OpenCode** — основной исполнитель: реализация, тесты, исправления по ревью.
- **GitHub Copilot Agent** — независимый ревьюер: анализ diff, поиск ошибок, запись замечаний и предложений.

Роли могут меняться, если это явно указано в задаче или согласовано с пользователем.

### Рабочий цикл

1. **Прочитать контекст** — AGENTS.md, `.agent/status.json`, текущую задачу (`.agent/tasks/TASK-XXX.md`).
2. **Проверить Git status** перед работой. Убедиться, что рабочее дерево чистое или изменения понятны.
3. **Уточнить владельца задачи** и затрагиваемые файлы. Проверить, что никто другой не работает над теми же файлами.
4. **Реализовать задачу** в согласованной области (ветка `feature/xxx`).
5. **Записать результаты** — что сделано, какие файлы изменены, какие тесты добавлены.
6. **Передать на ревью** — создать `.agent/reviews/REVIEW-XXX.md`, обновить статус на `review`.
7. **Исправить подтверждённые замечания** и повторно проверить тесты.
8. **Завершить задачу** — обновить статус на `done`, записать результат в handoff.md. Только после успешного прохождения всех проверок.

### Защита от конфликтов

- **Не редактировать файл**, который сейчас изменяет другой агент, без явной передачи контроля.
- **Не перезаписывать** чужие изменения и результаты ревью. Дописывать, а не заменять.
- **При неизвестном состоянии или конфликте** — остановиться и запросить решение пользователя. Не пытаться разрешить автоматически.
- **Не переключать ветки, не коммитить, не пушить и не создавать PR** без отдельного разрешения пользователя.
- **Раздельные ветки сами по себе не синхронизируют файлы.** Учитывать состояние рабочей копии и Git. Перед началом работы всегда проверять `git status`.

### Соглашения для .agent/status.json

Допустимые значения поля `status`:
- `idle` — нет активной задачи
- `in-progress` — задача в работе
- `review` — задача на ревью
- `changes-requested` — ревьюер запросил изменения
- `done` — задача завершена и проверена
- `blocked` — задача заблокирована (нужна информация или решение)

Обязательные поля:
- `version` — версия схемы (сейчас 1)
- `current_task` — ID задачи или null
- `assigned_to` — opencode | copilot | human | null
- `branch` — имя ветки или null
- `last_updated` — ISO 8601 timestamp или null
- `last_action` — краткое описание последнего действия или null
- `status` — одно из допустимых значений

### Соглашения для .agent/handoff.md

При передаче задачи от одного агента другому заполняются поля:
- **От кого:** имя агента (opencode / copilot / human)
- **Кому:** имя агента-получателя
- **Дата:** ISO 8601
- **Что сделано:** краткое описание выполненной работы
- **Что нужно сделать дальше:** конкретное следующее действие
- **Ветка:** имя ветки
- **Файлы, которые трогали:** список файлов
- **Тесты:** результаты тестов (сколько прошло/провалилось)

### Правила обмена

1. **Задачи** создаются в `.agent/tasks/TASK-XXX.md` по шаблону `.agent/templates/TASK-TEMPLATE.md`.
2. **Ревью** создаются в `.agent/reviews/REVIEW-XXX.md` по шаблону `.agent/templates/REVIEW-TEMPLATE.md`.
3. **Не заявлять об автоматическом уведомлении** второго агента. Агенты не могут вызывать друг друга — обмен только через файлы и Git.
4. **Не объявлять задачу done**, если проверки (тесты, ревью) не выполнены и не зафиксированы.
5. **Не перезаписывать** результаты ревью или чужие заметки — дописывать в конец или создавать новый файл.
6. **При неизвестном состоянии** — остановиться и запросить решение пользователя, а не пытаться разрешить автоматически.