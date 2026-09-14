# Асинхронная обработка изображений

Это тестовый сервис на aiohttp. API принимает картинку, создаёт задачу и
сразу возвращает её ID. Само изображение обрабатывает отдельный worker.

Исходный файл временно хранится на диске. PostgreSQL хранит задачи и готовые
JPEG-файлы, а Redis используется как очередь. Если загружен PNG или другой
формат, worker конвертирует его в JPEG. Также можно передать качество и новые
размеры изображения.

## Что здесь есть

- загрузка изображения;
- необязательные параметры quality, x и y;
- получение статуса задачи;
- получение готового JPEG по ID;
- изменение размера уже сохранённого изображения;
- получение параметров одного изображения;
- список изображений в JSON или CSV;
- чтение JSONL-логов через API;
- Bearer-авторизация;
- SQL-миграции без ORM и Alembic;
- unit-, API-интеграционные и полные интеграционные тесты.

## Стек

- Python 3.11;
- aiohttp;
- asyncpg и обычный SQL;
- PostgreSQL 14.1+;
- Redis;
- Pillow;
- Pydantic v2;
- Loguru;
- pytest и pytest-asyncio.

## Как устроен проект

~~~text
app/
├── api/          HTTP-ручки и проверка входных данных
├── db/           пул asyncpg, репозитории и миграции
├── middlewares/  авторизация, ошибки, request ID и логи
├── models/       Pydantic-модели
├── services/     основная логика API
├── storage/      временные файлы загрузок
├── task_queue/   очередь Redis
└── worker/       получение задач и обработка через Pillow
~~~

Цепочка загрузки выглядит так:

~~~text
POST /api/images
    -> проверка multipart
    -> временный файл
    -> запись tasks в PostgreSQL
    -> ID задачи в Redis
    -> worker
    -> JPEG и completed в одной транзакции
    -> удаление временного файла
~~~

В Redis лежит только ID задачи. Все параметры и статусы находятся в
PostgreSQL, поэтому база остаётся основным источником данных.

## Запуск на Ubuntu 22.04 или WSL

Если проект лежит на диске Windows, путь в WSL будет примерно таким:

~~~bash
cd "/mnt/c/Users/<имя_пользователя>/Desktop/test_task"
~~~

Windows-окружение venv в Ubuntu не работает. Для WSL нужно создать своё:

~~~bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip postgresql redis-server

python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
~~~

Запускаем PostgreSQL и Redis:

~~~bash
sudo service postgresql start
sudo service redis-server start
~~~

Создаём основную и тестовую базы. Эти команды нужны один раз:

~~~bash
sudo -u postgres psql -c "ALTER USER postgres WITH PASSWORD 'postgres';"
sudo -u postgres createdb image_service
sudo -u postgres createdb image_service_test
~~~

Если база уже существует, повторно создавать её не нужно.

Копируем настройки окружения:

~~~bash
cp .env.example .env
nano .env
~~~

Пример содержимого:

~~~env
POSTGRES_DSN=postgresql://postgres:postgres@localhost:5432/image_service
REDIS_DSN=redis://localhost:6379/0
BEARER_TOKEN=change-me-to-a-long-random-secret-token

TEST_POSTGRES_DSN=postgresql://postgres:postgres@localhost:5432/image_service_test
TEST_REDIS_DSN=redis://localhost:6379/15
~~~

Пароль PostgreSQL и токен нужно заменить на свои. Файл .env не должен
попадать в Git.

Обычные настройки находятся в config.cfg. Там можно изменить порт, лимиты
файла и изображения, размер пула БД, имя очереди, папку загрузок и параметры
логирования.

## Миграции

Проверить состояние миграций:

~~~bash
.venv/bin/python -m app.db.migrate status
~~~

Применить ещё не выполненные миграции:

~~~bash
.venv/bin/python -m app.db.migrate up
~~~

Мигратор читает SQL-файлы из app/db/migrations и записывает выполненные
версии в таблицу schema_migrations.

## Запуск API и worker

В первом терминале:

~~~bash
.venv/bin/python -m app.main
~~~

Во втором терминале:

~~~bash
.venv/bin/python -m app.worker.main
~~~

API будет доступно по адресу http://localhost:8080.

Для остановки достаточно нажать Ctrl+C в обоих терминалах.

## Проверка API вручную

Сначала зададим токен и путь к фотографии:

~~~bash
TOKEN='change-me-to-a-long-random-secret-token'
PHOTO='/mnt/c/Users/<имя_пользователя>/Pictures/photo.png'
~~~

Значение TOKEN должно совпадать с BEARER_TOKEN в .env.

