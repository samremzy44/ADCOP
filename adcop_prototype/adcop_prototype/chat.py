"""Terminal chat: play the learner. python chat.py"""
from adcop.bot import handle_message
print(handle_message("cli", "START"))
while True:
    print("\n" + handle_message("cli", input("> ")))
