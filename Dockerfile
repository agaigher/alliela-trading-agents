FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /build
COPY . .
RUN pip install --no-cache-dir .

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

RUN useradd --create-home appuser \
 && install -d -m 0755 -o appuser -g appuser /home/appuser/.tradingagents
USER appuser
WORKDIR /home/appuser/app

COPY --from=builder --chown=appuser:appuser /build .

# The upstream CLI was removed when vendored into Alliela. The framework is
# meant to be imported as a library — build your own driver (FastAPI shim,
# Celery worker, etc.) and override the default below in a downstream image.
# As a sanity-check default, runs the example script at trading-agents/main.py:
#   docker run --rm -it <image>
ENTRYPOINT ["python"]
CMD ["main.py"]
