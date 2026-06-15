#!/usr/bin/env bash
set -euo pipefail

# ============================================================================
# Yukkuri TTS — Setup Script
# ============================================================================
# This script installs system dependencies, downloads/extracts the VOICEVOX
# engine, creates a PipeWire virtual audio sink, initialises the project
# config, and makes scripts executable.
#
# The script is idempotent — it is safe to run multiple times.
# ============================================================================

# ── Colours ─────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m' # No Colour

ok()   { echo -e "${GREEN}[OK]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
err()  { echo -e "${RED}[ERR]${NC} $1"; }
info() { echo -e "${BOLD}[INFO]${NC} $1"; }
header() {
    echo ""
    echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BOLD}  $1${NC}"
    echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
}

# ── Utility helpers ────────────────────────────────────────────────────────
command_exists() {
    command -v "$1" &>/dev/null
}

# ── Step 1: System dependencies ────────────────────────────────────────────
step_system_deps() {
    header "Step 1 / 6 — Installing system dependencies"

    local missing=()
    command_exists python3       || missing+=(python3)
    command_exists pip3          || missing+=(python3-pip)
    command_exists pactl         || missing+=(pulseaudio-utils)
    command_exists 7z            || missing+=(p7zip-full)

    if [[ ${#missing[@]} -gt 0 ]]; then
        info "The following packages will be installed: ${missing[*]}"
        sudo apt-get update
        sudo apt-get install -y python3-pip pulseaudio-utils p7zip-full python3-tk
        ok "System dependencies installed."
    else
        ok "All system dependencies already present — skipping."
    fi
}

# ── Step 2: VOICEVOX engine ───────────────────────────────────────────────
step_voicevox() {
    header "Step 2 / 6 — VOICEVOX engine"

    local engine_dir="$HOME/voicevox/voicevox_engine-linux-cpu-x64"
    local archive_url="https://github.com/VOICEVOX/voicevox_engine/releases/download/0.25.2/voicevox_engine-linux-cpu-x64-0.25.2.7z.001"

    if [[ -d "$engine_dir" ]]; then
        ok "VOICEVOX engine already present at ${engine_dir} — skipping download."
        return
    fi

    info "VOICEVOX engine not found. Downloading..."

    mkdir -p "$HOME/voicevox"

    local archive_name
    archive_name="$(basename "$archive_url")"

    echo ""
    curl -L --progress-bar "$archive_url" -o "$HOME/voicevox/$archive_name"
    echo ""

    # Check that the download succeeded (non-zero file)
    if [[ ! -f "$HOME/voicevox/$archive_name" ]] || [[ ! -s "$HOME/voicevox/$archive_name" ]]; then
        err "Download failed or produced an empty file."
        exit 1
    fi
    ok "Download complete."

    info "Extracting with 7z..."
    if ! 7z x "$HOME/voicevox/$archive_name" -o"$HOME/voicevox/" -y &>/dev/null; then
        err "Extraction failed. The archive may be corrupt."
        exit 1
    fi
    ok "Extraction complete."

    info "Cleaning up archive..."
    rm -f "$HOME/voicevox/$archive_name"
    ok "Cleanup done."

    # Verify the engine directory now exists
    if [[ ! -d "$engine_dir" ]]; then
        warn "Expected engine directory not found after extraction at ${engine_dir}"
        warn "Please check the extracted contents of ~/voicevox/ manually."
    else
        ok "VOICEVOX engine ready at ${engine_dir}"
    fi
}

# ── Step 3: PipeWire virtual sink config ───────────────────────────────────
step_pipewire_config() {
    header "Step 3 / 6 — PipeWire virtual audio sink"

    local conf_dir="$HOME/.config/pipewire/pipewire.conf.d"
    local conf_file="$conf_dir/99-yukkuri.conf"

    mkdir -p "$conf_dir"

    if [[ -f "$conf_file" ]]; then
        ok "PipeWire config already exists at ${conf_file} — skipping."
        return
    fi

    cat > "$conf_file" << 'PIPEWIRE_CONF'
context.objects = [
    {   factory = adapter
        args = {
            factory.name     = support.null-audio-sink
            node.name        = "yukkuri_sink"
            node.description = "Yukkuri Virtual Sink"
            media.class      = "Audio/Sink"
            audio.position   = "FL,FR"
            monitor.passthrough = true
        }
    }
]
PIPEWIRE_CONF

    ok "PipeWire config written to ${conf_file}"
}

# ── Step 4: Restart PipeWire ───────────────────────────────────────────────
step_restart_pipewire() {
    header "Step 4 / 6 — Restarting PipeWire"

    if command_exists systemctl; then
        info "Restarting pipewire and pipewire-pulse user services..."
        systemctl --user restart pipewire pipewire-pulse 2>/dev/null || {
            warn "Could not restart PipeWire services automatically."
            warn "You may need to log out and back in, or reboot, for the virtual sink to appear."
            return
        }
        ok "PipeWire restarted successfully."
    else
        warn "systemctl not found — cannot restart PipeWire automatically."
        warn "Please restart PipeWire manually or reboot."
    fi
}

# ── Step 5: Project config directory ───────────────────────────────────────
step_project_config() {
    header "Step 5 / 6 — Project configuration"

    local config_dir="$HOME/.config/yukkuri"
    local config_file="$config_dir/config.json"
    local default_config="/home/swig/TTS/config.json"

    mkdir -p "$config_dir"

    if [[ -f "$config_file" ]]; then
        ok "Config already exists at ${config_file} — skipping."
    else
        if [[ -f "$default_config" ]]; then
            cp "$default_config" "$config_file"
            ok "Default config copied to ${config_file}"
        else
            warn "Default config not found at ${default_config}."
            warn "Creating an empty config file at ${config_file} — please edit it."
            echo '{}' > "$config_file"
        fi
    fi
}

# ── Step 6: Make scripts executable ────────────────────────────────────────
step_make_executable() {
    header "Step 6 / 6 — Making scripts executable"

    local script="/home/swig/TTS/yukkuri.py"

    if [[ -f "$script" ]]; then
        chmod +x "$script"
        ok "${script} is now executable."
    else
        warn "${script} not found — skipping chmod."
    fi
}

# ── Final summary ──────────────────────────────────────────────────────────
print_summary() {
    echo ""
    echo -e "${GREEN}${BOLD}╔══════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}${BOLD}║           Yukkuri TTS — Setup Complete!                ║${NC}"
    echo -e "${GREEN}${BOLD}╚══════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "  ${BOLD}Start the VOICEVOX engine:${NC}"
    echo -e "    cd ~/voicevox/voicevox_engine-linux-cpu-x64/"
    echo -e "    ./run"
    echo ""
    echo -e "  ${BOLD}Run the TTS application:${NC}"
    echo -e "    python3 /home/swig/TTS/yukkuri.py"
    echo ""
    echo -e "  ${BOLD}Select the virtual microphone in Discord:${NC}"
    echo -e "    Open Discord → User Settings → Voice & Video →"
    echo -e '    Input Device →  "Yukkuri Virtual Sink" (or the PipeWire'
    echo -e "    null-audio-sink monitor associated with it)"
    echo ""
    echo -e "  ${BOLD}Notes:${NC}"
    echo -e "    - The VOICEVOX engine serves its API at http://localhost:50021"
    echo -e "    - The virtual sink is named 'yukkuri_sink'"
    echo -e "    - Run this setup script again any time to repair or update"
    echo ""
}

# ── Main ───────────────────────────────────────────────────────────────────
main() {
    echo ""
    echo -e "${BOLD} Yukkuri TTS — Setup Script${NC}"
    echo -e "${BOLD}============================${NC}"
    echo ""
    echo "This script will prepare your system to run the Yukkuri TTS"
    echo "application, which uses VOICEVOX and PipeWire to pipe Japanese"
    echo "text-to-speech into Discord as a virtual microphone."
    echo ""

    # Prompt before making changes unless --yes is passed
    if [[ "${1:-}" != "--yes" ]] && [[ "${1:-}" != "-y" ]]; then
        read -rp "Proceed with setup? [Y/n] " reply
        case "$reply" in
            [nN]|[nN][oO]) echo "Aborting."; exit 0 ;;
            *) ;;
        esac
    fi

    step_system_deps
    step_voicevox
    step_pipewire_config
    step_restart_pipewire
    step_project_config
    step_make_executable
    print_summary

    ok "All done. Happy Yukkuri!"
}

main "$@"
