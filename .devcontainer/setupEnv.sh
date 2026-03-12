#!/bin/sh

# ── Inject setup-in-progress banner into ~/.bashrc ───────────────────────────
# This runs every time a new bash terminal opens until setup is complete.
cat >> ~/.bashrc << 'BANNER_EOF'

# === Prior Auth MAF: devcontainer setup banner (auto-removed when done) ===
if [ ! -f /tmp/.devcontainer-setup-complete ]; then
  echo ""
  echo "╔══════════════════════════════════════════════════════════════╗"
  echo "║  ⏳  ENVIRONMENT SETUP IN PROGRESS — PLEASE WAIT            ║"
  echo "╠══════════════════════════════════════════════════════════════╣"
  echo "║                                                              ║"
  echo "║  Installing: Azure CLI • azd • Python packages • npm        ║"
  echo "║                                                              ║"
  echo "║  ⚠️  DO NOT run  azd up  until you see the ✅ message.      ║"
  echo "║                                                              ║"
  echo "║  Monitor: Codespaces menu ▸ View Creation Log               ║"
  echo "║                                                              ║"
  echo "╚══════════════════════════════════════════════════════════════╝"
  echo ""
fi
# === end banner ===
BANNER_EOF

rm -f /tmp/.devcontainer-setup-complete

echo "Pull latest code for the current branch"
git fetch
git pull

set -e

# Ensure azd is available (fallback if Dev Container Feature failed)
if ! command -v azd >/dev/null 2>&1 || ! azd version >/dev/null 2>&1; then
  echo "Installing Azure Developer CLI (azd)..."
  curl -fsSL https://aka.ms/install-azd.sh | bash
  echo "azd installed: $(azd version)"
else
  echo "azd already available: $(azd version)"
fi

echo "Upgrading Azure CLI to latest..."
# Remove stale Yarn repo that blocks apt-get update (expired GPG key)
sudo rm -f /etc/apt/sources.list.d/yarn.list 2>/dev/null
curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash
echo "az CLI version: $(az version --query '"azure-cli"' -o tsv)"

echo "Installing Azure CLI extensions..."
az extension add --name containerapp --yes 2>/dev/null || echo "⚠️ containerapp extension install skipped"

echo "Setting up Backend..."
cd ./backend
pip install --upgrade pip
pip install -r requirements.txt || echo "⚠️ Backend dependency install had errors (non-fatal)"
cd ../

echo "Setting up Frontend..."
cd ./frontend
npm install
cd ../

echo "Setup complete! 🎉"

# Mark setup complete and remove the warning banner from ~/.bashrc
touch /tmp/.devcontainer-setup-complete
sed -i '/# === Prior Auth MAF: devcontainer setup banner/,/# === end banner ===/d' ~/.bashrc

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  ✅  ENVIRONMENT READY — open a new terminal to deploy       ║"
echo "╠══════════════════════════════════════════════════════════════╣"
echo "║                                                              ║"
echo "║  Run:  azd auth login && az login && azd up                 ║"
echo "║                                                              ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
