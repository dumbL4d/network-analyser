# Production image for the Network Analyser FastAPI backend.
#
# Build from the backend/ directory (docker-compose in Ticket 0.4 / 6.3 uses
# `context: ../backend` for exactly this layout):
#
#   docker build -t network-analyser-backend .
#
# Runtime notes:
#   - The ping engine needs CAP_NET_RAW for icmplib's raw ICMP sockets, so run
#     the container with `--cap-add=NET_RAW` (set in docker-compose).
#   - Mount a volume at /app/data so the SQLite database survives rebuilds.

FROM python:3.12-slim

# No system `ping` binary is installed: app/services/ping_engine.py has never
# shelled out to a subprocess. The code review for Ticket 1.2 / this ticket
# confirms it uses icmplib's pure-Python socket API exclusively --
# `async_ping(..., privileged=True)` opens a raw ICMP socket directly. The
# legacy tool invoked the system ping binary, but this rewrite does not,
# so installing iputils-ping would be a cargo-culted dependency. The only
# runtime privilege needed is the NET_RAW capability.

WORKDIR /app

# Install dependencies BEFORE copying application code so this layer only
# rebuilds when requirements.txt changes (layer-caching optimization).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# requirements-dev.txt is intentionally NOT installed: pytest/httpx are dev-only
# and stay out of the deployed image.

# Application code.
COPY app /app/app
# Debug utility only: scripts/manual_ping_test.py (manual on-demand ping
# smoke test). Not invoked at runtime, but useful for in-container debugging.
COPY scripts /app/scripts

# SQLite needs a writable directory even before a volume is mounted, so a
# volume-less test run does not crash on a missing directory. The volume mount
# (mounted to /app/data) overlays this in real deployments.
RUN mkdir -p /app/data

EXPOSE 8000

# No --reload: that flag is development-only and must not run in production.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]