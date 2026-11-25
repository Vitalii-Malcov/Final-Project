# Rental Housing API

Back-end приложения для аренды жилья (финальный проект курса Python Backend Developer).
Объявления, поиск и фильтрация, регистрация с ролями, бронирование, отзывы и рейтинги,
история поиска и просмотров. Упаковано в Docker, запускается одной командой.

## Стек

Python 3.14, Django 6.1, Django REST Framework, SimpleJWT (JWT + blacklist), MySQL 8.4,
django-environ, gunicorn, WhiteNoise, Docker / docker-compose.

> Ответы API (ошибки, сообщения) — на английском, комментарии в коде — на русском.

## Структура проекта

```
config/                 settings.py, urls.py (admin/ и api/v1/), wsgi.py
apps/
  routers.py            все маршруты API в одном месте
  core/                 абстрактные модели (UUIDv7, timestamps), пагинация, права доступа,
                        JWT-middleware, JSON-обработчики 404/500. Своих таблиц нет
  users/                модель User (вход по email), роли, регистрация/login/logout/me
  listings/             объявления, поиск и фильтры, просмотры, история поиска
  bookings/             бронирование, подтверждение, отмена
  reviews/              отзывы и рейтинги
Dockerfile, docker-compose.yml, .env.example, requirements.txt
```

В каждом приложении: `models`, `serializers`, `views`, `urls`, `admin`, `tests`.
Views написаны на `APIView` и generic-классах DRF (не ViewSet).

## База данных (MySQL)

Первичные ключи везде UUID версии 7 (растут со временем, удобны для индексов InnoDB).

| Таблица | Назначение | Ключевое |
|---|---|---|
| `users` | пользователи | `email` уникален, роли — группы Django (`groups`), пароль хранится хешем |
| `listings` | объявления | FK `owner`; индекс по `city`; составные `(is_active, price)`, `(is_active, rooms)`; индекс `housing_type`; цена `DECIMAL(10,2)` |
| `listing_views` | один просмотр = одна строка | FK `listing`, FK `user` (NULL у анонимов, SET_NULL) |
| `search_history` | одно ключевое слово = одна строка | индекс по `keyword`, FK `user` (NULL) |
| `bookings` | брони | FK `listing`, `tenant`; `total_price` фиксируется при создании; `CHECK (end_date > start_date)` |
| `reviews` | отзывы | FK `listing`, `author`; `UNIQUE (listing, author)`; `CHECK (rating BETWEEN 1 AND 5)`; OneToOne `booking` |

Статистика объявления (`views_count`, `reviews_count`, `avg_rating`) не хранится, а считается
подзапросами (`Listing.objects.with_stats()`). Подзапросы, а не JOIN, чтобы счётчики просмотров
и отзывов не умножались друг на друга. Без отзывов `avg_rating = null`.

## Роли и права

Роль — это стандартная группа `django.contrib.auth.models.Group` (`tenant`, `landlord`), а права —
стандартные model permissions, выданные группам. Пользователь может состоять **в обеих группах**:
арендодатель, который тоже снимает жильё, не нуждается во втором аккаунте.

| Группа | Права | Что даёт |
|---|---|---|
| `landlord` | `listings.add_listing`, `listings.change_listing`, `listings.delete_listing`, `bookings.change_booking` | создавать, править, удалять и скрывать свои объявления; смотреть заявки, подтверждать и отклонять |
| `tenant` | `bookings.add_booking`, `reviews.add_review` | бронировать, отменять и смотреть свои брони; писать отзывы |

Группы и права создаёт миграция `users/0002_create_role_groups` (она сама создаёт model permissions
нужных приложений, потому что штатный сигнал `post_migrate` срабатывает позже всех миграций, а на чистой
базе в этот момент прав ещё нет). Миграция `0003` перенесла старое поле `role` в группы, `0004` удалила поле.
Права можно менять в админке (Группы) без правки кода.

