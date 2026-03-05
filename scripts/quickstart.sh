#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${ROOT_DIR}/.venv"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Error: python3 is required but not found in PATH." >&2
  exit 1
fi

cd "${ROOT_DIR}"

echo "Creating virtual environment at ${VENV_DIR} ..."
python3 -m venv "${VENV_DIR}"

echo "Installing Anglerfish and dev dependencies ..."
"${VENV_DIR}/bin/python" -m pip install --upgrade pip
"${VENV_DIR}/bin/pip" install -e ".[dev]"

echo
echo "Quickstart setup complete."
echo
echo "Next steps:"
echo "1. Activate environment:"
echo "   source .venv/bin/activate"
echo "2. Set application auth variables:"
echo "   export ANGLERFISH_CLIENT_ID=\"<your-application-client-id>\""
echo "   export ANGLERFISH_TENANT_ID=\"<your-tenant-id-guid>\""
echo "   export ANGLERFISH_APP_CREDENTIAL_MODE=\"secret\""
echo "   export ANGLERFISH_CLIENT_SECRET=\"<your-client-secret>\""
echo "   # or certificate auth:"
echo "   # export ANGLERFISH_APP_CREDENTIAL_MODE=\"certificate\""
echo "   # export ANGLERFISH_CLIENT_CERT_PFX_PATH=\"/path/to/client-cert.pfx\""
echo "   # export ANGLERFISH_CLIENT_CERT_PASSPHRASE=\"<optional-passphrase>\""
echo "3. Verify CLI:"
echo "   anglerfish --version"
echo "4. Run first deployment:"
echo "   anglerfish"
echo "   # or force certificate mode:"
echo "   # anglerfish --credential-mode certificate"