### 1. Загрузка изображения

~~~bash
UPLOAD_RESPONSE=$(curl -sS -X POST http://localhost:8080/api/images \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@$PHOTO" \
  -F "quality=80" \
  -F "x=800" \
  -F "y=600")

echo "$UPLOAD_RESPONSE"
~~~

Пример ответа:

~~~json
{"task_id":"d5cb3e1c-89d1-4089-9d8d-928241da76f4","status":"pending"}
~~~

Параметры quality, x и y необязательны. Без них можно отправить только file.

Сохраним ID задачи без jq:

~~~bash
TASK_ID=$(
  printf '%s' "$UPLOAD_RESPONSE" |
  .venv/bin/python -c 'import json,sys; print(json.load(sys.stdin)["task_id"])'
)

echo "$TASK_ID"
~~~

### 2. Статус задачи

~~~bash
TASK_RESPONSE=$(curl -sS \
  -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8080/api/tasks/$TASK_ID")

echo "$TASK_RESPONSE"
~~~

Пока worker не закончил:

~~~json
{"task_id":"...","status":"pending"}
~~~

После обработки:

~~~json
{"task_id":"...","status":"completed","image_id":"..."}
~~~

При ошибке статус будет failed, а в поле error будет причина.

Получим ID готового изображения:

~~~bash
IMAGE_ID=$(
  printf '%s' "$TASK_RESPONSE" |
  .venv/bin/python -c 'import json,sys; print(json.load(sys.stdin)["image_id"])'
)

echo "$IMAGE_ID"
~~~

Если задача ещё не completed, повторите запрос статуса через секунду.

### 3. Скачать изображение

~~~bash
curl -sS \
  -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8080/api/images/$IMAGE_ID" \
  -o result.jpg

file result.jpg
~~~

### 4. Получить параметры изображения

~~~bash
curl -sS \
  -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8080/api/images/$IMAGE_ID/metadata"
~~~

Пример ответа:

~~~json
{
  "id": "...",
  "original_filename": "photo.png",
  "media_type": "image/jpeg",
  "width": 800,
  "height": 600,
  "size_bytes": 12345,
  "quality": 80,
  "created_at": "...",
  "updated_at": "..."
}
~~~

### 5. Список изображений в JSON

~~~bash
curl -sS \
  -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8080/api/images?format=json&limit=20&offset=0"
~~~

### 6. Список изображений в CSV

~~~bash
curl -sS \
  -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8080/api/images?format=csv&limit=20&offset=0" \
  -o images.csv

head images.csv
~~~

### 7. Изменить размер сохранённого изображения

~~~bash
RESIZE_RESPONSE=$(curl -sS -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"image_id\": \"$IMAGE_ID\",
    \"width\": 320,
    \"height\": 240
  }" \
  http://localhost:8080/api/images/resize)

echo "$RESIZE_RESPONSE"
~~~

Ответ снова содержит task_id. Его можно проверить через
GET /api/tasks/{task_id}. Resize обновляет существующую запись изображения,
поэтому ID изображения не меняется.

### 8. Прочитать последние логи

~~~bash
curl -sS \
  -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8080/api/logs?limit=20"
~~~

По умолчанию файл находится в logs/application.jsonl. Каждая строка — это
отдельный JSON-объект с request_id, IP, endpoint, методом, параметрами,
статусом и traceback при ошибке.

## Тесты

Запустить все тесты:

~~~bash
.venv/bin/python -m pytest
~~~

Если TEST_POSTGRES_DSN и TEST_REDIS_DSN заданы, вместе с остальными тестами
запустится полная цепочка с настоящими PostgreSQL и Redis:

~~~text
upload -> worker -> status -> metadata -> получение JPEG
~~~

Тест создаёт временную схему PostgreSQL и отдельные имена очередей Redis.
После выполнения он убирает свои данные. Если тестовые DSN не заданы, этот
сценарий будет пропущен.

Запустить только полную цепочку:

~~~bash
.venv/bin/python -m pytest \
  tests/integration/test_real_pipeline.py -q
~~~

## Статусы задач

- pending — задача создана и ждёт worker;
- processing — worker забрал задачу;
- completed — JPEG сохранён;
- failed — обработка закончилась ошибкой.

Worker подтверждает сообщение Redis только после завершения задачи и
удаления временного файла. При временной ошибке Redis подтверждение
повторяется. Если исходный файл не удалось удалить, задача доставляется ещё
раз только для повторной очистки.

Текущая очередь рассчитана на один процесс worker.
Для нескольких worker лучше использовать отдельный
processing-список на каждый процесс или Redis Streams.
