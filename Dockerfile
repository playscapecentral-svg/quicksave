FROM python:3.12-slim

# deno: JS runtime yt-dlp uses to solve YouTube's "n" challenge (EJS).
COPY --from=denoland/deno:bin /deno /usr/local/bin/deno

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg git curl xz-utils \
 && rm -rf /var/lib/apt/lists/*

# Node.js (for the bgutil PO-token provider) — official tarball, since the
# distro package is too old. Arch-matched to the build machine.
RUN case "$(uname -m)" in x86_64) NARCH=x64 ;; aarch64) NARCH=arm64 ;; *) NARCH=x64 ;; esac \
 && curl -fsSL "https://nodejs.org/dist/v20.19.5/node-v20.19.5-linux-${NARCH}.tar.xz" \
    | tar -xJ -C /usr/local --strip-components=1 \
 && node --version && npm --version

# bgutil-ytdlp-pot-provider: generates YouTube PO tokens so the web clients
# can pass the "not a bot" check WITHOUT any login cookies.
RUN git clone --depth 1 https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git /opt/bgutil \
 && cd /opt/bgutil/server && npm install --no-audit --no-fund && npx tsc

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py .
COPY templates ./templates
COPY static ./static

ENV PORT=5000
EXPOSE 5000
CMD ["sh", "-c", "node /opt/bgutil/server/build/main.js --port 4416 > /tmp/pot.log 2>&1 & exec gunicorn --bind 0.0.0.0:$PORT --workers 1 --threads 8 --timeout 600 server:app"]