| Действие | Аноним | Нужное право | Дополнительно |
|---|:-:|---|---|
| Регистрация, вход, просмотр и поиск объявлений, отзывы (чтение) | ✔ | — | |
| Создать объявление | — | `listings.add_listing` | владелец берётся из токена |
| Править / удалить / скрыть объявление | — | `change_listing` / `delete_listing` / `change_listing` | только владелец объявления |
| Создать бронь, отменить свою, смотреть свои брони | — | `bookings.add_booking` | нельзя бронировать своё жильё (400) |
| Заявки на мои объявления, подтвердить / отклонить | — | `bookings.change_booking` | только владелец объявления |
| Написать отзыв | — | `reviews.add_review` | только после завершённого проживания |

Права проверяет `user.has_perm(...)` по базе данных, а не роль из токена: если администратор забрал право у группы,
это действует сразу, не дожидаясь окончания жизни access-токена. Суперпользователь проходит все проверки.
Роли в токене (`roles`) нужны только фронтенду для выбора интерфейса.

Роли при регистрации: поле `roles` (список), по умолчанию `["tenant"]`, можно `["tenant", "landlord"]`.
Добавить роль позже: `POST auth/me/roles/ {"role": "landlord"}` (повтор безопасен). Новые права
вступают в силу сразу, а `roles` в уже выданном токене обновится после refresh или нового входа.

## Защита маршрутов

Защита двухуровневая:

1. **Middleware** `apps.core.middleware.JWTProtectedRoutesMiddleware`: требует валидный access-токен
   на приватных путях (`auth/me/`, `auth/logout/`, `bookings/...`, `listings/my/`,
   `listings/searches/my/`) и на любой изменяющий запрос (POST/PUT/PATCH/DELETE) под `/api/v1/`.
   Публичны только `auth/register|login|refresh/`. Иначе ответ 401.
2. **permission_classes** (`apps/core/permissions.py`): `IsLandlord`, `IsTenant`, `CanManageBookings`,
   `IsLandlordOrReadOnly`, `IsTenantOrReadOnly`, `IsOwnerOrReadOnly`. Каждый проверяет конкретное
   право через `has_perm` (см. таблицу выше); `IsOwnerOrReadOnly` дополнительно проверяет владельца объекта.

JWT: access 30 минут, refresh 7 дней, с ротацией; старый refresh попадает в blacklist.
Пагинация: 10 на странице, `?page_size=` до 100.

## Эндпоинты `/api/v1/`

| Метод | URL | Кто | Описание |
|---|---|---|---|
| POST | `auth/register/` | все | регистрация (`re_password`, `roles`: по умолчанию `["tenant"]`) → 201 |
| POST | `auth/login/` | все | `access`, `refresh`, `user`; роли (`roles`) в payload токена |
| POST | `auth/refresh/` | все | новый access + новый refresh |
| POST | `auth/logout/` | авторизованный | refresh в blacklist → 204 |
| GET | `auth/me/` | авторизованный | текущий пользователь (`roles`) |
| POST | `auth/me/roles/` | авторизованный | добавить себе роль `{"role": "landlord"}`, идемпотентно → 200 |
| GET | `listings/` | все | активные объявления; фильтры ниже |
| POST | `listings/` | `add_listing` | создание, владелец берётся из токена |
| GET | `listings/<id>/` | все | карточка (неактивные видит только владелец); просмотр записывается |
| PUT/PATCH/DELETE | `listings/<id>/` | владелец + `change_` / `delete_listing` | удаление при будущих confirmed-бронях → 409 |
| PATCH | `listings/<id>/toggle-status/` | владелец + `change_listing` | переключить или `{"is_active": false}` |
| GET | `listings/my/` | `add_listing` | свои объявления, включая неактивные |
| GET | `listings/popular/` | все | по числу просмотров |
| GET | `listings/searches/popular/` | все | популярные запросы, `?limit=` (1–100) |
| GET | `listings/searches/my/` | авторизованный | своя история поиска |
| GET / POST | `listings/<id>/reviews/` | GET все, POST `add_review` | отзыв только после завершённого проживания, один на объявление |
| GET / POST | `bookings/` | `add_booking` | свои брони (`?state=active\|completed\|cancelled\|rejected`) / создать |
| GET | `bookings/<id>/` | арендатор или владелец жилья | |
| PATCH | `bookings/<id>/cancel/` | `add_booking`, своя бронь | pending/confirmed, не позже `start − N дней` |
| GET | `bookings/requests/` | `change_booking` | заявки на свои объявления, `?status=` |
| PATCH | `bookings/<id>/confirm/` | `change_booking`, владелец жилья | только pending |
| PATCH | `bookings/<id>/reject/` | `change_booking`, владелец жилья | только pending |

