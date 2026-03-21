import sys

# Theme Constants
BG_PRIMARY   = '#1e1e1e'
BG_SECONDARY = '#252525'
BG_TERTIARY  = '#2d2d2d'
ACCENT       = '#4a7fe0'
TEXT_PRIMARY = '#e8e8e8'
TEXT_MUTED   = '#888888'
SEPARATOR    = '#3a3a3a'

if sys.platform == 'win32':
    FONT_MAIN = ('Segoe UI', 12)
    FONT_HEADER = ('Segoe UI', 13, 'bold')
else:
    FONT_MAIN = ('Inter', 12)
    FONT_HEADER = ('Inter', 13, 'bold')
