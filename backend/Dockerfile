FROM python:3.14-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Update OS packages to the latest security patches
RUN apt-get update \
    && apt-get upgrade -y \
    && rm -rf /var/lib/apt/lists/*

# Copy the project into the image
COPY . /app

# Disable development dependencies
ENV UV_NO_DEV=1

# Sync dependencies and remove pre-installed packaging tools containing vendored CVEs
RUN uv sync --locked && \
    rm -rf /usr/local/lib/python3.14/ensurepip \
           /usr/local/lib/python3.14/site-packages/pip*

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "rosalind.adapters.inbound.http.app:app", "--host", "0.0.0.0", "--port", "8000"]