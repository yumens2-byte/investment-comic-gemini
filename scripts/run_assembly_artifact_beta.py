"""Replay a generated episode artifact without database writes or provider calls."""
from __future__ import annotations

import json
from pathlib import Path

from engine.assembly.pil_composer import compose_episode
from scripts.run_resume import restore_panel_source


def main() -> None:
    episode = 'ICG-2026-10-02-001'
    date = '2026-10-02'
    root = Path('output/episodes/episodes') / date
    if not root.is_dir():
        root = Path('output/episodes') / date
    script = json.loads((root / f'{episode}_script.json').read_text())
    manifest = json.loads((root / f'{episode}_images.json').read_text())
    if script['episode_id'] != episode or manifest['episode_id'] != episode:
        raise ValueError('Artifact identity mismatch')
    images = [restore_panel_source(p['path'], date) for p in manifest['panels']]
    slides = compose_episode(script['panels'], images, Path('output/assembly-beta/slides'),
                             strict=True)
    from engine.publish.telegram_publisher import _validate_slides
    _validate_slides(slides)
    report = {'status': 'pass', 'episode_id': episode, 'slides': len(slides),
              'database_writes': 0, 'paid_calls': 0, 'publishes': 0,
              'source_images_verified': len(images)}
    Path('output/assembly-beta/report.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report))


if __name__ == '__main__':
    main()
