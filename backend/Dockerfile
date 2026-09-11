FROM python:3.14-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Copy the project into the image
COPY . /app

# Disable development dependencies
ENV UV_NO_DEV=1

# Sync dependencies and remove pre-installed packaging tools containing vendored CVEs
RUN uv sync --locked && \
    rm -rf /usr/local/lib/python3.14/ensurepip \
           /usr/local/lib/python3.14/site-packages/pip*

# Presuming there is a `my_app` command provided by the project
CMD ["uv", "run", "my_app"]