"""
PLAYGROUND — Phase 1 / Sources
================================
Explore the three source loaders: LocalFolder, Zip, GitHub.

Run:
    uv run python playground/phase1/01_sources.py
"""

from __future__ import annotations

from aquila_atlas.ingestion import LocalFolderLoader

# ──────────────────────────────────────────────
# 1. LOCAL FOLDER
# ──────────────────────────────────────────────
print("=" * 60)
print("LOCAL FOLDER LOADER")
print("=" * 60)

# Change this path to any folder you want to explore
TARGET = "aquila_atlas/ingestion"

loader = LocalFolderLoader(TARGET)
files = list(loader.load())

print(f"Label    : {loader.label()}")
print(f"Metadata : {loader.metadata()}")
print(f"Files    : {len(files)}\n")

for f in files:
    print(f"  {f.path:<50}  {f.size:>6} bytes")

# ──────────────────────────────────────────────
# 2. ZIP LOADER
# ──────────────────────────────────────────────
# Uncomment and point to a real zip to try this section.
'''
print("\n" + "=" * 60)
print("ZIP LOADER")
print("=" * 60)

zip_path = Path("my_repo.zip")
loader_zip = ZipLoader(zip_path)
files_zip = list(loader_zip.load())

print(f"Label    : {loader_zip.label()}")
print(f"Metadata : {loader_zip.metadata()}")
print(f"Files    : {len(files_zip)}\n")

for f in files_zip[:5]:
    print(f"  {f.path:<50}  {f.size:>6} bytes")
'''

# ──────────────────────────────────────────────
# 3. GITHUB LOADER
# ──────────────────────────────────────────────
# Requires GITHUB_TOKEN in your environment (or .env file).
# Uncomment and set the URL to try this section.

'''
import os
from aquila_atlas.config import get_settings
#
print("\n" + "=" * 60)
print("GITHUB LOADER")
print("=" * 60)
#
REPO_URL = "https://github.com/MohamadNesr/Deep-Reinforcement-Learning"
settings = get_settings()
#
loader_gh = GitHubLoader(REPO_URL, token=settings.github_token)
files_gh = list(loader_gh.load())
#
print(f"Label    : {loader_gh.label()}")
print(f"Metadata : {loader_gh.metadata()}")
print(f"Files    : {len(files_gh)}\n")
#
for f in files_gh[:10]:
    print(f"  {f.path:<60}  {f.size:>6} bytes")
'''
