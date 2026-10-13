"""FastAPI app. M0: read-only leads screens. No route here changes data or sends anything."""

import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from app.db import get_engine, init_db
from app.models import LEAD_STATUSES, LEGAL_ROUTES, Contact, Draft, Lead, Profile
from app.ui import labels

UI_DIR = Path(__file__).parent / "ui"


def create_app(engine: Engine | None = None) -> FastAPI:
    engine = engine or get_engine()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        init_db(engine)
        yield

    app = FastAPI(title="Outreach Agent", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/static", StaticFiles(directory=UI_DIR / "static"), name="static")

    templates = Jinja2Templates(directory=UI_DIR / "templates")
    templates.env.globals["labels"] = labels
    templates.env.globals["label"] = labels.label
    templates.env.filters["pretty"] = lambda value: json.dumps(value, ensure_ascii=False, indent=2)

    def get_session():
        with Session(engine) as session:
            yield session

    @app.get("/", include_in_schema=False)
    def index():
        return RedirectResponse("/leads")

    @app.get("/healthz", include_in_schema=False)
    def healthz():
        return {"ok": True}

    @app.get("/leads", response_class=HTMLResponse)
    def leads(
        request: Request,
        status: str = "",
        segment: str = "",
        route: str = "",
        min_score: str = "",
        q: str = "",
        session: Session = Depends(get_session),
    ):
        query = select(Lead)
        if status:
            query = query.where(Lead.status == status)
        if segment:
            query = query.where(Lead.segment == segment)
        if route:
            query = query.where(Lead.legal_route == route)
        min_score_value = int(min_score) if min_score.strip().isdigit() else None
        if min_score_value is not None:
            query = query.where(Lead.score >= min_score_value)
        if q.strip():
            query = query.where(Lead.company.contains(q.strip()))
        rows = session.exec(query.order_by(Lead.score.desc().nulls_last(), Lead.company)).all()

        draft_counts = dict(
            session.exec(
                select(Draft.lead_id, func.count(Draft.id))
                .where(Draft.status == "pending")
                .group_by(Draft.lead_id)
            ).all()
        )
        profiled = set(session.exec(select(Profile.lead_id)).all())
        segments = [s for s in session.exec(select(Lead.segment).distinct()).all() if s]
        total = session.exec(select(func.count(Lead.id))).one()

        context = {
            "leads": rows,
            "draft_counts": draft_counts,
            "profiled": profiled,
            "total": total,
            "filters": {"status": status, "segment": segment, "route": route, "min_score": min_score, "q": q},
            "statuses": LEAD_STATUSES,
            "routes": LEGAL_ROUTES,
            "segments": sorted(segments),
        }
        template = "_leads_table.html" if request.headers.get("HX-Request") else "leads.html"
        return templates.TemplateResponse(request, template, context)

    @app.get("/leads/{lead_id}", response_class=HTMLResponse)
    def lead_detail(lead_id: int, request: Request, session: Session = Depends(get_session)):
        lead = session.get(Lead, lead_id)
        if lead is None:
            raise HTTPException(status_code=404, detail="ליד לא נמצא")
        contacts = session.exec(select(Contact).where(Contact.lead_id == lead_id)).all()
        drafts = session.exec(
            select(Draft).where(Draft.lead_id == lead_id).order_by(Draft.status != "pending", Draft.kind, Draft.id)
        ).all()
        profile = session.exec(
            select(Profile).where(Profile.lead_id == lead_id).order_by(Profile.created_at.desc())
        ).first()
        return templates.TemplateResponse(
            request,
            "lead.html",
            {"lead": lead, "contacts": contacts, "drafts": drafts, "profile": profile},
        )

    return app


app = create_app()
