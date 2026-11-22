# Lookup

A fast desktop app for searching a textbook and slide PDFs during an exam.
<img width="1360" height="699" alt="image" src="https://github.com/user-attachments/assets/28d8c3ba-31d6-4e7e-b2c6-2637c9b10b20" />


## Download

`Lookup-Windows.zip` is the Windows app, version 1.3.0. It runs on 64-bit Windows 10 and Windows 11. Download it from the [releases page](https://github.com/sbf-developer/lookup-pdf-search/releases), unzip it, and open `Lookup.exe`.

Windows may say it protected your PC the first time, because the app is not signed. Choose More info, then Run anyway.

To run it from this folder instead, double-click `run.bat`. The first launch installs what it needs. After that it opens straight away.

Add PDFs with **Add PDFs**, or drop them on the window. The last files reopen next time.

## Search

Type in the bar. Results update as you type, including halfway through a word: `balanced scoreca` finds `balanced scorecard`. Arrow keys move through hits: the page jumps to the words, and the right panel shows the hit plus the sentences that follow it.

**Broad** is the default. It also finds close wording, so `data mining` matches `data mine`, light typos, and words that sound similar.

**Exact** finds the words in the order you typed. Ctrl+B switches mode.

## Keys

- ↑ ↓ move through hits
- Ctrl+O add PDFs
- Ctrl+F search
- Ctrl+B Exact / Broad
- Ctrl+0 fit the page
- Ctrl+scroll zoom

Scanned PDFs with no text layer cannot be searched. The file chip says “no text” when that happens.
