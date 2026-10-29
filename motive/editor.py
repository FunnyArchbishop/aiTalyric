"""Pure editing operations and bounded history for GUI parameter snapshots."""
from copy import deepcopy


class History:
    def __init__(self, limit=100):
        self.limit = limit
        self.items = []
        self.index = -1

    def record(self, state):
        state = deepcopy(state)
        if self.index >= 0 and self.items[self.index] == state:
            return
        self.items = self.items[:self.index + 1] + [state]
        self.items = self.items[-self.limit:]
        self.index = len(self.items) - 1

    def move(self, delta):
        target = self.index + delta
        if not 0 <= target < len(self.items):
            return None
        self.index = target
        return deepcopy(self.items[target])


def edit_sequence(sequence, index, action):
    result = list(sequence)
    if not result or not 0 <= index < len(result):
        raise ValueError("请选择有效的和弦位置")
    if action == "duplicate":
        result.insert(index + 1, result[index])
        index += 1
    elif action == "delete":
        if len(result) == 1:
            raise ValueError("至少保留一个和弦")
        result.pop(index)
        index = min(index, len(result) - 1)
    elif action in ("left", "right"):
        other = index + (-1 if action == "left" else 1)
        if 0 <= other < len(result):
            result[index], result[other] = result[other], result[index]
            index = other
    else:
        raise ValueError("未知编辑操作")
    return result, index
