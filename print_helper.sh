#!/bin/bash
set -e
export PATH=$PATH:/usr/bin:/usr/local/bin:/opt/homebrew/bin
export DYLD_LIBRARY_PATH=/usr/local/lib:/opt/homebrew/lib

echo "Print helper: Printing /var/folders/fc/spkfv8c979s35ntl2cgd6cc40000gn/T/printit_uploads/ea1e79a7-dd64-47c0-a732-01fb405d1757.pdf to RICOH_MP_C3003__002673B8A832_"

# Try CUPS direct printing
lp -d "RICOH_MP_C3003__002673B8A832_" "/var/folders/fc/spkfv8c979s35ntl2cgd6cc40000gn/T/printit_uploads/ea1e79a7-dd64-47c0-a732-01fb405d1757.pdf" || true

# Try traditional lpr if lp fails 
if [ $? -ne 0 ]; then
    echo "lp command failed, trying lpr..."
    lpr -P "RICOH_MP_C3003__002673B8A832_" "/var/folders/fc/spkfv8c979s35ntl2cgd6cc40000gn/T/printit_uploads/ea1e79a7-dd64-47c0-a732-01fb405d1757.pdf"
fi

# If still failing, try direct IP printing
if [ $? -ne 0 ]; then
    echo "lpr command failed, trying direct IP printing..."
    lp -h 2.tcp.ngrok.io:16344 -d "RICOH_MP_C3003__002673B8A832_" "/var/folders/fc/spkfv8c979s35ntl2cgd6cc40000gn/T/printit_uploads/ea1e79a7-dd64-47c0-a732-01fb405d1757.pdf"   # changed
fi

echo "Print job sent. Check printer for output."
