# The README's recording, part two: the two runs compared.
# `just demo` puts the runs' ids in place of BEFORE AFTER and records it after demo.tape.
Output compare.mp4
Set Shell bash
Set FontSize 16
Set Width 1000
Set Height 620
Set Padding 24
Set Theme { "name": "convy", "background": "#15181e", "foreground": "#e4e7ec", "cursor": "#5fc48a", "selection": "#2e3440", "black": "#15181e", "red": "#ef7b70", "green": "#5fc48a", "yellow": "#e0b155", "blue": "#9db4ff", "magenta": "#c9a8ff", "cyan": "#7fd1d6", "white": "#e4e7ec", "brightBlack": "#a3abb8", "brightRed": "#ef7b70", "brightGreen": "#5fc48a", "brightYellow": "#e0b155", "brightBlue": "#9db4ff", "brightMagenta": "#c9a8ff", "brightCyan": "#7fd1d6", "brightWhite": "#ffffff" }
Hide
Type "export PS1='$ ' && alias convy='uv run -q --project ../.. convy' && clear" Enter
Sleep 500ms
Show
Sleep 500ms
Type "convy compare BEFORE AFTER" Sleep 500ms Enter
Sleep 3s
