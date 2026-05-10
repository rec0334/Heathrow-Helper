from bot import respond

QUERIES = [
    "what is SSSS",
    "what does PNR mean",
    "explain group 3",
    "timeline for 14:30 long-haul",
    "timeline for 09:15",
    "BA123 status",
    "AF1680 flight status",
    "Lufthansa terminal",
    "where is Emirates check in",
    "British Airways gate",
    "can I bring vape",
    "can I bring power bank",
    "can I bring lighter",
    "is hoverboard allowed",
    "can I take baby formula",
    "hello",
    "",
]

for q in QUERIES:
    print("=" * 60)
    print(f"USER : {q!r}")
    print("BOT  :")
    print(respond(q))
    print()
