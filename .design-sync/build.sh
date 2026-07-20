#!/bin/sh
# Rebuild the tokens+guidelines design-sync bundle (ds-bundle/) from the
# committed sources. ds-bundle/ is gitignored build output; everything it
# needs is either in docs/design-system/ or in .design-sync/ (this dir).
#
# After running, upload with the DesignSync tool / the /design-sync skill into
# project 37a6c3fc-d40d-426c-ac6c-696d8902a252 (see config.json).
set -e
cd "$(dirname "$0")/.."
rm -rf ds-bundle
mkdir -p ds-bundle/tokens ds-bundle/guidelines/screenshots

# Derivable copies from the repo's design-system docs (source of truth)
cp docs/design-system/theme.css        ds-bundle/tokens/theme.css
cp docs/design-system/README.md        ds-bundle/guidelines/design-system.md
cp docs/design-system/CONFORMANCE.md   ds-bundle/guidelines/conformance.md
cp docs/design-system/screenshots/*.png ds-bundle/guidelines/screenshots/

# Authored (non-derivable) sources, kept in .design-sync/
cp .design-sync/styles.css ds-bundle/styles.css
cp .design-sync/brand.css  ds-bundle/tokens/brand.css

# README = conventions header + project overview
{
  cat .design-sync/conventions.md
  cat .design-sync/readme-overview.md
} > ds-bundle/README.md

# Upload sentinel
printf 'tokens-only sync sentinel\n' > ds-bundle/_ds_needs_recompile

echo "Built ds-bundle/ ($(find ds-bundle -type f | wc -l | tr -d ' ') files)"
