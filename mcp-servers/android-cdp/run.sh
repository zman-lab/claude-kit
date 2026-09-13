#!/bin/bash
cd /Users/nhn/zman-lab/claude-kit/mcp-servers/android-cdp
exec /opt/homebrew/bin/python3 -m src.server 2>/tmp/android-cdp-mcp.log
