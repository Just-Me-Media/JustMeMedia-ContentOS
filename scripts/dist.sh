#!/bin/bash
# Distribution script - builds and packages ContentOS for release
set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
DIST_DIR="/tmp/contentos-dist-$$"

echo "============================================"
echo "  Building ContentOS Distribution"
echo "============================================"

# Clean up any previous dist
rm -rf "$DIST_DIR"
mkdir -p "$DIST_DIR"

echo ""
echo "[1/4] Building frontend..."
cd "$ROOT/frontend"
npm install --quiet 2>/dev/null
npm run build
echo "   ✓ Frontend built"

cd "$ROOT"

echo ""
echo "[2/4] Copying files..."
# Copy essential files
for f in app/*.py; do
  cp "$f" "$DIST_DIR/"
done
cp -r app/platforms "$DIST_DIR/"
cp -r app/data "$DIST_DIR/" 2>/dev/null || mkdir -p "$DIST_DIR/data"
cp -r static "$DIST_DIR/" 2>/dev/null || echo "   (static dir will be created on build)"
cp -r config "$DIST_DIR/"
cp -r scripts "$DIST_DIR/"
cp -r brand "$DIST_DIR/"
cp -r prompts "$DIST_DIR/"
cp -r workflows "$DIST_DIR/"

# Copy docs
cp README.md "$DIST_DIR/"
cp SECURITY.md "$DIST_DIR/"
cp LICENSE "$DIST_DIR/" 2>/dev/null || echo "MIT License" > "$DIST_DIR/LICENSE"

echo "   ✓ Files copied"

echo ""
echo "[3/4] Creating run scripts..."
# Create simple run script
cat > "$DIST_DIR/run.sh" << 'RUNEOF'
#!/bin/bash
echo "Starting JustMeMedia ContentOS..."
echo "Visit http://127.0.0.1:8765"
cd "$(dirname "$0")"
python3 app/server.py
RUNEOF
chmod +x "$DIST_DIR/run.sh"

echo "   ✓ Run scripts created"

echo ""
echo "[4/4] Creating distribution archive..."
cd /tmp
zip -r contentos-dist.zip contentos-dist-$$ -x "*.DS_Store" -x "__pycache__/*" -x "*.pyc"
DIST_FILE="/tmp/contentos-dist.zip"

# Cleanup
rm -rf "$DIST_DIR"

echo ""
echo "============================================"
echo "  Distribution package created!"
echo "  Location: $DIST_FILE"
echo "  Size: $(du -h "$DIST_FILE" | cut -f1)"
echo "============================================"
echo ""
echo "To install:"
echo "  unzip contentos-dist.zip -d /your/install/dir"
echo ""
echo "Then run: ./run.sh"