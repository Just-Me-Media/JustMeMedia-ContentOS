# Code Signing & Distribution

## Overview
ContentOS is distributed as a self-contained archive with no code signing by default. This document outlines the signing process for enterprise distribution.

## macOS Signing

For macOS distribution, you'll need an Apple Developer ID certificate:

```bash
# 1. Build the distribution
./scripts/dist.sh

# 2. Sign the Python scripts
codesign --force --deep --sign "Developer ID Application: Your Name (TEAMID)" \
    contentos-dist.zip

# 3. Create a signed disk image for distribution
hdiutil create -volname "ContentOS" -srcfolder /tmp/contentos-dist \
    -ov -format UDZO contentos.dmg

# 4. Notarize (optional but recommended)
xcrun notarytool submit contentos.dmg --keychain-profile "AC_PASSWORD" --wait

# 5. Staple the notarization
xcrun stapler staple contentos.dmg
```

## Windows Signing

For Windows, use a code signing certificate from a trusted CA:

```powershell
# Using signtool.exe (Windows SDK)
signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 `
    /f "path\to\your\certificate.pfx" /p "password" `
    contentos-dist.zip

# Verify signature
signtool verify /pa contentos-dist.zip
```

## Verification Commands

### macOS
```bash
# Verify notarization
xcrun stapler validate /path/to/contentos.dmg

# Check code signature
codesign --verify --deep --strict contentos-dist/app/server.py
```

### Windows
```powershell
# Verify signature
signtool verify /pa contentos-dist.zip
```

## Release Process

1. **Update version** in `app/server.py`: `CONTENTOS_VERSION = "X.Y.Z"`
2. **Update changelog** in `docs/CHANGELOG.md`
3. **Build frontend**: `cd frontend && npm run build`
4. **Create distribution**: `./scripts/dist.sh`
5. **Sign artifacts**: Use the commands above
6. **Upload to GitHub Releases**: Attach signed DMG/ZIP
7. **Update release notes** with new features and known issues

## Notarization Notes

For macOS, notarization is required for distribution outside the developer account. The Apple notary service:
- Scans for malware
- Checks for known vulnerable libraries
- Validates code signature

Set the environment variable before building:
```bash
export NOTARIZE=1  # Set to enable notarization in build scripts
```

## Security Checklist

- [ ] No API keys or credentials in the archive
- [ ] All Python files compiled successfully
- [ ] Static assets built and minified
- [ ] Distribution tested on clean machine
- [ ] Code signature verified
- [ ] Notarization complete (macOS)

## Transparency

- Source code: Public in GitHub repository
- Build process: Fully reproducible via shell scripts
- Dependencies: Python standard library only; npm modules for frontend
- No telemetry or data collection