# Heygen Passport container image for Docker Desktop.
# Build from the repository root:
#   docker compose -f heygen_passport/docker-compose.yml build
FROM ubuntu:24.04

# Python and Microsoft ODBC Driver 18 for SQL Server (officially supported
# on Ubuntu 24.04).
ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 python3-venv curl gnupg ca-certificates tzdata \
 && curl -fsSL https://packages.microsoft.com/keys/microsoft.asc \
    | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg \
 && echo "deb [arch=amd64,arm64 signed-by=/usr/share/keyrings/microsoft-prod.gpg] https://packages.microsoft.com/ubuntu/24.04/prod noble main" \
    > /etc/apt/sources.list.d/mssql-release.list \
 && apt-get update \
 && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 unixodbc libgssapi-krb5-2 \
 && rm -rf /var/lib/apt/lists/* \
 && python3 -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH

WORKDIR /app
COPY heygen_passport/requirements.txt heygen_passport/requirements.txt
RUN pip install --no-cache-dir -r heygen_passport/requirements.txt

COPY heygen_passport heygen_passport
RUN rm -f heygen_passport/local.env \
 && useradd --create-home --uid 10001 heygen \
 && sed -i "s/\r$//" heygen_passport/docker/entrypoint.sh \
 && chmod +x heygen_passport/docker/entrypoint.sh

USER heygen
ENV PYTHONUNBUFFERED=1 \
    HEYGEN_DB_ENGINE=mssql \
    HEYGEN_PORT=8502
EXPOSE 8502
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request,os;urllib.request.urlopen('http://127.0.0.1:%s/_stcore/health' % os.environ.get('HEYGEN_PORT','8502'), timeout=4)"
ENTRYPOINT ["heygen_passport/docker/entrypoint.sh"]
