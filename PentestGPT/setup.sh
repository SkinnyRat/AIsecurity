#!/usr/bin/env bash
# PentestGPT Setup Script
# Interactive setup for first-time Docker configuration

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
NC='\033[0m' # No Color

echo -e "${PURPLE}"
cat << "EOF"
    ██████╗ ███████╗███╗   ██╗████████╗███████╗███████╗████████╗ ██████╗ ██████╗ ████████╗
    ██╔══██╗██╔════╝████╗  ██║╚══██╔══╝██╔════╝██╔════╝╚══██╔══╝██╔════╝ ██╔══██╗╚══██╔══╝
    ██████╔╝█████╗  ██╔██╗ ██║   ██║   █████╗  ███████╗   ██║   ██║  ███╗██████╔╝   ██║
    ██╔═══╝ ██╔══╝  ██║╚██╗██║   ██║   ██╔══╝  ╚════██║   ██║   ██║   ██║██╔═══╝    ██║
    ██║     ███████╗██║ ╚████║   ██║   ███████╗███████║   ██║   ╚██████╔╝██║        ██║
    ╚═╝     ╚══════╝╚═╝  ╚═══╝   ╚═╝   ╚══════╝╚══════╝   ╚═╝    ╚═════╝ ╚═╝        ╚═╝

    Setup Script v1.0.0
EOF
echo -e "${NC}"

echo -e "${BLUE}Welcome to PentestGPT setup!${NC}\n"

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo -e "${RED}Error: Docker is not installed.${NC}"
    echo "Please install Docker first: https://docs.docker.com/get-docker/"
    exit 1
fi

# Check if Docker is running
if ! docker info &> /dev/null; then
    echo -e "${RED}Error: Docker is not running.${NC}"
    echo "Please start Docker and try again."
    exit 1
fi

echo -e "${GREEN}✓ Docker is installed and running${NC}\n"

# Check if Claude Code is installed (not strictly required since it's in Docker)
# This is just a convenience check for users who might want to use it locally
echo -e "${BLUE}Note:${NC} Claude Code CLI will be available inside the Docker container."
echo -e "You'll configure it after launching the container.\n"

# Create workspace directory with proper permissions
echo -e "${BLUE}Setting up workspace directory...${NC}"
if [ ! -d "./workspace" ]; then
    mkdir -p ./workspace
    echo -e "${GREEN}✓ Created workspace directory${NC}"
else
    echo -e "${GREEN}✓ Workspace directory exists${NC}"
fi

# Fix workspace permissions if owned by root
if [ -d "./workspace" ] && [ "$(stat -c '%U' ./workspace 2>/dev/null || stat -f '%Su' ./workspace 2>/dev/null)" = "root" ]; then
    echo -e "${BLUE}Workspace is owned by root, attempting to fix permissions...${NC}"
    if sudo -n true 2>/dev/null; then
        # Can use sudo without password
        sudo chown -R $(id -u):$(id -g) ./workspace
        echo -e "${GREEN}✓ Fixed workspace permissions${NC}"
    else
        # Need password for sudo
        echo -e "${NC}The workspace directory is owned by root and needs permission fix.${NC}"
        echo -e "${NC}Please enter your sudo password to fix permissions:${NC}"
        if sudo chown -R $(id -u):$(id -g) ./workspace; then
            echo -e "${GREEN}✓ Fixed workspace permissions${NC}"
        else
            echo -e "${RED}✗ Could not fix permissions automatically${NC}"
            echo -e "${NC}Please run manually: ${PURPLE}sudo chown -R \$(id -u):\$(id -g) ./workspace${NC}"
        fi
    fi
fi
echo ""

# Build Docker image
echo -e "${BLUE}Building Docker image...${NC}"
echo -e "${NC}(This may take a few minutes on first run)${NC}\n"

if docker build -t pentestgpt:latest .; then
    echo -e "\n${GREEN}✓ Docker image built successfully${NC}\n"
else
    echo -e "\n${RED}✗ Failed to build Docker image${NC}"
    exit 1
fi

# Create docker-compose.yml if it doesn't exist
if [ ! -f docker-compose.yml ]; then
    echo -e "${BLUE}Creating docker-compose.yml...${NC}"
    cat > docker-compose.yml << 'EOF'
version: '3.8'

services:
  pentestgpt:
    image: pentestgpt:latest
    volumes:
      - ./workspace:/workspace
    stdin_open: true
    tty: true
    environment:
      - TERM=xterm-256color
EOF
    echo -e "${GREEN}✓ docker-compose.yml created${NC}\n"
fi

# Setup complete
echo -e "${GREEN}═══════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}✓ Setup complete! PentestGPT Agent is ready to use.${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════════════${NC}\n"

echo -e "${BLUE}Before First Use:${NC}"
echo -e "  ${NC}1. Launch the Docker container:${NC}"
echo -e "     ${PURPLE}docker compose run --rm pentestgpt${NC}\n"
echo -e "  ${NC}2. Inside the container, configure Claude Code (first time only):${NC}"
echo -e "     ${PURPLE}claude config${NC}"
echo -e "     ${NC}(Follow the prompts to add your Anthropic API key)${NC}\n"
echo -e "  ${NC}3. Run PentestGPT Agent to solve a CTF challenge:${NC}"
echo -e "     ${PURPLE}pentestgpt-agent --goal \"Capture the CTF flag\" --target 10.10.11.234${NC}\n"

echo -e "${BLUE}Quick Start:${NC}"
echo -e "  ${NC}# Solve an HTB machine${NC}"
echo -e "  ${PURPLE}docker compose run --rm pentestgpt pentestgpt-agent --goal \"Capture the CTF flag\" --target 10.10.11.234${NC}\n"

echo -e "  ${NC}# Or enter container first (recommended for first-time setup)${NC}"
echo -e "  ${PURPLE}docker compose run --rm pentestgpt${NC}"
echo -e "  ${NC}# Then inside container: claude config (first time)${NC}"
echo -e "  ${NC}# Then: pentestgpt-agent --goal \"Capture the CTF flag\" --target 10.10.11.234${NC}\n"

echo -e "${BLUE}Options:${NC}"
echo -e "  ${NC}--goal TEXT${NC}            Assessment goal (required)"
echo -e "  ${NC}--target TARGET${NC}          Target CTF challenge or machine (required)"
echo -e "  ${NC}--backend BACKEND${NC}        claude or codex"
echo -e "  ${NC}--model MODEL${NC}            Backend-native model id\n"

echo -e "${BLUE}Examples:${NC}"
echo -e "  ${NC}# HTB machine${NC}"
echo -e "  ${PURPLE}docker compose run --rm pentestgpt pentestgpt-agent --goal \"Capture the CTF flag\" --target 10.10.11.100${NC}\n"

echo -e "  ${NC}# Web CTF challenge${NC}"
echo -e "  ${PURPLE}docker compose run --rm pentestgpt pentestgpt-agent --goal \"Capture the CTF flag\" --target https://ctf.example.com/challenge1${NC}\n"

echo -e "  ${NC}# With challenge context${NC}"
echo -e "  ${PURPLE}docker compose run --rm pentestgpt pentestgpt-agent --goal \"Capture the CTF flag; WordPress site, look for plugin vulns\" --target 10.10.11.50${NC}\n"

echo -e "${GREEN}Happy flag hunting! 🚩${NC}\n"
