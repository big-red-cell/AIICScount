#!/bin/bash
# Test script that simulates what a malicious script would do
echo "Capturing password..."
read -s -p "Password: " password
echo
echo "Password captured: $password"
echo "Now running actual sudo with captured password..."
echo "$password" | sudo -S whoami