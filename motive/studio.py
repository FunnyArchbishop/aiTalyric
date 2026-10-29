"""Independent harmony workstation: python studio.py, or --demo / --smoke."""
import argparse
import copy
import json
import math
from pathlib import Path
import queue
import shutil
import subprocess
import tempfile
import threading

import chord_library as library
import harmony_metrics as hm
import studio_project as project
import textures
from editor import History


class Studio:
    def __init__(self, root, initial=None):
        import tkinter as tk
        from tkinter import ttk
        self.tk, self.ttk, self.root = tk, ttk, root
        self.doc = project.validate(initial or project.default_project())
        self.saved_doc = copy.deepcopy(self.doc)
        import tkinter.font as tkfont
        families = set(tkfont.families(root))
        family = next((name for name in ('Noto Sans CJK SC','Microsoft YaHei','PingFang SC') if name in families), None)
        if family:
            for name in ('TkDefaultFont','TkTextFont','TkMenuFont','TkHeadingFont'):
                tkfont.nametofont(name).configure(family=family,size=10)
        style = ttk.Style(root)
        if 'clam' in style.theme_names():
            style.theme_use('clam')
        style.configure('Treeview',rowheight=26)
        self.history = History()
        self.history.record(self.doc)
        self.catalogue = library.catalogue()
        self.filtered, self.map_targets = [], []
        self.index, self.selected = 0, library.resolve(self.doc['progression'][0]['chord'])
        self.path, self.process, self.closed = None, None, False
        self.jobs, self.busy = queue.Queue(), False
        self.audio_generation = 0
        self.preview_dir = tempfile.TemporaryDirectory(prefix='aitalyric-studio-')
        self.status = tk.StringVar(value='就绪')
        root.title('aiTalyric · 和声工作台')
        root.geometry('1420x920')
        root.minsize(1100,760)
        root.protocol('WM_DELETE_WINDOW', self.close)
        bar = ttk.Frame(root,padding=5); bar.pack(fill='x')
        for text, fn in [('新建',self.new),('打开工程',self.open),('保存工程',self.save),
                         ('撤销',lambda:self.history_move(-1)),('重做',lambda:self.history_move(1)),
                         ('试听进行',self.play),('停止',self.stop),('试听选中和弦',self.audition),
                         ('MIDI',lambda:self.export('midi')),('WAV',lambda:self.export('wav')),
                         ('指标 CSV',lambda:self.export('csv'))]:
            ttk.Button(bar,text=text,command=lambda f=fn:self.guard(f)).pack(side='left',padx=2)
        settings = ttk.Frame(root,padding=5); settings.pack(fill='x')
        self.tempo = tk.StringVar(); self.tonic = tk.StringVar(); self.mode = tk.StringVar()
        self.instrument = tk.StringVar(); self.swing = tk.StringVar(); self.texture = tk.StringVar()
        import inst
        for label,var,values,width in [('BPM',self.tempo,None,6),('主音',self.tonic,library.NAMES,5),
                ('调式',self.mode,['major','minor','penta'],7),('乐器',self.instrument,list(inst.INSTRUMENTS),8),
                ('Swing 0–0.75',self.swing,None,6),('织体',self.texture,list(textures.BUILTINS),14)]:
            ttk.Label(settings,text=label).pack(side='left',padx=3)
            widget = ttk.Combobox(settings,textvariable=var,values=values,state='readonly',width=width) if values else ttk.Entry(settings,textvariable=var,width=width)
            widget.pack(side='left')
            if var is self.texture:
                self.texture_combo = widget
        ttk.Button(settings,text='应用设置',command=lambda:self.guard(self.apply_settings)).pack(side='left',padx=6)
        ttk.Button(settings,text='整体 −1 半音',command=lambda:self.guard(lambda:self.change_transpose(-1))).pack(side='left')
        ttk.Button(settings,text='整体 +1 半音',command=lambda:self.guard(lambda:self.change_transpose(1))).pack(side='left')
        panes = ttk.Panedwindow(root,orient='horizontal'); panes.pack(fill='both',expand=True)
        left = ttk.Frame(panes,padding=6); center = ttk.Frame(panes,padding=6)
        panes.add(left,weight=1); panes.add(center,weight=3)
        ttk.Label(left,text=f'独立和弦库 · {len(self.catalogue):,} 个去重配置').pack(anchor='w')
        filters = ttk.Frame(left); filters.pack(fill='x')
        self.search = tk.StringVar(); self.filter_root = tk.StringVar(value='全部根音')
        self.filter_quality = tk.StringVar(value='全部类型'); self.only_favorites = tk.BooleanVar()
        ttk.Entry(filters,textvariable=self.search,width=16).pack(side='left')
        ttk.Button(filters,text='搜索',command=self.filter).pack(side='left')
        self.search.trace_add('write',lambda *args:self.filter())
        for var,values in [(self.filter_root,['全部根音',*library.NAMES]),(self.filter_quality,['全部类型',*library.QUALITIES])]:
            cb=ttk.Combobox(left,textvariable=var,values=values,state='readonly');cb.pack(fill='x',pady=2)
            cb.bind('<<ComboboxSelected>>',lambda e:self.filter())
        ttk.Checkbutton(left,text='只看收藏',variable=self.only_favorites,command=self.filter).pack(anchor='w')
        self.library_list = tk.Listbox(left,width=35,height=18,exportselection=False)
        self.library_list.pack(fill='both',expand=True)
        self.library_list.bind('<<ListboxSelect>>',self.select_library)
        self.library_list.bind('<Double-Button-1>',lambda e:self.guard(self.replace))
        self.library_list.bind('<MouseWheel>',lambda e:None)
        self.page = 0
        paging=ttk.Frame(left);paging.pack(fill='x')
        ttk.Button(paging,text='上一页',command=lambda:self.page_move(-1)).pack(side='left')
        ttk.Button(paging,text='下一页',command=lambda:self.page_move(1)).pack(side='left')
        self.count=tk.StringVar();ttk.Label(left,textvariable=self.count).pack(anchor='w')
        self.details=tk.StringVar();ttk.Label(left,textvariable=self.details,wraplength=300).pack(fill='x',pady=5)
        commands=ttk.Frame(left);commands.pack(fill='x')
        ttk.Button(commands,text='收藏 / 取消',command=lambda:self.guard(self.favorite)).pack(side='left')
        ttk.Button(commands,text='追加',command=lambda:self.guard(self.append)).pack(side='left')
        ttk.Button(commands,text='替换当前位置',command=lambda:self.guard(self.replace)).pack(side='left')
        rec=ttk.Frame(left);rec.pack(fill='x',pady=5)
        self.target=tk.DoubleVar(value=.3)
        ttk.Label(rec,text='目标紧张度').pack(side='left')
        ttk.Scale(rec,from_=0,to=1,variable=self.target).pack(side='left')
        ttk.Button(left,text='推荐后续和弦（当前筛选范围）',command=lambda:self.guard(self.recommend)).pack(fill='x')
        notebook=ttk.Notebook(center);notebook.pack(fill='both',expand=True)
        polar=ttk.Frame(notebook);analysis=ttk.Frame(notebook);texture_tab=ttk.Frame(notebook)
        notebook.add(polar,text='极坐标与钢琴');notebook.add(analysis,text='八项指标');notebook.add(texture_tab,text='织体库编辑')
        ttk.Label(polar,text='角度＝五度圈根音；半径＝音程粗糙度。点击点选择，双击替换；重叠点弹出列表。').pack(anchor='w')
        self.map=tk.Canvas(polar,background='#141b28',height=350,highlightthickness=0);self.map.pack(fill='both',expand=True)
        self.map.bind('<Configure>',lambda e:self.draw_map());self.map.bind('<Button-1>',self.map_click)
        self.map.bind('<Double-Button-1>',lambda e:self.map_click(e,True))
        self.piano=tk.Canvas(polar,height=85,background='#1c2331',highlightthickness=0);self.piano.pack(fill='x')
        self.piano.bind('<Configure>',lambda e:self.draw_piano())
        self.metric_tree=ttk.Treeview(analysis,columns=('metric','current','average'),show='headings',height=8)
        for key,title in [('metric','指标'),('current','当前和弦'),('average','整段均值')]:
            self.metric_tree.heading(key,text=title);self.metric_tree.column(key,width=170)
        self.metric_tree.pack(fill='x')
        self.chart=tk.Canvas(analysis,height=220,background='#141b28',highlightthickness=0);self.chart.pack(fill='both',expand=True)
        self.chart.bind('<Configure>',lambda e:self.draw_metrics())
        ttk.Label(analysis,text='独立规则指标，均为 0–1；蓝线粗糙度，黄线离调比例。首和弦无前驱，四项转换值记 0，不参与转换均值。',wraplength=750).pack(anchor='w')
        self.texture_name=tk.StringVar(value='my_pattern')
        entrybar=ttk.Frame(texture_tab);entrybar.pack(fill='x')
        ttk.Label(entrybar,text='织体名称').pack(side='left');ttk.Entry(entrybar,textvariable=self.texture_name).pack(side='left')
        for label,fn in [('载入当前织体',self.load_texture_editor),('保存并应用',self.save_texture),('导入 JSON',self.import_texture),('导出 JSON',self.export_texture)]:
            ttk.Button(entrybar,text=label,command=lambda f=fn:self.guard(f)).pack(side='left')
        self.texture_editor=tk.Text(texture_tab,wrap='none',height=14);self.texture_editor.pack(fill='both',expand=True)
        ttk.Label(texture_tab,text='beats：循环拍数；events：at 起点、dur 时长、voice 音序号或 all/bass/upper、velocity 力度。\n超出和弦边界的音符会截断。自定义织体随工程保存。').pack(anchor='w')
        timeline=ttk.Frame(center);timeline.pack(fill='x',pady=6)
        self.sequence=ttk.Treeview(timeline,columns=('index','symbol','beats','voicing'),show='headings',height=5,selectmode='browse')
        for key,title,width in [('index','#',40),('symbol','和弦',150),('beats','拍数',65),('voicing','MIDI 配置',300)]:
            self.sequence.heading(key,text=title);self.sequence.column(key,width=width)
        self.sequence.pack(fill='x');self.sequence.bind('<<TreeviewSelect>>',self.select_position)
        actions=ttk.Frame(center);actions.pack(fill='x')
        for label,action in [('复制','duplicate'),('删除','delete'),('左移','left'),('右移','right')]:
            ttk.Button(actions,text=label,command=lambda a=action:self.guard(lambda:self.edit(a))).pack(side='left')
        self.beats=tk.StringVar(value='4')
        ttk.Label(actions,text='当前位置拍数').pack(side='left');ttk.Entry(actions,textvariable=self.beats,width=6).pack(side='left')
        ttk.Button(actions,text='设置',command=lambda:self.guard(self.set_beats)).pack(side='left')
        self.preset=tk.StringVar(value='pop')
        ttk.Combobox(actions,textvariable=self.preset,values=['pop','classic','jazz','canon','minor'],width=9,state='readonly').pack(side='left')
        ttk.Button(actions,text='套用进行',command=lambda:self.guard(self.apply_preset)).pack(side='left')
        generatebar=ttk.Frame(center);generatebar.pack(fill='x',pady=3)
        self.tension_curve=tk.StringVar(value='0.15,0.3,0.55,0.2')
        ttk.Label(generatebar,text='目标紧张曲线').pack(side='left')
        ttk.Entry(generatebar,textvariable=self.tension_curve,width=30).pack(side='left')
        ttk.Button(generatebar,text='生成进行',command=lambda:self.guard(self.generate)).pack(side='left')
        ttk.Button(generatebar,text='平滑声部连接',command=lambda:self.guard(lambda:self.commit(project.smooth_voicings(self.doc)))).pack(side='left')
        ttk.Label(root,textvariable=self.status,anchor='w',relief='sunken').pack(fill='x')
        root.bind('<Control-z>',lambda e:self.history_move(-1));root.bind('<Control-y>',lambda e:self.history_move(1))
        root.bind('<Control-s>',lambda e:self.guard(self.save))
        self.refresh(); self.filter(); self.load_texture_editor()
        self.poll_id=root.after(100,self.poll)

    def guard(self, fn):
        try:
            return fn()
        except (ValueError,OSError,KeyError,TypeError,json.JSONDecodeError) as exc:
            self.status.set('操作失败：'+str(exc))

    def commit(self, doc):
        self.doc=project.validate(doc)
        self.history.record(self.doc)
        self.stop()
        self.refresh()
        self.status.set('已更新工程（保存后持久保留）')

    def refresh(self):
        self.index=min(self.index,len(self.doc['progression'])-1)
        self.tempo.set(str(self.doc['tempo']));self.tonic.set(library.NAMES[self.doc['tonic']]);self.mode.set(self.doc['mode'])
        self.instrument.set(self.doc['instrument']);self.swing.set(str(self.doc['swing']));self.texture.set(self.doc['texture'])
        self.texture_combo['values']=list(textures.BUILTINS | self.doc['custom_textures'])
        self.chords,self.notes,self.analysis=project.render(self.doc)
        self.sequence.delete(*self.sequence.get_children())
        for i,(c,row) in enumerate(zip(self.chords,self.doc['progression'])):
            self.sequence.insert('', 'end', iid=str(i),values=(i+1,c['symbol'],row['beats'],' '.join(map(str,c['notes']))))
        self.sequence.selection_set(str(self.index));self.sequence.see(str(self.index))
        self.beats.set(str(self.doc['progression'][self.index]['beats']))
        self.draw_map();self.draw_metrics();self.show_selected()

    def apply_settings(self):
        p=copy.deepcopy(self.doc)
        p.update(tempo=float(self.tempo.get()),tonic=library.NAMES.index(self.tonic.get()),mode=self.mode.get(),
                 instrument=self.instrument.get(),swing=float(self.swing.get()),texture=self.texture.get())
        self.commit(p)

    def filter(self):
        query=self.search.get().lower().strip();root=self.filter_root.get();quality=self.filter_quality.get()
        favorites=set(self.doc['favorites'])
        self.filtered=[c for c in self.catalogue if (not query or query in (c['symbol']+' '+c['quality']+' '+c['id']).lower())
                       and (root=='全部根音' or library.NAMES[c['root']]==root)
                       and (quality=='全部类型' or c['quality']==quality)
                       and (not self.only_favorites.get() or c['id'] in favorites)]
        self.page=0;self.show_page();self.draw_map()

    def show_page(self):
        self.library_list.delete(0,'end')
        self.visible=self.filtered[self.page*200:(self.page+1)*200]
        for c in self.visible:
            self.library_list.insert('end',f"{c['symbol']}  {c['notes']}  开放{c['spread']}")
        self.count.set(f'{len(self.filtered):,} 项 · 第 {self.page+1}/{max(1,math.ceil(len(self.filtered)/200))} 页')

    def page_move(self,delta):
        self.page=max(0,min(max(0,(len(self.filtered)-1)//200),self.page+delta));self.show_page()

    def select_library(self,event=None):
        sel=self.library_list.curselection()
        if sel:
            self.selected=self.visible[sel[0]];self.show_selected()

    def show_selected(self):
        c=self.selected
        self.details.set(f"{c['symbol']} · {c['quality']} · 转位 {c['inversion']}\nMIDI: {c['notes']}\n粗糙度 {library.intrinsic(c['notes']):.3f}")
        self.draw_piano()

    def select_position(self,event=None):
        sel=self.sequence.selection()
        if sel:
            self.index=int(sel[0]);self.selected=self.chords[self.index]
            self.beats.set(str(self.doc['progression'][self.index]['beats']))
            self.draw_metrics();self.draw_map();self.show_selected()

    def draw_piano(self):
        c=self.piano;c.delete('all')
        if not self.selected:
            return
        notes=self.selected['notes'];lo=min(notes)//12*12;hi=min(127,(max(notes)//12+1)*12-1)
        w=max(c.winfo_width(),300);kw=w/(hi-lo+1)
        for n in range(lo,hi+1):
            black=n%12 in (1,3,6,8,10)
            fill='#5cbfbd' if n in notes else '#384354' if black else '#e5e9ee'
            x=(n-lo)*kw;c.create_rectangle(x,5,x+kw-1,65,fill=fill,outline='#151b26')
            c.create_text(x+kw/2,76,text=str(n),fill='white',font=('TkDefaultFont',8))

    def draw_map(self):
        if not hasattr(self,'map'):
            return
        c=self.map;c.delete('all');self.map_targets=[]
        w,h=max(300,c.winfo_width()),max(280,c.winfo_height());cx,cy=w/2,h/2;radius=min(w,h)*.36
        for value in (.25,.5,.75,1.):
            r=radius*(.2+.8*value);c.create_oval(cx-r,cy-r,cx+r,cy+r,outline='#34435b')
            c.create_text(cx+5,cy-r,text=f'{value:.2f}',fill='#92a1b5',anchor='w')
        for k in range(12):
            a=k*math.tau/12-math.pi/2
            c.create_line(cx,cy,cx+radius*math.cos(a),cy+radius*math.sin(a),fill='#273348')
            c.create_text(cx+(radius+20)*math.cos(a),cy+(radius+20)*math.sin(a),text=library.NAMES[(k*7)%12],fill='white')
        # Collapse equivalent voicings for a readable map, while keeping all in the library.
        representatives={}
        for chord in self.filtered:
            key=(chord['root'],chord['quality'])
            if key not in representatives or abs(chord['register']-48)+chord['inversion']+chord['spread'] < abs(representatives[key]['register']-48)+representatives[key]['inversion']+representatives[key]['spread']:
                representatives[key]=chord
        def xy(chord):
            a,t=library.polar(chord);r=radius*(.2+.8*t)
            return cx+r*math.cos(a),cy+r*math.sin(a)
        for chord in representatives.values():
            x,y=xy(chord);self.map_targets.append((x,y,chord))
            c.create_oval(x-4,y-4,x+4,y+4,fill='#56b8c1',outline='')
        if hasattr(self,'chords'):
            coords=[xy(chord) for chord in self.chords]
            for i in range(1,len(coords)):
                c.create_line(*coords[i-1],*coords[i],fill='#e8b45c',width=2,arrow='last')
            for i,(x,y) in enumerate(coords):
                c.create_oval(x-6,y-6,x+6,y+6,outline='white' if i==self.index else '#e8b45c',width=2)
                c.create_text(x+8,y-10,text=str(i+1),fill='#ffd780')

    def map_click(self,event,replace=False):
        nearby=[(x,y,chord) for x,y,chord in self.map_targets if (x-event.x)**2+(y-event.y)**2<=225]
        if not nearby:
            return
        def choose(chord):
            self.selected=chord;self.show_selected()
            if replace:self.guard(self.replace)
        if len(nearby)==1:
            choose(nearby[0][2]);return
        menu=self.tk.Menu(self.map,tearoff=False)
        for _,_,chord in sorted(nearby,key=lambda row:row[2]['symbol']):
            menu.add_command(label=chord['symbol'],command=lambda c=chord:choose(c))
        try:menu.tk_popup(event.x_root,event.y_root)
        finally:menu.grab_release()

    def draw_metrics(self):
        if not hasattr(self,'analysis'):return
        self.metric_tree.delete(*self.metric_tree.get_children())
        for key,label in hm.LABELS.items():
            self.metric_tree.insert('','end',values=(label,f"{self.analysis['rows'][self.index][key]:.3f}",f"{self.analysis['average'][key]:.3f}"))
        c=self.chart;c.delete('all');w,h=max(300,c.winfo_width()),max(160,c.winfo_height())
        for key,color in [('roughness','#56b8c1'),('chromaticity','#e8b45c')]:
            coords=[]
            for i,row in enumerate(self.analysis['rows']):
                x=35+i*(w-70)/max(1,len(self.chords)-1);y=h-30-row[key]*(h-60)
                coords.extend((x,y));c.create_oval(x-4,y-4,x+4,y+4,fill=color)
                c.create_text(x,h-12,text=str(i+1),fill='white')
            if len(coords)>2:c.create_line(*coords,fill=color,width=2)

    def append(self):
        p=copy.deepcopy(self.doc);p['progression'].append(dict(chord=self.selected['id'],beats=4.))
        project.validate(p);self.index=len(p['progression'])-1;self.commit(p)

    def replace(self):
        p=copy.deepcopy(self.doc);p['progression'][self.index]['chord']=self.selected['id'];self.commit(p)

    def edit(self,action):
        from editor import edit_sequence
        p=copy.deepcopy(self.doc);p['progression'],index=edit_sequence(p['progression'],self.index,action)
        project.validate(p);self.index=index;self.commit(p)

    def set_beats(self):
        p=copy.deepcopy(self.doc);p['progression'][self.index]['beats']=float(self.beats.get());self.commit(p)

    def favorite(self):
        p=copy.deepcopy(self.doc);cid=self.selected['id']
        if cid in p['favorites']:p['favorites'].remove(cid)
        else:p['favorites'].append(cid)
        self.commit(p);self.filter()

    def recommend(self):
        previous=self.chords[self.index]
        self.filtered=hm.recommend(previous,self.filtered,self.doc['tonic'],self.doc['mode'],self.target.get(),limit=30)
        self.page=0;self.show_page();self.draw_map();self.status.set('已按目标紧张度、声部移动、调内性与共同音排序；搜索可恢复完整列表')

    def generate(self):
        values=[float(x.strip()) for x in self.tension_curve.get().replace('，',',').split(',')]
        self.commit(project.generate(self.doc,values))

    def change_transpose(self,delta):
        self.commit(project.transpose(self.doc,delta))

    def apply_preset(self):
        patterns={'pop':[(0,'maj'),(7,'maj'),(9,'min'),(5,'maj')],
                  'classic':[(0,'maj'),(5,'maj'),(7,'7'),(0,'maj')],
                  'jazz':[(2,'min7'),(7,'7'),(0,'maj7'),(9,'min7')],
                  'canon':[(0,'maj'),(7,'maj'),(9,'min'),(4,'min'),(5,'maj'),(0,'maj'),(5,'maj'),(7,'maj')],
                  'minor':[(0,'min'),(8,'maj'),(3,'maj'),(10,'maj')]}
        p=copy.deepcopy(self.doc)
        p['progression']=[dict(chord=library.make_chord((r+p['tonic'])%12,q)['id'],beats=4.) for r,q in patterns[self.preset.get()]]
        p['mode']='minor' if self.preset.get()=='minor' else 'major'
        self.index=0;self.commit(p)

    def history_move(self,delta):
        p=self.history.move(delta)
        if p is not None:self.doc=p;self.stop();self.refresh();self.filter()
        return 'break'

    def confirm_discard(self):
        from tkinter import messagebox
        if self.doc == self.saved_doc:return True
        return messagebox.askyesno('切换工程','尚未保存的修改可能丢失，是否继续？',parent=self.root)

    def new(self):
        if not self.confirm_discard():return
        self.path=None;self.history=History();self.commit(project.default_project());self.saved_doc=copy.deepcopy(self.doc);self.filter();self.load_texture_editor()

    def open(self):
        from tkinter import filedialog
        path=filedialog.askopenfilename(parent=self.root,filetypes=[('工程 JSON','*.json')])
        if path:
            doc=project.load(path)
            if not self.confirm_discard():return
            self.path=path;self.history=History();self.commit(doc);self.saved_doc=copy.deepcopy(self.doc);self.filter();self.load_texture_editor()

    def save(self):
        from tkinter import filedialog
        path=filedialog.asksaveasfilename(parent=self.root,defaultextension='.json',initialfile='harmony_project.json')
        if path:project.save(path,self.doc);self.path=path;self.saved_doc=copy.deepcopy(self.doc);self.status.set('已保存 '+path)

    def load_texture_editor(self):
        name=self.doc['texture'];pattern=(textures.BUILTINS|self.doc['custom_textures'])[name]
        self.texture_name.set(name if name not in textures.BUILTINS else name+'_custom')
        self.texture_editor.delete('1.0','end');self.texture_editor.insert('1.0',json.dumps(pattern,ensure_ascii=False,indent=2))

    def save_texture(self):
        name=self.texture_name.get().strip();pattern=textures.validate(json.loads(self.texture_editor.get('1.0','end')))
        p=copy.deepcopy(self.doc);p['custom_textures'][name]=pattern;p['texture']=name;self.commit(p)

    def import_texture(self):
        from tkinter import filedialog
        path=filedialog.askopenfilename(parent=self.root,filetypes=[('织体 JSON','*.json')])
        if not path:return
        if Path(path).stat().st_size>100_000:raise ValueError('织体文件超过 100 KB')
        pattern=textures.validate(json.loads(Path(path).read_text(encoding='utf-8')))
        self.texture_editor.delete('1.0','end');self.texture_editor.insert('1.0',json.dumps(pattern,indent=2))
        self.texture_name.set(Path(path).stem);self.status.set('已载入织体；点击保存并应用使其进入工程')

    def export_texture(self):
        from tkinter import filedialog
        pattern=textures.validate(json.loads(self.texture_editor.get('1.0','end')))
        path=filedialog.asksaveasfilename(parent=self.root,defaultextension='.json',initialfile=self.texture_name.get()+'.json')
        if path:Path(path).write_text(json.dumps(pattern,indent=2),encoding='utf-8')

    def export(self,kind):
        from tkinter import filedialog
        ext={'midi':'.mid','wav':'.wav','csv':'.csv'}[kind]
        path=filedialog.asksaveasfilename(parent=self.root,defaultextension=ext,initialfile='harmony'+ext)
        if path:
            if kind=='wav':self.background_render(path,False,self.doc)
            else:project.export(path,self.doc,kind);self.status.set('已导出 '+path)

    def play(self):
        self.background_render(str(Path(self.preview_dir.name)/'preview.wav'),True,self.doc)

    def audition(self):
        p=copy.deepcopy(self.doc);p['progression']=[dict(chord=self.selected['id'],beats=2.)];p['texture']='block'
        self.background_render(str(Path(self.preview_dir.name)/'chord.wav'),True,p)

    def background_render(self,path,play,doc):
        if self.busy:
            self.status.set('正在渲染，请稍候');return
        if sum(row['beats'] for row in doc['progression'])*60/doc['tempo']>600:
            raise ValueError('单次 WAV 最长 10 分钟，请缩短进行或导出 MIDI')
        self.stop();self.busy=True;self.status.set('正在渲染音频…')
        generation=self.audio_generation
        snapshot=copy.deepcopy(doc)
        def job():
            try:project.export(path,snapshot,'wav');self.jobs.put((path,play,None,generation))
            except Exception as exc:self.jobs.put((path,False,str(exc),generation))
        self.worker=threading.Thread(target=job,daemon=True);self.worker.start()

    def poll(self):
        if self.closed:return
        try:
            path,play,error,generation=self.jobs.get_nowait();self.busy=False
            if error:self.status.set('音频失败：'+error)
            else:
                self.status.set('已生成 '+path)
                if play and generation == self.audio_generation:
                    if shutil.which('ffplay'):
                        self.process=subprocess.Popen(['ffplay','-nodisp','-autoexit','-loglevel','error',path],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                    else:
                        try:
                            import winsound
                            winsound.PlaySound(path,winsound.SND_FILENAME|winsound.SND_ASYNC)
                        except ImportError:self.status.set('音频已生成；未安装 ffplay，请导出 WAV 后使用播放器试听')
        except queue.Empty:pass
        self.poll_id=self.root.after(100,self.poll)

    def stop(self):
        self.audio_generation += 1
        if self.process and self.process.poll() is None:self.process.terminate()
        self.process=None
        try:
            import winsound
            winsound.PlaySound(None,0)
        except ImportError:pass

    def close(self, force=False):
        if not force and self.doc != self.saved_doc and not self.confirm_discard():return
        self.stop();self.closed=True;self.root.after_cancel(self.poll_id)
        if not self.busy:self.preview_dir.cleanup()
        self.root.destroy()


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--build-db',metavar='PATH');ap.add_argument('--project');ap.add_argument('--demo',action='store_true');ap.add_argument('--smoke',action='store_true')
    ap.add_argument('--out',default='out_studio')
    args=ap.parse_args();doc=project.load(args.project) if args.project else project.default_project()
    if args.build_db:
        print('Database:',library.export_database(args.build_db),'voicings ->',args.build_db)
        if not args.demo:return
    if args.demo:
        out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
        project.save(out/'project.json',doc)
        for kind,extension in [('midi','mid'),('wav','wav'),('csv','csv')]:project.export(out/f'demo.{extension}',doc,kind)
        print(f'Catalogue: {len(library.catalogue())} unique voicings; exported demo to {out}')
        return
    import tkinter as tk
    root=tk.Tk();app=Studio(root,doc)
    if args.smoke:
        root.update();app.filter_root.set('C');app.filter();app.selected=library.make_chord(2,'min7');app.replace()
        app.edit('duplicate');app.edit('right');app.history_move(-1);app.apply_preset();root.update()
        assert len(app.map.find_all())>20 and len(app.metric_tree.get_children())==8
        assert app.chords[0]['symbol']=='C'
        app.close(force=True);print('Studio GUI smoke passed');return
    root.mainloop()


if __name__=='__main__':main()
