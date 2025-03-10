
#!/bin/bash
echo "Installing required packages for WifiPrinter..."

# Detect package manager
if command -v apt &> /dev/null; then
    sudo apt update
    sudo apt install -y cups cups-client cups-bsd
elif command -v yum &> /dev/null; then
    sudo yum install -y cups cups-client cups-lpd
elif command -v dnf &> /dev/null; then
    sudo dnf install -y cups cups-client cups-lpd
elif command -v pacman &> /dev/null; then
    sudo pacman -S cups cups-pdf
else
    echo "Could not detect package manager. Please install CUPS manually."
    exit 1
fi

# Enable CUPS service
sudo systemctl enable cups
sudo systemctl start cups

echo "Installation complete! You may need to add your user to the lpadmin group:"
echo "sudo usermod -aG lpadmin $USER"
echo "Then log out and back in for changes to take effect."