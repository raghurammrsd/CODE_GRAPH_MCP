from __future__ import annotations

from codegraph.search import SearchResult


def assemble_context(results: list[SearchResult], limit: int) -> str:
    pieces: list[str] = []
    used = 0
    seen: set[tuple[str, int, int]] = set()
    for result in results:
        identity = (result.file, result.start_line, result.end_line)
        if identity in seen:
            continue
        seen.add(identity)
        piece = f"# {result.file}:{result.start_line}-{result.end_line}\n{result.snippet}\n"
        if used + len(piece) > limit:
            break
        pieces.append(piece)
        used += len(piece)
    return "\n".join(pieces)
