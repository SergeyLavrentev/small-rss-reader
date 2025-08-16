from PyQt5.QtWidgets import (
    QDialog, QFormLayout, QLineEdit, QDialogButtonBox, QSpinBox, QLabel, QCheckBox, QPushButton, QFontComboBox, QComboBox, QMessageBox, QHBoxLayout
)
from PyQt5.QtGui import QFont, QIcon, QPixmap
from PyQt5.QtCore import Qt, QSettings



class AddFeedDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add New Feed")
        self.setModal(True)
        self.setFixedSize(400, 150)
        self.setup_ui()

    def setup_ui(self):
        layout = QFormLayout(self)
        self.name_input = QLineEdit(self)
        self.name_input.setPlaceholderText("Enter custom feed name (optional)")
        layout.addRow("Feed Name:", self.name_input)
        self.url_input = QLineEdit(self)
        self.url_input.setPlaceholderText("Enter feed URL")
        layout.addRow("Feed URL:", self.url_input)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addRow(self.buttons)

    def get_inputs(self):
        return self.name_input.text().strip(), self.url_input.text().strip()

    def accept(self):
        feed_name, feed_url = self.get_inputs()
        if not feed_url:
            # parent expected to have warn()
            if hasattr(self.parent(), 'warn'):
                self.parent().warn("Input Error", "Feed URL is required.")
            return
        super().accept()


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.parent = parent
        self.setup_ui()

    def setup_ui(self):
        layout = QFormLayout(self)
        self.api_key_input = QLineEdit(self)
        self.api_key_input.setEchoMode(QLineEdit.Password)
        # Load from secrets helper (Keychain) if available; fallback to parent value if empty
        existing_key = ''
        try:
            from rss_reader.utils.secrets import get_omdb_api_key
            existing_key = get_omdb_api_key() or ''
        except Exception:
            existing_key = ''
        if not existing_key:
            existing_key = getattr(self.parent, 'api_key', '') or ''
        self.api_key_input.setText(existing_key)
        # Keep parent cache in sync so notice reflects reality
        try:
            if hasattr(self.parent, 'api_key') and existing_key:
                self.parent.api_key = existing_key
        except Exception:
            pass
        layout.addRow("OMDb API Key:", self.api_key_input)
        # Row with Test button
        test_row = QHBoxLayout()
        self.test_key_btn = QPushButton("Test OMDb Key", self)
        self.test_key_btn.clicked.connect(self.test_api_key)
        test_row.addWidget(self.test_key_btn)
        test_row.addStretch(1)
        layout.addRow("", self._wrap_in_widget(test_row))
        self.api_key_notice = QLabel()
        self.api_key_notice.setStyleSheet("color: red;")
        self.update_api_key_notice()
        layout.addRow("", self.api_key_notice)
        self.refresh_interval_input = QSpinBox(self)
        self.refresh_interval_input.setRange(1, 1440)
        self.refresh_interval_input.setValue(getattr(self.parent, 'refresh_interval', 60))
        layout.addRow("Refresh Interval (minutes):", self.refresh_interval_input)
        self.font_name_combo = QFontComboBox(self)
        self.font_name_combo.setCurrentFont(getattr(self.parent, 'default_font', QFont("Arial", 12)))
        layout.addRow("Font Name:", self.font_name_combo)
        self.font_size_spin = QSpinBox(self)
        self.font_size_spin.setRange(8, 48)
        self.font_size_spin.setValue(getattr(self.parent, 'current_font_size', 12))
        layout.addRow("Font Size:", self.font_size_spin)
        self.global_notifications_checkbox = QCheckBox("Enable Notifications", self)
        settings = QSettings('rocker', 'SmallRSSReader')
        global_notifications = settings.value('notifications_enabled', False, type=bool)
        self.global_notifications_checkbox.setChecked(global_notifications)
        layout.addRow("Global Notifications:", self.global_notifications_checkbox)
        self.tray_icon_checkbox = QCheckBox("Enable Tray Icon", self)
        tray_icon_enabled = settings.value('tray_icon_enabled', True, type=bool)
        self.tray_icon_checkbox.setChecked(tray_icon_enabled)
        layout.addRow("Tray Icon:", self.tray_icon_checkbox)
        self.icloud_backup_checkbox = QCheckBox("Enable iCloud Backup", self)
        icloud_enabled = settings.value('icloud_backup_enabled', False, type=bool)
        self.icloud_backup_checkbox.setChecked(icloud_enabled)
        layout.addRow("iCloud Backup:", self.icloud_backup_checkbox)
        self.restore_backup_button = QPushButton("Restore from iCloud", self)
        self.restore_backup_button.clicked.connect(self.restore_backup)
        layout.addRow("", self.restore_backup_button)
        self.log_level_combo = QComboBox(self)
        self.log_level_combo.addItems(["ERROR", "WARNING", "INFO", "DEBUG"]) 
        current_level = settings.value('log_level', 'INFO')
        if current_level not in ["ERROR", "WARNING", "INFO", "DEBUG"]:
            current_level = 'INFO'
        self.log_level_combo.setCurrentText(current_level)
        layout.addRow("Log level:", self.log_level_combo)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addRow(self.buttons)
        self.max_days_input = QSpinBox(self)
        self.max_days_input.setRange(1, 365)
        self.max_days_input.setValue(getattr(self.parent, 'max_days', 30))
        layout.addRow("Max Days to Keep Articles:", self.max_days_input)

    def _wrap_in_widget(self, layout):
        # Helper to place a layout as a form row
        from PyQt5.QtWidgets import QWidget
        w = QWidget(self)
        w.setLayout(layout)
        return w

    def update_api_key_notice(self):
        if not getattr(self.parent, 'api_key', ''):
            self.api_key_notice.setText("Ratings feature is disabled without an API key.")
        else:
            self.api_key_notice.setText("")

    def restore_backup(self):
        if hasattr(self.parent, 'restore_from_icloud'):
            self.parent.restore_from_icloud()

    def save_settings(self):
        api_key = (self.api_key_input.text() or "").strip()
        # Normalize using shared sanitizer (handles spaces and invisible chars)
        try:
            from rss_reader.utils.secrets import sanitize_omdb_api_key
            sanitized = sanitize_omdb_api_key(api_key)
        except Exception:
            sanitized = api_key.replace(" ", "")
        if sanitized != api_key:
            api_key = sanitized
            self.api_key_input.setText(api_key)
        refresh_interval = self.refresh_interval_input.value()
        font_name = self.font_name_combo.currentFont().family()
        font_size = self.font_size_spin.value()
        # Persist API key via secrets helper (handles Keychain + fallback)
        try:
            from rss_reader.utils.secrets import set_omdb_api_key
            set_omdb_api_key(api_key)
        except Exception:
            pass
        # reset OMDb queue auth-failed state if present
        try:
            if hasattr(self.parent, '_omdb_mgr') and self.parent._omdb_mgr:
                self.parent._omdb_mgr.set_auth_failed(False)
            if hasattr(self.parent, '_clear_omdb_status'):
                self.parent._clear_omdb_status()
        except Exception:
            pass
        if hasattr(self.parent, 'api_key'):
            self.parent.api_key = api_key
        if hasattr(self.parent, 'refresh_interval'):
            self.parent.refresh_interval = refresh_interval
        if hasattr(self.parent, 'current_font_size'):
            self.parent.current_font_size = font_size
        if hasattr(self.parent, 'default_font'):
            self.parent.default_font = QFont(font_name, font_size)
        notifications_enabled = self.global_notifications_checkbox.isChecked()
        tray_icon_enabled = self.tray_icon_checkbox.isChecked()
        icloud_enabled = self.icloud_backup_checkbox.isChecked()
        settings = QSettings('rocker', 'SmallRSSReader')
        settings.setValue('refresh_interval', refresh_interval)
        settings.setValue('font_name', font_name)
        settings.setValue('font_size', font_size)
        settings.setValue('notifications_enabled', notifications_enabled)
        settings.setValue('tray_icon_enabled', tray_icon_enabled)
        settings.setValue('icloud_backup_enabled', icloud_enabled)
        if hasattr(self.parent, 'icloud_backup_enabled'):
            self.parent.icloud_backup_enabled = icloud_enabled
        if hasattr(self.parent, 'update_refresh_timer'):
            self.parent.update_refresh_timer()
        if hasattr(self.parent, 'apply_font_size'):
            self.parent.apply_font_size()
        # If API key was entered, kick OMDb fetching for current feed
        try:
            if api_key and hasattr(self.parent, '_on_feed_selected'):
                self.parent._on_feed_selected()
        except Exception:
            pass
        self.update_api_key_notice()

    def accept(self):
        self.save_settings()
        super().accept()

    def test_api_key(self):
        key = (self.api_key_input.text() or "").strip()
        # Normalize with the same sanitizer used for storage
        try:
            from rss_reader.utils.secrets import sanitize_omdb_api_key
            key_sanitized = sanitize_omdb_api_key(key)
        except Exception:
            key_sanitized = key.replace(" ", "")
        if key_sanitized != key:
            key = key_sanitized
            self.api_key_input.setText(key)
        if not key:
            QMessageBox.information(self, "Test OMDb Key", "Enter API key first.")
            return
        try:
            import urllib.request, json
            url = f"https://www.omdbapi.com/?i=tt3896198&apikey={key}"
            req = urllib.request.Request(url, headers={"User-Agent": "SmallRSSReader/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:  # nosec - user-initiated check
                payload = resp.read()
            data = json.loads(payload.decode('utf-8', 'ignore'))
            if isinstance(data, dict) and str(data.get('Response', '')).lower() == 'true':
                QMessageBox.information(self, "Test OMDb Key", "Key works. OMDb responded successfully.")
            else:
                err = data.get('Error') if isinstance(data, dict) else 'Unknown error'
                QMessageBox.warning(self, "Test OMDb Key", f"OMDb error: {err}")
        except Exception as e:
            QMessageBox.critical(self, "Test OMDb Key", f"Request failed: {e}")
