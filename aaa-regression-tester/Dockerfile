# aaa-regression-tester — Python 3.11 container.
# Runs as a Kubernetes Job inside the cluster (see plan-07 umbrella chart).
# Pushes metrics to Prometheus Pushgateway after the suite completes.

FROM python:3.11-slim

# Non-root user
RUN groupadd -r tester && useradd -r -g tester tester

WORKDIR /app

# Install dependencies first (cache layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install kubectl for post-test pod log inspection
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl" \
    && install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl \
    && rm kubectl \
    && apt-get purge -y curl && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

# Copy test suite
COPY . .

RUN chown -R tester:tester /app

USER tester

# Default: run full suite and push metrics.
# Override CMD in the Helm Job template to run a subset (e.g. --smoke).
CMD ["/bin/bash", "run_all.sh"]
