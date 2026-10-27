"""Associate body images with adjacent figure captions without reusing a caption."""

from __future__ import annotations

from collections.abc import Callable, Sequence


def pair_figure_captions(
    body_texts: Sequence[str],
    image_body_indices: set[int],
    caption_text: Callable[[str], str],
) -> dict[int, tuple[str, int, str]]:
    """Return image index -> (caption, caption index, relative order).

    A run of consecutive images can share one following caption. Empty layout
    paragraphs do not divide the run; visible prose does. Following captions
    take priority, while a preceding caption is accepted only if no earlier
    image run has already claimed it.
    """
    meaningful = [
        index for index, text in enumerate(body_texts)
        if text.strip() or index in image_body_indices
    ]
    position = {index: ordinal for ordinal, index in enumerate(meaningful)}
    runs: list[list[int]] = []
    current: list[int] = []
    for index in meaningful:
        if index not in image_body_indices:
            if current:
                runs.append(current)
                current = []
            continue
        current.append(index)
        if caption_text(body_texts[index]):
            runs.append(current)
            current = []
    if current:
        runs.append(current)

    paired: dict[int, tuple[str, int, str]] = {}
    claimed_captions: set[int] = set()
    pending: list[list[int]] = []
    for run in runs:
        last = run[-1]
        same = caption_text(body_texts[last])
        next_position = position[last] + 1
        next_index = meaningful[next_position] if next_position < len(meaningful) else -1
        following = (
            caption_text(body_texts[next_index])
            if next_index >= 0 and next_index not in image_body_indices else ""
        )
        if same:
            caption, caption_index, order = same, last, "same"
        elif following and next_index not in claimed_captions:
            caption, caption_index, order = following, next_index, "after"
        else:
            pending.append(run)
            continue
        claimed_captions.add(caption_index)
        paired.update({index: (caption, caption_index, order) for index in run})

    for run in pending:
        first = run[0]
        previous_position = position[first] - 1
        previous_index = meaningful[previous_position] if previous_position >= 0 else -1
        if previous_index < 0 or previous_index in claimed_captions:
            continue
        preceding = caption_text(body_texts[previous_index])
        if not preceding or previous_index in image_body_indices:
            continue
        claimed_captions.add(previous_index)
        paired.update({index: (preceding, previous_index, "before") for index in run})
    return paired
