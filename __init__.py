import os
from itertools import chain

import numpy as np
import scipy.sparse as sp
from anki import hooks
from aqt import gui_hooks, mw
from aqt.qt import *
from lxml.html import fromstring
from sklearn.feature_extraction.text import HashingVectorizer, TfidfTransformer
import joblib

# TODO:
# - Handle MathJax (requires re-doing view as html)
# - Make a default label for the label if no note is selected for query
# - Handle note syncing
# - When we show matching, we can use search "nid:" in the browser. Jump to
# note in browser on click

def field_text(flds):
    for fld in flds:
        yield fromstring(fld).text_content() if fld else ""

def init_counts():
    global count_extractor, tfidf, ids, counts, vecs
    id_list = []
    def note_iterator():
        for id, flds in mw.col.db.execute("select id, flds from notes order by id"):
            id_list.append(id)
            yield " ".join(field_text(flds.split(chr(0x1f))))
    counts = count_extractor.transform(note_iterator())
    ids = np.array(id_list, dtype=np.long)
    vecs = tfidf.fit_transform(counts)

def handle_open_window():
    global list_widget
    list_widget.show()

action = QAction("Show Similar Cards", mw)
action.triggered.connect(handle_open_window)
mw.form.menuTools.addAction(action)

class MatchItem(QWidget):
    def __init__(self, itr):
        super().__init__()
        vbox = QVBoxLayout()
        self.setLayout(vbox)
        for ix, a in enumerate(filter(None, itr)):
            if len(a) > 120:
                a = a[:120] + "..."
            label = QLabel(a)
            vbox.addWidget(label)
            if ix > 0:
                label.setIndent(50)

def handle_modified_note(note, query_counts):
    global dirty_counts, counts, vecs, ids
    ix = np.searchsorted(ids, note.id)
    counts = sp.vstack((counts[:ix,:], query_counts, counts[ix+1:,:]))
    vecs = tfidf.fit_transform(counts)

typing_cache = None
def handle_typing_timer(note):
    global typing_cache, list_widget, counts, ids
    text = " ".join(field_text(note.fields))
    text_hash = hash(text)
    if text_hash == typing_cache: return
    else:
        typing_cache = text_hash
        query_counts = count_extractor.transform([" ".join(note.fields)])
        query = tfidf.transform(query_counts)
        dot_prods = (vecs @ query.T).A[:,0]
        max_ixs = np.argpartition(-dot_prods, 5)[:9]
        matching_ids = ids[max_ixs[dot_prods[max_ixs] > 0.1]]
        matching_ids = matching_ids[matching_ids != note.id]
        list_widget.clear()
        for id, flds in mw.col.db.execute(
            f"select id, flds from notes where id in ({', '.join(map(str, matching_ids))})"):
            item = MatchItem(field_text(flds.split(chr(0x1f))))
            list_item = QListWidgetItem(list_widget)
            list_item.setSizeHint(item.sizeHint())
            list_widget.addItem(list_item)
            list_widget.setItemWidget(list_item, item)
            # eventually keep the ids so we can jump to them
        if note.id > 0:
            handle_modified_note(note, query)

gui_hooks.editor_did_fire_typing_timer.append(handle_typing_timer)
gui_hooks.editor_did_load_note.append(lambda editor: handle_typing_timer(editor.note))

def handle_deleted(_, note_ids):
    global dirty_counts, ids, counts, vecs
    for id in note_ids:
        ix = np.searchsorted(ids, id)
        counts = sp.vstack((counts[:ix,:], counts[ix+1:,:]))
        ids = np.concatenate((ids[:ix], ids[ix+1:]))
        vecs = tfidf.fit_transform(counts)
    dirty_counts = True
hooks.notes_will_be_deleted.append(handle_deleted)

def init_hook():
    global count_extractor, tfidf, list_widget
    list_widget = QListWidget()
    list_widget.setAlternatingRowColors(True)
    count_extractor = HashingVectorizer(
        stop_words='english', alternate_sign=False, norm=None)
    tfidf = TfidfTransformer()
    init_counts()

gui_hooks.main_window_did_init.append(init_hook)
