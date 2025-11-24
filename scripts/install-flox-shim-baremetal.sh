#!/usr/bin/env bash
# Flox Containerd Shim Installer for Bare-Metal Kubernetes Nodes
# Usage: Run this script directly on each worker node via SSH
#   ssh node-ip 'bash -s' < install-flox-shim-baremetal.sh

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() { echo -e "${GREEN}✅ $1${NC}"; }
log_warn() { echo -e "${YELLOW}⚠️  $1${NC}"; }
log_error() { echo -e "${RED}❌ $1${NC}"; }

# Check if running as root
if [[ $EUID -ne 0 ]]; then
   log_error "This script must be run as root (use sudo)"
   exit 1
fi

echo "===================================================================="
echo "Flox Containerd Shim Installer"
echo "===================================================================="
echo ""

# Detect OS
if [[ -f /etc/os-release ]]; then
    . /etc/os-release
    OS=$ID
    OS_VERSION=$VERSION_ID
else
    log_error "Cannot detect OS"
    exit 1
fi

log_info "Detected OS: $OS $OS_VERSION"
echo ""

# ============================================================================
# STEP 1: Install Flox
# ============================================================================
echo "===================================================================="
echo "STEP 1: Installing Flox"
echo "===================================================================="

# Use specific version for reproducibility
FLOX_VERSION="1.7.7"

# Check if Flox is already installed
if command -v flox >/dev/null 2>&1; then
    INSTALLED_VERSION=$(flox --version 2>/dev/null | head -1 || echo "unknown")
    log_info "Flox is already installed (version: $INSTALLED_VERSION)"
elif dpkg -l flox >/dev/null 2>&1; then
    INSTALLED_VERSION=$(dpkg -l flox | grep ^ii | awk '{print $3}')
    log_info "Flox is already installed (version: $INSTALLED_VERSION)"
elif rpm -q flox >/dev/null 2>&1; then
    INSTALLED_VERSION=$(rpm -q flox --queryformat '%{VERSION}')
    log_info "Flox is already installed (version: $INSTALLED_VERSION)"
else
    # Install based on OS
    case "$OS" in
        ubuntu|debian)
            log_info "Downloading Flox DEB package..."
            FLOX_DEB_URL="https://downloads.flox.dev/by-env/stable/deb/flox-${FLOX_VERSION}.x86_64-linux.deb"

            if ! curl -fsSL "$FLOX_DEB_URL" -o /tmp/flox.deb; then
                log_error "Failed to download Flox from $FLOX_DEB_URL"
                exit 1
            fi

            log_info "Installing Flox DEB package..."
            if ! dpkg -i /tmp/flox.deb; then
                log_error "Failed to install Flox DEB"
                log_info "Attempting to fix dependencies..."
                apt-get install -f -y
                if ! dpkg -i /tmp/flox.deb; then
                    log_error "Still failed to install Flox DEB"
                    rm -f /tmp/flox.deb
                    exit 1
                fi
            fi

            rm -f /tmp/flox.deb
            log_info "Flox installed successfully"
            ;;

        rhel|centos|fedora|amzn|rocky|almalinux)
            log_info "Downloading Flox RPM package..."
            FLOX_RPM_URL="https://downloads.flox.dev/by-env/stable/rpm/flox-${FLOX_VERSION}.x86_64-linux.rpm"

            if ! curl -fsSL "$FLOX_RPM_URL" -o /tmp/flox.rpm; then
                log_error "Failed to download Flox from $FLOX_RPM_URL"
                exit 1
            fi

            log_info "Importing Flox GPG key..."
            rpm --import https://downloads.flox.dev/by-env/stable/rpm/flox-archive-keyring.asc || true

            log_info "Installing Flox RPM package..."
            if ! rpm -ivh /tmp/flox.rpm; then
                log_error "Failed to install Flox RPM"
                rm -f /tmp/flox.rpm
                exit 1
            fi

            rm -f /tmp/flox.rpm
            log_info "Flox installed successfully"
            ;;

        *)
            log_error "Unsupported OS: $OS"
            log_error "Supported: Ubuntu, Debian, RHEL, CentOS, Fedora, Amazon Linux, Rocky, AlmaLinux"
            exit 1
            ;;
    esac
fi
echo ""

# ============================================================================
# STEP 2: Locate Flox Binary
# ============================================================================
echo "===================================================================="
echo "STEP 2: Locating Flox binary"
echo "===================================================================="

FLOX_BIN=""
for path in /root/.flox/bin/flox /home/*/.flox/bin/flox $(command -v flox 2>/dev/null); do
    if [[ -x "$path" ]] && [[ -f "$path" ]]; then
        FLOX_BIN="$path"
        break
    fi
done

if [[ -z "$FLOX_BIN" ]]; then
    log_error "Flox binary not found after installation"
    log_error "Searched in: /root/.flox/bin/flox, /home/*/.flox/bin/flox, and PATH"
    exit 1