Фильтры `GET listings/`: `search` (все слова в заголовке или описании), `price_min`, `price_max`,
`city`, `district` (без учёта регистра, точное совпадение), `rooms_min`, `rooms_max`,
`housing_type` (через запятую: `apartment,house`), `ordering`: `price`, `created_at`, `views`,
`reviews`, `rating` (с `-` по убыванию; объявления без оценок всегда в конце).
Неверный параметр → 400 с описанием.

## Правила бронирования

- Даты не в прошлом, выезд позже заезда, не более 365 ночей, нельзя бронировать своё жильё.
- Периоды пересекаются, если `start1 < end2` и `end1 > start2`. День выезда одной брони и заезда
  другой могут совпадать.
- Новую бронь нельзя создать на даты, занятые подтверждённой (409), и на даты, пересекающиеся с
  собственной заявкой арендатора (409).
- `total_price` = цена за ночь × число ночей, фиксируется при создании.
- При подтверждении (`confirm`) в транзакции берётся блокировка строки объявления
  (`select_for_update`): два одновременных подтверждения пересекающихся заявок не могут оба
  пройти. Конфликт с подтверждённой бронью → 409, остальные пересекающиеся pending
  автоматически переводятся в rejected.
- Срок отмены: не позже `start_date − BOOKING_CANCELLATION_DEADLINE_DAYS` дней (из `.env`, по умолчанию 1).
- Коды ответов: некорректные данные → 400; данные верны, но состояние не позволяет действие → 409.

## Запуск локально (Windows, без Docker)

Нужны Python 3.14 и MySQL 8.4 (Django 6.1 не работает с MySQL 8.0).

```powershell
py -3.14 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env        # затем впишите свои значения
```

Создайте базу и пользователя (под root):

```sql
CREATE DATABASE rental_housing CHARACTER SET utf8mb4;
CREATE USER 'rental_user'@'localhost' IDENTIFIED BY '<пароль из .env>';
GRANT ALL PRIVILEGES ON rental_housing.* TO 'rental_user'@'localhost';
GRANT ALL PRIVILEGES ON `test\_rental_housing`.* TO 'rental_user'@'localhost';  -- для тестов
```

```powershell
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Для быстрой проверки без MySQL поставьте в `.env` `MYSQL=False` (будет SQLite).

> Если `django-admin.exe` блокируется политикой Windows, используйте `python -m django ...`.

## Запуск в Docker

```bash
cp .env.example .env     # заполните значения (см. ниже)
docker compose up -d --build
docker compose exec web python manage.py createsuperuser
```

API: `http://localhost:${WEB_PORT:-8000}/api/v1/`, админка: `/admin/`.

Что делает compose:
- `db` (mysql:8.4) с healthcheck и томом `mysql_data`. **Порт наружу не публикуется**: приложение
  обращается к базе по внутреннему имени `db`, поэтому не конфликтует с MySQL на хосте и не
  доступен из интернета.
- `web` стартует, только когда `db` прошла healthcheck. Команда запуска: `migrate` →
  `collectstatic` → `gunicorn`. Процесс идёт под непривилегированным пользователем.
