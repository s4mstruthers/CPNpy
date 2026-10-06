#!/bin/sh
# Add CPNpy Studio to the applications menu (and optionally the desktop).
#
# Run it from the unpacked CPNpy folder, wherever you keep it:
#     ./install-desktop-entry.sh
# It writes ~/.local/share/applications/cpnpy.desktop pointing at this folder,
# so run it again if you move the folder.  Nothing outside your home folder
# is touched; delete that one file to undo it.
set -e

HERE="$(cd "$(dirname "$0")" && pwd)"
ENTRY_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ENTRY="$ENTRY_DIR/cpnpy.desktop"

mkdir -p "$ENTRY_DIR"
cat > "$ENTRY" <<EOF
[Desktop Entry]
Type=Application
Name=CPNpy Studio
Comment=Process mining, Petri nets and coloured Petri nets
Exec="$HERE/CPNpy" %F
Icon=$HERE/CPNpy.png
Terminal=false
Categories=Education;Science;Development;
StartupWMClass=CPNpy
EOF
chmod +x "$ENTRY"
echo "Added CPNpy Studio to the applications menu ($ENTRY)."

# Also put a launcher on the desktop, if there is one.
DESKTOP="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"
if [ -d "$DESKTOP" ]; then
    cp "$ENTRY" "$DESKTOP/cpnpy.desktop"
    chmod +x "$DESKTOP/cpnpy.desktop"
    # GNOME asks before running desktop launchers until they are marked trusted.
    gio set "$DESKTOP/cpnpy.desktop" metadata::trusted true 2>/dev/null || true
    echo "Added a launcher to $DESKTOP."
fi
