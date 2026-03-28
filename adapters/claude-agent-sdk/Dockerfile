# Claude Agent SDK Demo Container
# Runs the edictum Claude Agent SDK adapter demo outside of Claude Code
# to avoid nested session detection.
#
# Build (from repo root):
#   docker build -f adapters/claude-agent-sdk/Dockerfile -t edictum-claude-sdk-demo .
#
# Run:
#   docker run --rm -it \
#     -e ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
#     edictum-claude-sdk-demo
#
# With options:
#   docker run --rm -it \
#     -e ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
#     edictum-claude-sdk-demo --mode observe --quick

FROM node:22-slim

# Install Python 3.12+ and pip
RUN apt-get update && \
    apt-get install -y --no-install-recommends python3 python3-pip python3-venv && \
    rm -rf /var/lib/apt/lists/*

# Install Claude Code CLI globally (latest)
RUN npm install -g @anthropic-ai/claude-code

# Create app directory and Python venv
WORKDIR /app
RUN python3 -m venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

# Install Python dependencies
# Install Python dependencies (latest)
RUN pip install --no-cache-dir \
    edictum[yaml] \
    claude-agent-sdk \
    python-dotenv

# Copy demo files (build context = repo root)
COPY adapters/shared_v2.py /app/adapters/shared_v2.py
COPY adapters/rules.yaml /app/adapters/rules.yaml
COPY adapters/demo_claude_agent_sdk.py /app/adapters/demo_claude_agent_sdk.py

WORKDIR /app/adapters

ENTRYPOINT ["python3", "demo_claude_agent_sdk.py"]
CMD ["--quick"]
