from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Theme:
    name: str
    dark: bool
    bg: str
    text: str
    muted: str
    soft: str
    border: str
    search_bg: str
    search_border: str
    panel: str
    viewer: str
    select: str
    hover: str
    found: str
    hit_bg: str
    hit_fg: str
    reader_bg: str
    title: str
    body: str
    button: str
    button_border: str
    mode_bg: str
    mode_on: str
    mode_on_text: str
    scroll: str
    status: str
    empty_title: str
    placeholder: str


LIGHT = Theme(
    name="light",
    dark=False,
    bg="#f6f6f7",
    text="#1d1d1f",
    muted="#6e6e73",
    soft="#3a3a3c",
    border="#e4e4e7",
    search_bg="#ffffff",
    search_border="#e1e1e4",
    panel="#ffffff",
    viewer="#ececef",
    select="#e7eefc",
    hover="#f3f4f6",
    found="#1d1d1f",
    hit_bg="#ffe7a3",
    hit_fg="#3f2e04",
    reader_bg="#ffffff",
    title="#6e6e73",
    body="#1d1d1f",
    button="#ffffff",
    button_border="#e1e1e4",
    mode_bg="#ececee",
    mode_on="#ffffff",
    mode_on_text="#1d1d1f",
    scroll="#c5c5ca",
    status="#f6f6f7",
    empty_title="#1d1d1f",
    placeholder="#8e8e93",
)

DARK = Theme(
    name="dark",
    dark=True,
    bg="#1e1e1e",
    text="#e6e6e6",
    muted="#8d8d8d",
    soft="#c8c8c8",
    border="#2a2a2a",
    search_bg="#2a2a2a",
    search_border="#343434",
    panel="#181818",
    viewer="#141414",
    select="#2c333d",
    hover="#22262c",
    found="#f7f7f7",
    hit_bg="#3a3118",
    hit_fg="#ffd98a",
    reader_bg="#181818",
    title="#a6a6a6",
    body="#f3f3f3",
    button="#2a2a2a",
    button_border="#3a3a3a",
    mode_bg="#2a2a2a",
    mode_on="#3a3a3a",
    mode_on_text="#f5f5f5",
    scroll="#3a3a3a",
    status="#181818",
    empty_title="#f2f2f2",
    placeholder="#6e6e6e",
)


def theme_for(name: str) -> Theme:
    return DARK if name == "dark" else LIGHT


