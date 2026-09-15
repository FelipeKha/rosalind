"""Build the import manifest payload sent to the backend."""

from cli.ingestion.discovery import FileInfo


def build_manifest(files: list[FileInfo]) -> dict[str, object]:
    return {
        "files": [
            {
                "path": info.path,
                "format": info.format,
                "size": info.size,
                "modified_at": info.modified_at.isoformat()
                if info.modified_at
                else None,
                "sha256": info.sha256,
            }
            for info in files
        ]
    }
