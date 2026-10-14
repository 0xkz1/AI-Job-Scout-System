#!/bin/bash
# PDF generator wrapper — uses /home symlink path (accessible from Obsidian Snap sandbox)
SCRIPT_DIR="/home/kz003/atelier/00_Kazuki/career/Job-Intelligence-System"
exec "${SCRIPT_DIR}/.venv/bin/python3" "${SCRIPT_DIR}/pdf_generator.py" "$@"
