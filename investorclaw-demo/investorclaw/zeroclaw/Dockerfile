# InvestorClaw zeroclaw runtime image
# Replaces alpine:3.20 default with Python 3.13 + all InvestorClaw dependencies
# Used as: [runtime.docker] image = "investorclaw-runtime:latest"
#
# Build: docker build -t investorclaw-runtime:latest -f zeroclaw/Dockerfile .
# Push (optional): docker tag investorclaw-runtime:latest <registry>/investorclaw-runtime:latest

FROM python:3.13-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    curl \
    git \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install InvestorClaw Python dependencies
# These match requirements.txt core deps (excludes heavy PDF/Excel optional deps)
RUN pip install --no-cache-dir \
    "polars>=0.20.0" \
    "pandas>=2.0.0" \
    "pyarrow>=12.0.0" \
    "yfinance>=0.2.35" \
    "requests>=2.31.0" \
    "pyyaml>=6.0" \
    "orjson>=3.9.0" \
    "python-dateutil>=2.8.0" \
    "python-dotenv>=1.0.0" \
    "numpy>=1.24.0"

# Verify imports
RUN python3 -c "import polars, yfinance, pandas, pyarrow, requests, yaml, orjson; print('All deps OK')"

# Create investorclaw data directory
RUN mkdir -p /home/pi/investorclaw/data /home/pi/investorclaw/portfolios

WORKDIR /home/pi/investorclaw

CMD ["/bin/bash"]