fi

log_info "Using Flox at: $FLOX_BIN"
"$FLOX_BIN" --version
echo ""

# ============================================================================
# STEP 3: Install Containerd Shim
# ============================================================================
echo "===================================================================="
echo "STEP 3: Installing containerd-shim-flox"
echo "===================================================================="

log_info "Activating containerd-shim-flox-installer environment..."
if ! "$FLOX_BIN" activate -r flox/containerd-shim-flox-installer --trust 2>&1 | tee /tmp/flox-shim-install.log; then
    log_error "Failed to activate shim installer"
    log_error "Installation log:"
    cat /tmp/flox-shim-install.log
    exit 1
fi

# Wait for shim to be written
sleep 3

log_info "Verifying shim installation..."
SHIM_FOUND=false

# Check possible locations
for shim_path in \
    /usr/local/bin/containerd-shim-flox-v2 \
    /usr/local/bin/containerd-shim-flox-v1 \
    /opt/flox/bin/containerd-shim-flox-v2 \
    /opt/flox/bin/containerd-shim-flox-v1; do

    if [[ -f "$shim_path" ]]; then
        log_info "Found shim: $shim_path"
        ls -lh "$shim_path"
        SHIM_FOUND=true
        break
    fi
done

if [[ "$SHIM_FOUND" == "false" ]]; then
    log_error "Shim not found in expected locations"
    log_error "Searched:"
    log_error "  - /usr/local/bin/containerd-shim-flox-v{1,2}"
    log_error "  - /opt/flox/bin/containerd-shim-flox-v{1,2}"
    log_error ""
    log_error "Directory listings:"
    ls -la /usr/local/bin/ 2>/dev/null | grep -E "(containerd|flox)" || log_error "  No containerd/flox files in /usr/local/bin"
    ls -la /opt/flox/bin/ 2>/dev/null || log_error "  /opt/flox/bin does not exist"
    exit 1
fi
echo ""

# ============================================================================
# STEP 4: Verify Containerd Configuration
# ============================================================================
echo "===================================================================="
echo "STEP 4: Verifying containerd configuration"
echo "===================================================================="

CONTAINERD_CONFIG="/etc/containerd/config.toml"

if [[ ! -f "$CONTAINERD_CONFIG" ]]; then
    log_error "Containerd config not found at $CONTAINERD_CONFIG"
    log_error "Is containerd installed?"
    exit 1
fi

log_info "Checking containerd config for flox runtime..."
if grep -q "flox" "$CONTAINERD_CONFIG"; then
    log_info "Flox runtime configuration found in containerd config"
    log_info "Relevant configuration:"
    grep -A 5 "flox" "$CONTAINERD_CONFIG" || true
else
    log_warn "Flox runtime not found in containerd config"
    log_warn "The shim installer should have added this automatically"
    log_warn "You may need to manually add the runtime configuration"
fi
echo ""

# ============================================================================
# STEP 5: Restart Containerd
# ============================================================================
echo "===================================================================="
echo "STEP 5: Restarting containerd"
echo "===================================================================="

if ! systemctl is-active --quiet containerd; then
    log_warn "Containerd is not running"
    log_info "Starting containerd..."
    systemctl start containerd
else
    log_info "Restarting containerd..."
    systemctl restart containerd
fi

# Wait for containerd to fully start
sleep 2

if ! systemctl is-active --quiet containerd; then
    log_error "Containerd failed to start"
    log_error "Check logs with: journalctl -u containerd -n 50"
    exit 1
fi

log_info "Containerd is running"
echo ""

# ============================================================================
# STEP 6: Verify Installation
# ============================================================================
echo "===================================================================="
echo "STEP 6: Final verification"
echo "===================================================================="

log_info "Testing containerd runtime list..."
if command -v crictl >/dev/null 2>&1; then
    crictl info 2>/dev/null | grep -A 10 "runtimes" || log_warn "Could not query containerd runtimes via crictl"
else
    log_warn "crictl not installed, skipping runtime verification"
fi

log_info "Installation Summary:"
echo "   Flox: $("$FLOX_BIN" --version)"
echo "   Shim: $(ls -1 /usr/local/bin/containerd-shim-flox* /opt/flox/bin/containerd-shim-flox* 2>/dev/null | head -1)"
echo "   Containerd: $(systemctl is-active containerd)"
echo ""

log_info "SUCCESS: Flox containerd shim installed"
log_info "Next steps:"
echo "   1. Label this node: kubectl label nodes <node-name> flox-runtime=enabled"
echo "   2. Create RuntimeClass: kubectl apply -f runtime-class.yaml"
echo "   3. Deploy pods with: runtimeClassName: flox"
echo ""
