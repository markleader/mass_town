from collections import deque


class TaskQueue:
    def __init__(self, tasks: list[str] | None = None) -> None:
        self._queue = deque(tasks or [])

    def pop_next(self) -> str | None:
        return self._queue.popleft() if self._queue else None

    def push_front(self, task: str) -> None:
        self._queue.appendleft(task)

    def extend(self, tasks: list[str]) -> None:
        self._queue.extend(tasks)

    def replace(self, tasks: list[str]) -> None:
        self._queue.clear()
        self._queue.extend(tasks)

    def is_empty(self) -> bool:
        return not self._queue

    def snapshot(self) -> list[str]:
        return list(self._queue)
