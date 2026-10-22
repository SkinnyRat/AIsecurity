#!/usr/bin/env bash
# Quick fix for workspace permissions issue

set -e

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}PentestGPT Workspace Permission Fix${NC}\n"

# Check if workspace exists
if [ ! -d "./workspace" ]; then
    echo -e "${BLUE}Creating workspace directory...${NC}"
    mkdir -p ./workspace
    echo -e "${GREEN}✓ Created workspace directory${NC}\n"
    exit 0
fi

# Check current owner
OWNER=$(stat -c '%U' ./workspace 2>/dev/null || stat -f '%Su' ./workspace 2>/dev/null)
echo -e "${BLUE}Current workspace owner: ${NC}${OWNER}"

if [ "$OWNER" = "root" ]; then
    echo -e "${BLUE}Fixing permissions (requires sudo)...${NC}"
    sudo chown -R $(id -u):$(id -g) ./workspace
    echo -e "${GREEN}✓ Fixed workspace permissions${NC}"
    echo -e "${BLUE}New owner: ${NC}$(whoami)\n"
else
    echo -e "${GREEN}✓ Workspace permissions are correct${NC}\n"
fi

echo -e "${BLUE}Rebuilding Docker image with updated code...${NC}"
docker compose build

echo -e "\n${GREEN}✓ All done! You can now run:${NC}"
echo -e "  ${NC}docker compose run --rm pentestgpt pentestgpt-agent --goal \"Assess the target\" --target http://127.0.0.1:8000${NC}\n"