- `MYSQL_HOST` внутри контейнера принудительно `db` (в `.env` может стоять `127.0.0.1` для локальной разработки).

Переменные `.env`:

| Переменная | Значение |
|---|---|
| `SECRET_KEY` | в **одинарных кавычках** (в ключе бывает `$`, иначе compose его исказит) |
| `DEBUG` | `False` на сервере |
| `ALLOWED_HOSTS` | через запятую: IP или домен сервера |
| `CSRF_TRUSTED_ORIGINS` | через запятую, со схемой: `http://203.0.113.10` |
| `MYSQL`, `MYSQL_DATABASE`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_HOST`, `MYSQL_PORT` | подключение к базе |
| `MYSQL_ROOT_PASSWORD` | root-пароль контейнера MySQL (только для Docker) |
| `BOOKING_CANCELLATION_DEADLINE_DAYS` | срок отмены брони, дней до заезда |
| `WEB_PORT` | порт приложения на хосте (по умолчанию 8000) |

Полезные команды: `docker compose logs -f web`, `docker compose down` (данные сохранятся),
`docker compose down -v` (**удалит данные БД**).

## Тесты

```powershell
python manage.py test
```

`APITestCase` в `tests.py` каждого приложения (195 тестов). Авторизация настоящим токеном
`AccessToken.for_user(user)` в заголовке, не `force_authenticate`: middleware проверяет заголовок
раньше DRF. Тесты идут на отдельную базу `test_rental_housing`. Есть тест реальной гонки на потоках
(одновременное подтверждение пересекающихся броней).

## Деплой на AWS EC2 (Ubuntu)

1. **Security Group**: входящие правила — SSH `22` только с вашего IP, HTTP `80` с `0.0.0.0/0`.
   Порты `3306` и `8000` **не открывайте**.
2. **Инстанс**: Ubuntu 24.04 LTS, тип от `t3.small` (для MySQL 8.4 и gunicorn `t3.micro` на пределе по памяти),
   диск от 20 ГБ, свой key pair (`.pem`).
3. **Elastic IP**: выделите и привяжите к инстансу, иначе публичный IP меняется при остановке.
4. Подключение и установка Docker:
   ```bash
   ssh -i key.pem ubuntu@<ELASTIC_IP>
   curl -fsSL https://get.docker.com | sudo sh
   sudo usermod -aG docker ubuntu && exit        # переподключитесь, чтобы группа применилась
   ```
5. Код и настройки:
   ```bash
   git clone <URL вашего репозитория> app && cd app
   cp .env.example .env && nano .env
   ```
   В `.env` задайте: `DEBUG=False`, свежий `SECRET_KEY` в одинарных кавычках, сложные
   `MYSQL_PASSWORD` и `MYSQL_ROOT_PASSWORD`, `ALLOWED_HOSTS=<ELASTIC_IP>`,
   `CSRF_TRUSTED_ORIGINS=http://<ELASTIC_IP>`, **`WEB_PORT=80`**.
6. Запуск:
   ```bash
   docker compose up -d --build
   docker compose exec web python manage.py createsuperuser
   ```
7. Проверка: `http://<ELASTIC_IP>/api/v1/listings/` должен вернуть JSON, `/admin/` — страницу входа.

Обновление версии: `git pull && docker compose up -d --build`.

## Типичные проблемы

| Симптом | Причина и решение |
|---|---|
| `Access denied` от web при втором запуске после смены `MYSQL_PASSWORD` | образ mysql применяет пароль только при создании тома. Верните старый пароль либо `docker compose down -v` (удалит данные) |
| `DisallowedHost` / 400 на сервере | IP или домен не указан в `ALLOWED_HOSTS` |
| 403 CSRF в админке | не указан `CSRF_TRUSTED_ORIGINS` (со схемой `http://`) |
| compose пишет `variable is not set` | в значении `.env` есть `$`; возьмите значение в одинарные кавычки |
| порт уже занят | поменяйте `WEB_PORT` в `.env` |
