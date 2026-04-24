"""Source loaders — abstract over where code comes from."""

from aquila_atlas.ingestion.sources._common import (
    EXT_TO_LANG,
    RawFile,
    SourceLoader,
    _should_ignore,
    detect_languages,
)
from aquila_atlas.ingestion.sources.git_clone import GitCloneLoader
from aquila_atlas.ingestion.sources.gitea import GiteaLoader
from aquila_atlas.ingestion.sources.github import GitHubLoader
from aquila_atlas.ingestion.sources.gitlab import GitLabLoader
from aquila_atlas.ingestion.sources.local import LocalFolderLoader
from aquila_atlas.ingestion.sources.zip import ZipLoader

__all__ = [
    "EXT_TO_LANG",
    "RawFile",
    "SourceLoader",
    "_should_ignore",
    "detect_languages",
    "GitCloneLoader",
    "GiteaLoader",
    "GitHubLoader",
    "GitLabLoader",
    "LocalFolderLoader",
    "ZipLoader",
]
