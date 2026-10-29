"""Heuristic harmonic tension map; values are relative, not perceptual measurements."""
import theory


def points(mode, previous=None):
    vocab = theory.CHORD_VOCAB[mode]
    by_name = {c[0]: c for c in vocab}
    prev = by_name.get(previous)
    result = []
    for chord in vocab:
        label, offsets, role, target, bass, penalty = chord
        pcs = sorted(set(o % 12 for o in offsets))
        intervals = [min((b-a) % 12, (a-b) % 12)
                     for i, a in enumerate(pcs) for b in pcs[i+1:]]
        rough = sum({1: 1., 2: .65, 6: .9}.get(d, 0.) for d in intervals)
        x = min(1., .12 + rough / 3 + {"T": 0., "S": .12, "D": .25}[role] + penalty * .2)
        y = 0.
        if prev:
            old = set(o % 12 for o in prev[1])
            distance = sum(min(min((a-b) % 12, (b-a) % 12) for b in pcs) for a in old) / len(old)
            functional = (0. if offsets[0] == prev[3] else 2.) if prev[3] is not None else theory.ROLE_COST[prev[2], role]
            y = min(1., distance / 6 + functional / 4)
        result.append(dict(label=label, x=x, y=y, role=role))
    return result


class TensionMap:
    def __init__(self, parent, on_select, on_edit=None, on_history=None):
        import tkinter as tk
        from tkinter import ttk
        self.tk, self.on_select = tk, on_select
        self.sequence, self.mode, self.index = [], "major", 0
        ttk.Label(parent, text="先选进行位置，再点击和弦点替换；重叠点会弹出选择菜单。").pack(anchor="w")
        self.position = ttk.Combobox(parent, state="readonly", width=35)
        self.position.pack(anchor="w", pady=6)
        self.position.bind("<<ComboboxSelected>>", self.choose_position)
        toolbar = ttk.Frame(parent)
        toolbar.pack(fill="x")
        if on_edit:
            for label, action in (("复制并插入", "duplicate"), ("删除", "delete"),
                                  ("左移", "left"), ("右移", "right")):
                ttk.Button(toolbar, text=label, command=lambda a=action: on_edit(a)).pack(side="left")
        if on_history:
            ttk.Button(toolbar, text="撤销", command=lambda: on_history(-1)).pack(side="left")
            ttk.Button(toolbar, text="重做", command=lambda: on_history(1)).pack(side="left")
        self.canvas = tk.Canvas(parent, background="#1b1b1f", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self.draw())
        self.canvas.bind("<Button-1>", self.click)
        self.canvas.bind("<Motion>", self.hover)
        self.curve = tk.Canvas(parent, height=130, background="#22222a", highlightthickness=0)
        self.curve.pack(fill="x")
        self.curve.bind("<Configure>", lambda e: self.draw_curve())
        self.curve.bind("<Button-1>", self.select_curve)
        self.caption = tk.StringVar()
        ttk.Label(parent, textvariable=self.caption).pack(anchor="w")
        ttk.Label(parent, text="规则估计，范围 0–1；首个和弦无前驱，转换张力为 0。").pack(anchor="w")
        self.targets = []
        self.curve_targets = []

    def update(self, mode, sequence):
        self.mode, self.sequence = mode, list(sequence)
        self.index = min(self.index, max(0, len(sequence)-1))
        self.position["values"] = [f"{i+1}. {c}" for i, c in enumerate(sequence)]
        if sequence:
            self.position.current(self.index)
        self.draw()

    def choose_position(self, event):
        self.index = self.position.current()
        self.draw()

    def draw(self):
        c = self.canvas
        c.delete("all")
        self.targets = []
        if not self.sequence:
            return
        w, h = max(c.winfo_width(), 250), max(c.winfo_height(), 200)
        left, top, right, bottom = 65, 35, w-40, h-55
        c.create_line(left, top, left, bottom, right, bottom, fill="#999999")
        c.create_text(w/2, h-15, text="和弦自身紧张度 →", fill="white")
        c.create_text(20, h/2, text="转换张力 →", angle=90, fill="white")
        for value in (0., .25, .5, .75, 1.):
            x, y = left+value*(right-left), bottom-value*(bottom-top)
            c.create_text(x, bottom+14, text=str(value), fill="#aaaaaa")
            c.create_text(left-20, y, text=str(value), fill="#aaaaaa")
        previous = self.sequence[self.index-1] if self.index else None
        self.caption.set("前一个和弦：%s　当前：%s" % (previous or "无", self.sequence[self.index]))
        self.draw_curve()
        for p in points(self.mode, previous):
            x, y = left+p["x"]*(right-left), bottom-p["y"]*(bottom-top)
            self.targets.append((x, y, p["label"]))
            color = "#ffcc55" if p["label"] == self.sequence[self.index] else {"T":"#70cfa4", "S":"#70bfff", "D":"#ed8695"}[p["role"]]
            c.create_oval(x-6, y-6, x+6, y+6, fill=color, outline="white")
            c.create_text(x, y-14, text=p["label"], fill=color)

    def draw_curve(self):
        c = self.curve
        c.delete("all")
        self.curve_targets = []
        if not self.sequence:
            return
        w = max(c.winfo_width(), 250)
        c.create_text(8, 10, anchor="w", text="进行紧张度轨迹（点击编号切换位置）：黄色=自身，蓝色=转换", fill="white")
        rows = []
        for i, label in enumerate(self.sequence):
            p = next(p for p in points(self.mode, self.sequence[i-1] if i else None) if p["label"] == label)
            rows.append(p)
        for key, color in (("x", "#ffcc55"), ("y", "#70bfff")):
            coords = []
            for i, p in enumerate(rows):
                x = 35 + (w-70) * i / max(1, len(rows)-1)
                y = 95 - p[key] * 65
                coords.extend((x, y))
                c.create_oval(x-3,y-3,x+3,y+3,fill=color,outline=color)
                if key == "x":
                    self.curve_targets.append((x, i))
                    c.create_text(x, 114, text=str(i+1), fill="white" if i != self.index else "#ffcc55")
            if len(rows) > 1:
                c.create_line(*coords, fill=color, width=2)

    def select_curve(self, event):
        if not self.curve_targets:
            return
        _, self.index = min(self.curve_targets, key=lambda item: abs(item[0]-event.x))
        self.position.current(self.index)
        self.draw()

    def hover(self, event):
        if not self.targets:
            return
        x, y, label = min(self.targets, key=lambda p: (p[0]-event.x)**2+(p[1]-event.y)**2)
        if (x-event.x)**2+(y-event.y)**2 > 400:
            return
        previous = self.sequence[self.index-1] if self.index else None
        p = next(p for p in points(self.mode, previous) if p["label"] == label)
        self.caption.set("%s | 功能 %s | 自身紧张度 %.2f | 转换张力 %.2f" %
                         (label, p["role"], p["x"], p["y"]))

    def click(self, event):
        near = [(x-event.x)**2+(y-event.y)**2 for x,y,_ in self.targets]
        if not near or min(near) > 400:
            return
        nearest = min(range(len(near)), key=near.__getitem__)
        x, y, _ = self.targets[nearest]
        labels = [label for px,py,label in self.targets if (px-x)**2+(py-y)**2 < 100]
        if len(labels) == 1:
            self.on_select(self.index, labels[0])
        else:
            menu = self.tk.Menu(self.canvas, tearoff=False)
            for label in labels:
                menu.add_command(label=label, command=lambda v=label: self.on_select(self.index, v))
            try:
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                menu.grab_release()
