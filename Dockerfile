# ---------- Стадия 1: сборка колёс ----------
# mysqlclient — C-расширение: для сборки нужен компилятор и заголовки клиента MySQL.
# Эти пакеты тяжёлые (~250 МБ), поэтому собираем в отдельной стадии и в финальный
# образ не берём: туда попадут только готовые .whl.
FROM python:3.14-slim AS builder

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential pkg-config default-libmysqlclient-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
# Сначала копируем только requirements.txt: пока зависимости не менялись, Docker берёт
# этот слой из кэша, и пересборка после правки кода занимает секунды, а не минуты.
COPY requirements.txt .
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt


# ---------- Стадия 2: итоговый образ ----------
FROM python:3.14-slim

# Только РАНТАЙМ-библиотека клиента MySQL (без компилятора и заголовков).
RUN apt-get update \
    && apt-get install -y --no-install-recommends libmariadb3 \
    && rm -rf /var/lib/apt/lists/*

# PYTHONDONTWRITEBYTECODE: не плодить .pyc в образе.
# PYTHONUNBUFFERED: логи сразу в stdout, чтобы их видел `docker compose logs`.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Непривилегированный пользователь: если приложение взломают, у атакующего не будет
# прав root внутри контейнера.
RUN useradd --create-home --uid 1000 app

WORKDIR /app

COPY --from=builder /wheels /wheels
COPY requirements.txt .
# --no-index: ставим строго из собранных колёс, без обращения к интернету.
RUN pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.txt \
    && rm -rf /wheels

COPY --chown=app:app . .

# Каталог для collectstatic должен принадлежать app: иначе команда запуска упадёт с Permission denied.
RUN mkdir -p /app/staticfiles && chown app:app /app/staticfiles

USER app

EXPOSE 8000

# Порядок: миграции -> статика -> сервер.
# `&&` останавливает цепочку при первой ошибке: если migrate упал, gunicorn не стартует
# с неготовой базой. `exec` заменяет оболочку процессом gunicorn, чтобы он получал
# сигналы остановки (docker stop) напрямую и завершался корректно.
CMD ["sh", "-c", "python manage.py migrate --noinput && python manage.py collectstatic --noinput && exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 3"]
