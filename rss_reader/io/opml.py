from typing import List, Dict
from PyQt5.QtWidgets import QFileDialog, QMessageBox


def export_opml(parent, feeds: List[Dict[str, str]]) -> None:
    path, _ = QFileDialog.getSaveFileName(parent, "Export OPML", "feeds.opml", "OPML Files (*.opml)")
    if not path:
        return
    try:
        import xml.etree.ElementTree as ET
        opml = ET.Element('opml', version='2.0')
        ET.SubElement(opml, 'head')
        body = ET.SubElement(opml, 'body')
        for f in feeds:
            url = f.get('url') or ''
            title = f.get('title') or url
            ET.SubElement(body, 'outline', text=title, type='rss', xmlUrl=url)
        tree = ET.ElementTree(opml)
        tree.write(path, encoding='utf-8', xml_declaration=True)
    except Exception as e:
        QMessageBox.warning(parent, "Export OPML", f"Failed to export OPML: {e}")


def import_opml(parent) -> List[Dict[str, str]]:
    path, _ = QFileDialog.getOpenFileName(parent, "Import OPML", "", "OPML Files (*.opml)")
    if not path:
        return []
    try:
        import xml.etree.ElementTree as ET
        tree = ET.parse(path)
        root = tree.getroot()
        out: List[Dict[str, str]] = []
        for o in root.findall('.//outline'):
            url = o.attrib.get('xmlUrl') or ''
            text = o.attrib.get('text') or url
            if url:
                out.append({'title': text, 'url': url})
        return out
    except Exception as e:
        QMessageBox.warning(parent, "Import OPML", f"Failed to import OPML: {e}")
        return []
