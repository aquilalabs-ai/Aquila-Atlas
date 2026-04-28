#!/usr/bin/env bash
# Install binary security tools (trivy + gitleaks) on Linux/macOS.
# Python tools (semgrep, checkov) are declared in pyproject.toml and installed via uv/pip.
#
# Usage: bash scripts/install-security-tools.sh
set -euo pipefail

GITLEAKS_VERSION="8.21.2"

echo "==> Installing trivy..."
curl -sfL https://raw.githubusercontent.com/aquasecurity/trivy/main/contrib/install.sh \
    | sh -s -- -b /usr/local/bin
trivy --version

echo ""
echo "==> Installing gitleaks ${GITLEAKS_VERSION}..."
OS=$(uname -s | tr '[:upper:]' '[:lower:]')
ARCH=$(uname -m)
case "$ARCH" in
    x86_64)  ARCH="x64" ;;
    aarch64) ARCH="arm64" ;;
    arm64)   ARCH="arm64" ;;
esac

wget -q "https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/gitleaks_${GITLEAKS_VERSION}_${OS}_${ARCH}.tar.gz" \
     -O /tmp/gitleaks.tar.gz
tar -xzf /tmp/gitleaks.tar.gz -C /usr/local/bin gitleaks
rm /tmp/gitleaks.tar.gz
gitleaks version

echo ""
echo "==> Installing Python security tools (semgrep + checkov)..."
uv sync   # picks up semgrep + checkov from pyproject.toml

echo ""
echo "All security tools installed:"
semgrep   --version
checkov   --version
trivy     --version
gitleaks  version
