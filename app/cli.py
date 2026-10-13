"""Command line: python -m app.cli {init-db,import,serve}"""

import argparse

from sqlmodel import Session

from app import config
from app.db import get_engine, init_db


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init-db", help="יצירת מסד הנתונים")
    imp = sub.add_parser("import", help="ייבוא לידים, פרופילים ורשימת הסרה")
    imp.add_argument("paths", nargs="+", help="קבצי CSV/JSON או תיקיות")
    serve = sub.add_parser("serve", help="הפעלת הממשק על 127.0.0.1")
    serve.add_argument("--port", type=int, default=config.PORT)
    args = parser.parse_args(argv)

    engine = get_engine()
    init_db(engine)

    if args.command == "init-db":
        print(f"מסד הנתונים מוכן: {config.DATABASE_URL}")
    elif args.command == "import":
        from app.leads.importer import import_paths

        with Session(engine) as session:
            report = import_paths(session, args.paths)
        print(report.summary())
    elif args.command == "serve":
        import uvicorn

        # Section 11: localhost only, never 0.0.0.0, until authentication exists.
        uvicorn.run("app.main:app", host=config.HOST, port=args.port)


if __name__ == "__main__":
    main()