def stylesheet(theme: Theme) -> str:
    return f"""
* {{ outline: none; }}

QWidget {{
    background: {theme.bg};
    color: {theme.text};
    font-family: "Segoe UI", sans-serif;
    font-size: 13px;
}}

QMainWindow, #topBar {{ background: {theme.bg}; }}
#topBar {{ border-bottom: 1px solid {theme.border}; }}

#brand {{
    color: {theme.found};
    font-size: 15px;
    font-weight: 600;
    background: transparent;
    padding: 0;
}}

QLineEdit#search {{
    background: {theme.search_bg};
    border: 1px solid {theme.search_border};
    border-radius: 8px;
    padding: 0 12px;
    color: {theme.text};
    font-size: 14px;
    selection-background-color: #2f4f86;
    selection-color: #ffffff;
    min-height: 34px;
}}
QLineEdit#search:focus {{ border-color: #3c6df0; }}
QLineEdit#search::placeholder {{ color: {theme.placeholder}; }}

#modeSwitch {{
    background: {theme.mode_bg};
    border-radius: 8px;
}}
#modeSwitch QPushButton {{
    background: transparent;
    color: {theme.muted};
    border: none;
    border-radius: 6px;
    padding: 4px 12px;
    min-height: 26px;
    min-width: 58px;
}}
#modeSwitch QPushButton:checked {{
    background: {theme.mode_on};
    color: {theme.mode_on_text};
}}
#modeSwitch QPushButton:hover:!checked {{ color: {theme.text}; }}

QPushButton#addButton, QPushButton#settingsButton {{
    background: {theme.button};
    color: {theme.text};
    border: 1px solid {theme.button_border};
    border-radius: 8px;
    padding: 4px 12px;
    min-height: 32px;
}}
QPushButton#addButton:hover, QPushButton#settingsButton:hover {{ background: {theme.hover}; }}

#resultsPanel, #readPanel {{ background: {theme.panel}; }}
#viewerPanel {{ background: {theme.viewer}; }}

#panelTitle {{
    color: {theme.text};
    font-size: 13px;
    font-weight: 600;
    background: transparent;
}}
#count, #echo, #source, #kicker, #pageLabel {{
    color: {theme.muted};
    background: transparent;
}}
#kicker {{ font-size: 11px; }}
#found {{
    color: {theme.found};
    font-size: 22px;
    font-weight: 600;
    background: transparent;
}}
#source {{ font-size: 12px; }}

QPushButton#chip {{
    background: transparent;
    color: {theme.soft};
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 3px 8px;
}}
QPushButton#chip:checked {{
    background: {theme.select};
    color: {theme.text};
}}
QPushButton#chip:hover:!checked {{ background: {theme.hover}; }}
QPushButton#chipX {{
    background: transparent;
    color: {theme.muted};
    border: none;
    padding: 0;
    font-size: 14px;
}}
QPushButton#chipX:hover {{ color: {theme.text}; }}

QListWidget#results {{
    background: {theme.panel};
    border: none;
    padding: 0;
    color: {theme.text};
}}
QListWidget#results::item {{ background: transparent; border: none; }}

QTextBrowser#reader {{
    background: {theme.reader_bg};
    color: {theme.text};
    border: none;
    selection-background-color: #2f4f86;
    selection-color: #ffffff;
}}

QScrollArea#pageScroll, QLabel#empty, QFrame#footer {{
    background: {theme.viewer};
    border: none;
    color: {theme.muted};
}}
QFrame#footer {{ border-top: 1px solid {theme.border}; }}
QLabel#empty {{ padding: 32px; }}

QPushButton#tool {{
    background: transparent;
    color: {theme.soft};
    border: none;
    border-radius: 6px;
    padding: 4px 8px;
    min-width: 28px;
}}
QPushButton#tool:hover {{ background: {theme.hover}; color: {theme.text}; }}
QPushButton#tool:checked {{ background: {theme.select}; color: {theme.text}; }}
QPushButton#tool:disabled {{ color: {theme.placeholder}; }}

QSplitter::handle {{ background: {theme.border}; }}

QStatusBar {{
    background: {theme.status};
    color: {theme.muted};
    border-top: 1px solid {theme.border};
}}
QStatusBar::item {{ border: none; }}

QProgressBar {{
    background: {theme.border};
    border: none;
    border-radius: 2px;
    max-height: 4px;
}}
QProgressBar::chunk {{
    background: #3c6df0;
    border-radius: 2px;
}}

QDialog#settings {{
    background: {theme.panel};
}}
QDialog#settings QLabel {{
    background: transparent;
    color: {theme.text};
}}
QDialog#settings QLabel#muted {{
    color: {theme.muted};
    background: transparent;
}}
QSlider::groove:horizontal {{
    height: 4px;
    background: {theme.border};
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    width: 14px;
    margin: -6px 0;
    background: #3c6df0;
    border-radius: 7px;
}}

QToolTip {{
    background: {theme.panel};
    color: {theme.text};
    border: 1px solid {theme.border};
    padding: 4px 6px;
}}

QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {theme.scroll};
    border-radius: 4px;
    min-height: 28px;
}}
QScrollBar::handle:vertical:hover {{ background: {theme.muted}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; background: none; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background: {theme.scroll};
    border-radius: 4px;
    min-width: 28px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; background: none; }}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: none; }}
"""


# Kept so older imports do not crash. The window applies a theme explicitly.
STYLESHEET = stylesheet(LIGHT)
