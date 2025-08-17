import json
from typing import List, Dict
from PyQt5.QtWidgets import QFileDialog, QMessageBox


def import_json(parent) -> List[Dict[str, str]]:
    path, _ = QFileDialog.getOpenFileName(parent, "Import Feeds (JSON)", "", "JSON Files (*.json)")
    if not path:
        return []
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        feeds = data.get('feeds') if isinstance(data, dict) else data
        out: List[Dict[str, str]] = []
        for it in feeds or []:
            url = (it.get('url') if isinstance(it, dict) else None) or ''
            title = (it.get('title') if isinstance(it, dict) else None) or url
            if url:
                out.append({'title': title, 'url': url})
        return out
    except Exception as e:
        QMessageBox.warning(parent, "Import JSON", f"Failed to import: {e}")
        return []


def export_json(parent, feeds: List[Dict[str, str]]) -> None:
    path, _ = QFileDialog.getSaveFileName(parent, "Export Feeds (JSON)", "feeds.json", "JSON Files (*.json)")
    if not path:
        return
    try:
        payload = {'feeds': [{'title': f.get('title') or f.get('url'), 'url': f.get('url') or ''} for f in feeds]}
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception as e:
        QMessageBox.warning(parent, "Export JSON", f"Failed to export: {e}")
